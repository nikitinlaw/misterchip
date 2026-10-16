#!/usr/bin/env bash
# Run ONCE as misterchip-admin, from ~/misterchip.
# Never paste private keys or .env contents into chat.
set -Eeuo pipefail
[[ "$(id -un)" == misterchip-admin ]] || {
  echo "Run as misterchip-admin, not root." >&2; exit 2;
}
repo="/home/misterchip-admin/misterchip"
cd "$repo"
[[ -f .env ]] || { echo "Missing .env; create it from .env.example first." >&2; exit 2; }
[[ -f "$HOME/.ssh/misterchip_github" ]] || {
  echo "Existing GitHub read-only clone key not found." >&2; exit 2;
}
umask 077
chmod 600 .env
# Safely parse KEY=VALUE lines without sourcing/executing shell contents.
# Preserve existing non-placeholder DB and Django secrets across restarts.
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path(".env")
lines = path.read_text().splitlines()
values = {}
for raw in lines:
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        values[key] = value
key = values.get("DJANGO_SECRET_KEY", "")
password = values.get("DB_PASSWORD", "")
if not key or key.startswith("replace-this-") or len(key) < 32:
    values["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(48)
if not password or password == "local-development-only" or len(password) < 24:
    values["DB_PASSWORD"] = secrets.token_urlsafe(36)
values.update({
    "DJANGO_DEBUG": "0",
    "DJANGO_STAGING_SSH_TUNNEL": "1",
    "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
    "DJANGO_SECURE_SSL_REDIRECT": "0",
    "DJANGO_EMAIL_BACKEND": "django.core.mail.backends.filebased.EmailBackend",
    "EMAIL_FILE_PATH": "/app/private_mail",
    "DEFAULT_FROM_EMAIL": "MISTERCHIP <noreply@example.invalid>",
})
existing = set()
updated = []
for raw in lines:
    if not raw.lstrip().startswith("#") and "=" in raw:
        name, _ = raw.split("=", 1)
        if name in values:
            if name not in existing:
                updated.append(f"{name}={values[name]}")
            existing.add(name)
            continue
    updated.append(raw)
for name, value in values.items():
    if name not in existing:
        updated.append(f"{name}={value}")
path.write_text("\n".join(updated) + "\n")
path.chmod(0o600)
print("Private staging environment prepared; secret values were not displayed.")
PY

sudo install -o root -g root -m 0755 \
  ops/deploy-host.sh /usr/local/sbin/misterchip-deploy
sudo install -o root -g root -m 0755 \
  ops/deploy-gateway.sh /usr/local/bin/misterchip-deploy-gateway
sudo tee /etc/sudoers.d/misterchip-deploy > /dev/null <<'SUDOERS'
misterchip-admin ALL=(root) NOPASSWD: /usr/local/sbin/misterchip-deploy *
SUDOERS
sudo chmod 440 /etc/sudoers.d/misterchip-deploy
sudo visudo -cf /etc/sudoers.d/misterchip-deploy >/dev/null

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
key="$HOME/.ssh/misterchip_actions_deploy"
if [[ ! -f "$key" ]]; then
  ssh-keygen -q -t ed25519 -N '' -f "$key" -C "misterchip-actions-staging"
  chmod 600 "$key"
fi
pub="$(cat "$key.pub")"
entry="restrict,command=\"/usr/local/bin/misterchip-deploy-gateway\" $pub"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! grep -Fqx "$entry" "$HOME/.ssh/authorized_keys"; then
  printf '%s\n' "$entry" >> "$HOME/.ssh/authorized_keys"
fi
echo "Bootstrap complete."
echo "NEXT: Put the complete text of $key into GitHub Actions secret MISTERCHIP_DEPLOY_SSH_KEY."
echo "Do not send it to anyone or paste it into chat."
echo "After saving the secret, securely delete the temporary private key on VPS:"
echo "  shred -u ~/.ssh/misterchip_actions_deploy"
