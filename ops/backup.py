#!/usr/bin/env python3
"""Encrypted off-host PostgreSQL backups and isolated restore drills.

Run the installed, root-owned copy. Commands never restore into the live
database, send email, or print credentials, repository URLs, SQL or child logs.
Only Python's standard library, Docker Compose and restic are required.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlsplit
import uuid


DEFAULT_CONFIG = Path("/etc/misterchip/backup.env")
DEFAULT_STATE = Path("/var/lib/misterchip-ops")
RUNTIME_LOCK_DIR = Path("/run/misterchip-ops")
SNAPSHOT_PATTERN = re.compile(r"[0-9a-f]{64}")
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
ARCHIVE_PATH = "/misterchip/database.tar"
RESTORE_LABEL = "com.misterchip.purpose"
RESTORE_DB = "misterchip_restore_check"
ALLOWED_CONFIG = {
    "PROJECT_DIR", "STATE_DIR", "RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION",
    "AWS_SESSION_TOKEN",
}


class OperationError(Exception):
    def __init__(self, code, exit_code=None):
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require_private_file(path):
    try:
        metadata = path.lstat()
    except OSError:
        raise OperationError("private_configuration_missing") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise OperationError("private_configuration_permissions")


def parse_config(text):
    """Parse literal KEY=VALUE lines; never source a shell file or interpolate it."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in ALLOWED_CONFIG or key in values:
            raise OperationError("invalid_backup_configuration")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise OperationError("invalid_backup_configuration")
            value = value[1:-1]
        if "\x00" in value:
            raise OperationError("invalid_backup_configuration")
        values[key] = value
    return values


def validate_remote_repository(value):
    # Restrict the first implementation to encrypted HTTPS S3-compatible storage.
    # Credentials belong in separate variables, never inside the endpoint URL.
    if not value.startswith("s3:https://"):
        raise OperationError("offhost_https_s3_repository_required")
    try:
        parsed = urlsplit(value[3:])
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        raise OperationError("invalid_repository_endpoint") from None
    if (
        not host or not parsed.path.strip("/") or parsed.username or parsed.password
        or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)
        or host in {"localhost", "93.188.187.188"}
        or host.endswith((".localhost", ".invalid", ".test", ".example"))
    ):
        raise OperationError("invalid_repository_endpoint")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if address.is_loopback or address.is_unspecified or address.is_link_local:
        raise OperationError("offhost_repository_required")


class Configuration:
    def __init__(self, path):
        require_private_file(path)
        if path.stat().st_size > 65536:
            raise OperationError("invalid_backup_configuration")
        self.values = parse_config(path.read_text(encoding="utf-8"))
        validate_remote_repository(self.values.get("RESTIC_REPOSITORY", ""))
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "RESTIC_PASSWORD_FILE"):
            if not self.values.get(key):
                raise OperationError("backup_credentials_incomplete")
        password_file = Path(self.values["RESTIC_PASSWORD_FILE"])
        if not password_file.is_absolute():
            raise OperationError("password_file_must_be_absolute")
        require_private_file(password_file)
        if password_file.stat().st_size == 0:
            raise OperationError("repository_password_missing")
        self.project_dir = Path(self.values.get("PROJECT_DIR", "/home/misterchip-admin/misterchip"))
        self.state_dir = Path(self.values.get("STATE_DIR", str(DEFAULT_STATE)))
        if not self.project_dir.is_absolute() or not self.state_dir.is_absolute():
            raise OperationError("configuration_paths_must_be_absolute")
        if not (self.project_dir / "compose.staging.yaml").is_file():
            raise OperationError("compose_configuration_missing")
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self.state_dir.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise OperationError("state_directory_permissions")

    def environment(self, *, restic=False):
        # Avoid inherited values silently overriding the intended private files.
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("RESTIC_", "AWS_", "DJANGO_", "DB_", "EMAIL_"))
            and key not in {"DEFAULT_FROM_EMAIL", "PUBLIC_SITE_URL", "REDIS_URL"}
        }
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        if restic:
            env.update({key: value for key, value in self.values.items() if key.startswith(("RESTIC_", "AWS_"))})
            env["RESTIC_CACHE_DIR"] = str(self.state_dir / "restic-cache")
        return env

    @property
    def compose(self):
        return [
            "docker", "compose", "--project-directory", str(self.project_dir),
            "--env-file", str(self.project_dir / ".env"),
            "-f", str(self.project_dir / "compose.staging.yaml"),
        ]


