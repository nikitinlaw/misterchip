"""Backup failure handling and isolation invariants; no Docker or network calls."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ops import backup


class BackupSafetyTests(unittest.TestCase):
    def test_configuration_values_are_literal_and_duplicates_are_rejected(self):
        values = backup.parse_config("AWS_SECRET_ACCESS_KEY='$(touch /tmp/must-not-exist)'\n")
        self.assertEqual(values["AWS_SECRET_ACCESS_KEY"], "$(touch /tmp/must-not-exist)")
        with self.assertRaises(backup.OperationError):
            backup.parse_config("AWS_ACCESS_KEY_ID=one\nAWS_ACCESS_KEY_ID=two")

    def test_repository_must_be_offhost_https_without_embedded_credentials(self):
        for endpoint in (
            "/var/backups/misterchip", "s3:http://storage.example.org/bucket",
            "s3:https://127.0.0.1/bucket", "s3:https://93.188.187.188/bucket",
            "s3:https://user:secret@storage.example.org/bucket",
            "s3:https://storage.example.invalid/bucket",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(backup.OperationError):
                backup.validate_remote_repository(endpoint)
        backup.validate_remote_repository("s3:https://storage.example.org/private-bucket/misterchip")

    def test_partial_backup_is_failure_and_child_secrets_are_not_exposed(self):
        child = subprocess.CompletedProcess(["restic"], 3, b"secret stdout", b"secret endpoint password")
        with patch("ops.backup.subprocess.run", return_value=child):
            with self.assertRaises(backup.OperationError) as raised:
                backup.run_checked(["restic", "backup"], "offhost_backup")
        self.assertEqual(raised.exception.code, "offhost_backup_failed")
        self.assertEqual(raised.exception.exit_code, 3)
        self.assertNotIn("secret", str(raised.exception))

    def test_dump_failure_does_not_upload_or_mark_success(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(state_dir=Path(directory), compose=["docker", "compose"], environment=lambda **kwargs: {})
            with patch("ops.backup.run_checked", side_effect=backup.OperationError("postgres_dump_failed")) as run:
                with self.assertRaises(backup.OperationError):
                    backup.create_backup(config)
            self.assertEqual(run.call_count, 1)
            self.assertFalse((Path(directory) / "last-backup.json").exists())

    def test_completed_backup_bundle_roundtrips_and_excludes_configuration(self):
        payload = b"PGDMP complete database archive"
        snapshot = "c" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = SimpleNamespace(state_dir=root, compose=["docker", "compose"],
                                     environment=lambda **kwargs: {"AWS_SECRET_ACCESS_KEY": "private-storage-secret"})

            def run(command, step, **kwargs):
                if step == "postgres_dump":
                    kwargs["stdout"].write(payload)
                elif step == "archive_list":
                    self.assertEqual(kwargs["stdin"].read(), payload)
                elif step == "source_revision":
                    return ("d" * 40).encode()
                elif step == "offhost_backup":
                    bundle = root / "roundtrip.tar"
                    bundle.write_bytes(kwargs["stdin"].read())
                    restored = root / "roundtrip"
                    restored.mkdir()
                    dump, manifest = backup.extract_bundle(bundle, restored)
                    self.assertEqual(dump.read_bytes(), payload)
                    self.assertEqual(manifest["source_revision"], "d" * 40)
                    self.assertNotIn("private-storage-secret", json.dumps(manifest))
                    return json.dumps({"message_type": "summary", "snapshot_id": snapshot}).encode()
                return b""

            with patch("ops.backup.run_checked", side_effect=run):
                report = backup.create_backup(config)
            self.assertEqual(report["snapshot_id"], snapshot)
            self.assertFalse(report["restore_verified"])
            self.assertEqual(backup.safe_state(root, "last-backup.json")["snapshot_id"], snapshot)

    def test_archive_path_traversal_is_rejected_without_extracting(self):
        with tempfile.TemporaryDirectory() as directory:
            working = Path(directory)
            bundle = working / "archive.tar"
            with tarfile.open(bundle, "w") as archive:
                entry = tarfile.TarInfo("../escaped-secret")
                entry.size = 1
                archive.addfile(entry, io.BytesIO(b"x"))
            with self.assertRaises(backup.OperationError):
                backup.extract_bundle(bundle, working)
            self.assertEqual(set(path.name for path in working.iterdir()), {"archive.tar"})

    def test_archive_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            working = Path(directory)
            bundle = working / "archive.tar"
            manifest = json.dumps({"schema_version": 1, "postgres_major": 16,
                                   "archive_bytes": 4, "archive_sha256": "0" * 64}).encode()
            with tarfile.open(bundle, "w") as archive:
                for name, content in (("postgres.dump", b"data"), ("manifest.json", manifest)):
                    entry = tarfile.TarInfo(name)
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
            with self.assertRaises(backup.OperationError) as raised:
                backup.extract_bundle(bundle, working)
            self.assertEqual(raised.exception.code, "backup_checksum_mismatch")

    def test_failed_restore_cleans_only_its_own_isolated_container(self):
        container_id = "a" * 64
        commands = []

        def run(command, step, **kwargs):
            commands.append(command)
            if step == "isolated_postgres_start":
                return container_id.encode()
            if step == "isolated_postgres_restore":
                raise backup.OperationError("isolated_postgres_restore_failed")
            if step == "isolated_container_identity":
                return b"restore-check\n"
            return b""

        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"test")
            with patch("ops.backup.run_checked", side_effect=run):
                with self.assertRaises(backup.OperationError):
                    backup.isolated_restore(dump, {})
        start = commands[0]
        self.assertEqual(start[start.index("--network") + 1], "none")
        self.assertNotIn("-p", start)
        self.assertNotIn("--publish", start)
        restore = next(command for command in commands if "pg_restore" in command)
        self.assertIn(container_id, restore)
        self.assertEqual(restore[restore.index("-d") + 1], backup.RESTORE_DB)
        self.assertEqual(commands[-1], ["docker", "rm", "--force", container_id])

    def test_identity_mismatch_never_removes_a_container(self):
        container_id = "b" * 64

        def run(command, step, **kwargs):
            if step == "isolated_postgres_start":
                return container_id.encode()
            if step == "restored_schema_check":
                return b"10"
            if step == "isolated_container_identity":
                return b"production"
            return b""

        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "postgres.dump"
            dump.write_bytes(b"test")
            with patch("ops.backup.run_checked", side_effect=run) as mocked:
                with self.assertRaises(backup.OperationError):
                    backup.isolated_restore(dump, {})
        self.assertFalse(any(call.args[0][:2] == ["docker", "rm"] for call in mocked.call_args_list))

    def test_status_only_emits_allowlisted_nonsecret_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "last-backup.json").write_text(json.dumps({
                "snapshot_id": "a" * 64, "completed_at": datetime.now(timezone.utc).isoformat(),
                "source_revision": "b" * 40, "secret": "do-not-print",
                "repository": "https://user:password@host.example.org",
            }))
            report = backup.safe_state(state, "last-backup.json")
            self.assertNotIn("do-not-print", json.dumps(report))
            self.assertNotIn("password", json.dumps(report))
            self.assertEqual(report["source_revision"], "b" * 40)


if __name__ == "__main__":
    unittest.main()