def run_checked(command, step, *, env=None, stdin=None, stdout=None, timeout=1800):
    try:
        result = subprocess.run(
            command, stdin=stdin, stdout=subprocess.PIPE if stdout is None else stdout,
            stderr=subprocess.PIPE, env=env, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        raise OperationError(step + "_timeout") from None
    except OSError:
        raise OperationError(step + "_unavailable") from None
    if result.returncode:
        # Child messages can contain endpoint URLs, SQL or credentials. Do not echo.
        raise OperationError(step + "_failed", result.returncode)
    return result.stdout or b""


@contextmanager
def operation_lock():
    # The root-owned deploy helpers use this same lock, so a scheduled dump
    # cannot capture a database while a helper is applying migrations.
    RUNTIME_LOCK_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = RUNTIME_LOCK_DIR.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise OperationError("operation_lock_permissions")
    with (RUNTIME_LOCK_DIR / "operation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OperationError("operation_already_running") from None
        yield


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_state(state_dir, filename, value):
    target = state_dir / filename
    temporary = state_dir / (filename + "." + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def safe_state(state_dir, filename):
    path = state_dir / filename
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        snapshot = data["snapshot_id"]
        if not SNAPSHOT_PATTERN.fullmatch(snapshot):
            raise ValueError
        completed = datetime.fromisoformat(data["completed_at"])
        if completed.tzinfo is None:
            raise ValueError
        result = {
            "snapshot_id": snapshot,
            "completed_at": completed.isoformat(timespec="seconds"),
            "age_seconds": max(0, int((datetime.now(timezone.utc) - completed).total_seconds())),
        }
        revision = data.get("source_revision", "unknown")
        result["source_revision"] = revision if REVISION_PATTERN.fullmatch(revision) else "unknown"
        return result
    except (ValueError, TypeError, KeyError, OSError):
        raise OperationError("invalid_local_status_marker") from None


def snapshot_from_json(output):
    try:
        summaries = [item for line in output.splitlines() if line
                     for item in [json.loads(line)] if item.get("message_type") == "summary"]
        snapshot = summaries[-1]["snapshot_id"]
        if not SNAPSHOT_PATTERN.fullmatch(snapshot):
            raise ValueError
        return snapshot
    except (ValueError, TypeError, KeyError, IndexError):
        raise OperationError("backup_snapshot_unconfirmed") from None


def create_backup(config):
    with tempfile.TemporaryDirectory(prefix="backup-", dir=config.state_dir) as temporary:
        working = Path(temporary)
        dump = working / "postgres.dump"
        env = config.environment()
        with dump.open("wb") as output:
            run_checked(
                config.compose + ["exec", "-T", "db", "sh", "-c",
                                  'pg_dump --format=custom -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
                "postgres_dump", env=env, stdout=output,
            )
        if not dump.stat().st_size:
            raise OperationError("postgres_dump_empty")
        with dump.open("rb") as source:
            run_checked(config.compose + ["exec", "-T", "db", "pg_restore", "--list"],
                        "archive_list", env=env, stdin=source)
        revision_output = run_checked(
            config.compose + ["exec", "-T", "web", "python", "-c",
                              "from pathlib import Path; p=Path('/app/RELEASE'); print(p.read_text().strip() if p.is_file() else 'unknown')"],
            "source_revision", env=env, timeout=30,
        ).decode("ascii", errors="replace").strip()
        revision = revision_output if REVISION_PATTERN.fullmatch(revision_output) else "unknown"
        manifest = {
            "schema_version": 1, "created_at": utc_now(), "postgres_major": 16,
            "source_revision": revision, "archive_sha256": sha256_file(dump),
            "archive_bytes": dump.stat().st_size,
        }
        (working / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        bundle = working / "database.tar"
        with tarfile.open(bundle, mode="w") as archive:
            for name in ("postgres.dump", "manifest.json"):
                archive.add(working / name, arcname=name, recursive=False)
        # The dump is complete and checked before restic sees its input.
        # A pg_dump failure can therefore never become a successful empty snapshot.
        with bundle.open("rb") as source:
            output = run_checked(
                ["restic", "backup", "--stdin", "--stdin-filename", ARCHIVE_PATH,
                 "--json", "--tag", "misterchip-db", "--host", "misterchip-beget"],
                "offhost_backup", env=config.environment(restic=True), stdin=source,
            )
        snapshot = snapshot_from_json(output)
        marker = {
            "snapshot_id": snapshot, "completed_at": utc_now(),
            "source_revision": revision,
        }
        write_state(config.state_dir, "last-backup.json", marker)
        return {"status": "backup_uploaded", **marker, "restore_verified": False}


def extract_bundle(bundle, working):
    """Extract only two fixed regular files; never trust paths from an archive."""
    try:
        with tarfile.open(bundle, mode="r:") as archive:
            members = archive.getmembers()
            if (
                len(members) != 2 or {item.name for item in members} != {"postgres.dump", "manifest.json"}
                or any(not item.isfile() for item in members)
            ):
                raise OperationError("invalid_backup_bundle")
            for item in members:
                if item.name == "manifest.json" and item.size > 65536:
                    raise OperationError("invalid_backup_manifest")
                with archive.extractfile(item) as source, (working / item.name).open("wb") as output:
                    shutil.copyfileobj(source, output)
        manifest = json.loads((working / "manifest.json").read_text(encoding="utf-8"))
        dump = working / "postgres.dump"
        if (
            manifest.get("schema_version") != 1 or manifest.get("postgres_major") != 16
            or manifest.get("archive_bytes") != dump.stat().st_size
            or manifest.get("archive_sha256") != sha256_file(dump)
        ):
            raise OperationError("backup_checksum_mismatch")
        return dump, manifest
    except (tarfile.TarError, ValueError, TypeError, OSError):
        raise OperationError("invalid_backup_bundle") from None


def isolated_restore(dump, env):
    """No live container, Compose service, port or database is accepted as input."""
    name = "misterchip-restore-check-" + uuid.uuid4().hex
    container_id = run_checked(
        ["docker", "run", "--detach", "--rm", "--pull=never", "--network", "none",
         "--name", name, "--label", RESTORE_LABEL + "=restore-check", "--memory", "768m",
         "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "POSTGRES_USER=restorecheck",
         "--env", "POSTGRES_DB=" + RESTORE_DB, "postgres:16"],
        "isolated_postgres_start", env=env, timeout=60,
    ).decode("ascii", errors="replace").strip()
    if not SNAPSHOT_PATTERN.fullmatch(container_id):
        raise OperationError("invalid_isolated_container_id")
    try:
        for attempt in range(60):
            try:
                run_checked(["docker", "exec", container_id, "pg_isready", "-U", "restorecheck", "-d", RESTORE_DB],
                            "isolated_postgres_readiness", env=env, timeout=5)
                break
            except OperationError:
                if attempt == 59:
                    raise
                time.sleep(1)
        with dump.open("rb") as source:
            run_checked(
                ["docker", "exec", "-i", container_id, "pg_restore", "--exit-on-error",
                 "--no-owner", "--no-privileges", "-U", "restorecheck", "-d", RESTORE_DB],
                "isolated_postgres_restore", env=env, stdin=source,
            )
        count = run_checked(
            ["docker", "exec", container_id, "psql", "-v", "ON_ERROR_STOP=1",
             "-U", "restorecheck", "-d", RESTORE_DB, "-Atc", "SELECT count(*) FROM django_migrations"],
            "restored_schema_check", env=env, timeout=30,
        ).strip()
        if not count.isdigit() or int(count) == 0:
            raise OperationError("restored_schema_incomplete")
    finally:
        # Delete only the exact container created above, and only with our label.
        label = run_checked(
            ["docker", "inspect", "--format", '{{ index .Config.Labels "' + RESTORE_LABEL + '" }}', container_id],
            "isolated_container_identity", env=env, timeout=30,
        ).strip()
        if label != b"restore-check":
            raise OperationError("isolated_container_identity_mismatch")
        run_checked(["docker", "rm", "--force", container_id], "isolated_container_cleanup", env=env, timeout=60)


def verify_restore(config, snapshot=None):
    if snapshot is None:
        marker = safe_state(config.state_dir, "last-backup.json")
        if not marker:
            raise OperationError("no_successful_backup_marker")
        snapshot = marker["snapshot_id"]
    if not SNAPSHOT_PATTERN.fullmatch(snapshot):
        raise OperationError("exact_snapshot_id_required")
    with tempfile.TemporaryDirectory(prefix="restore-", dir=config.state_dir) as temporary:
        working = Path(temporary)
        bundle = working / "database.tar"
        with bundle.open("wb") as output:
            run_checked(["restic", "dump", snapshot, ARCHIVE_PATH], "offhost_download",
                        env=config.environment(restic=True), stdout=output)
        dump, manifest = extract_bundle(bundle, working)
        isolated_restore(dump, config.environment())
        revision = manifest.get("source_revision", "unknown")
        marker = {
            "snapshot_id": snapshot, "completed_at": utc_now(),
            "source_revision": revision if REVISION_PATTERN.fullmatch(revision) else "unknown",
        }
        write_state(config.state_dir, "last-restore.json", marker)
        return {"status": "isolated_restore_verified", **marker, "live_database_modified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("backup", "init", "status"):
        subparsers.add_parser(action)
    restore = subparsers.add_parser("restore-check")
    restore.add_argument("--snapshot", help="Exact 64-character snapshot ID; defaults to last successful upload.")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if os.geteuid() != 0:
            raise OperationError("run_installed_copy_as_root")
        # Status is local/read-only and works before credentials are installed.
        if args.action == "status":
            state_dir = DEFAULT_STATE
            if args.config.exists():
                require_private_file(args.config)
                values = parse_config(args.config.read_text(encoding="utf-8"))
                state_dir = Path(values.get("STATE_DIR", str(DEFAULT_STATE)))
            result = {
                "status": "local_status", "external_config_present": args.config.exists(),
                "backup": safe_state(state_dir, "last-backup.json"),
                "restore": safe_state(state_dir, "last-restore.json"),
            }
        else:
            config = Configuration(args.config)
            with operation_lock():
                if args.action == "init":
                    run_checked(["restic", "init"], "repository_init", env=config.environment(restic=True))
                    result = {"status": "repository_initialized"}
                elif args.action == "backup":
                    result = create_backup(config)
                else:
                    result = verify_restore(config, args.snapshot)
        print(json.dumps(result, sort_keys=True))
        return 0
    except OperationError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "exit_code": exc.exit_code}, sort_keys=True))
        return 1
    except Exception:
        # Never expose raw configuration/endpoint values through a traceback.
        print(json.dumps({"status": "error", "code": "unexpected_operational_error"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
