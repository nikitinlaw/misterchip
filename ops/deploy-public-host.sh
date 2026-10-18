#!/usr/bin/env bash
# Fixed, root-owned PUBLIC deployment procedure; called only through restricted SSH key.
# Public HTTPS is terminated by Caddy. No database, Redis or app ports are made public.
set -Eeuo pipefail
umask 077
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid commit ID." >&2; exit 2; }
expected="$1"
install -d -o root -g root -m 0700 /run/misterchip-ops
exec 9>/run/misterchip-ops/operation.lock
flock -w 120 9 || { echo "Another deployment or backup operation is running." >&2; exit 2; }
owner=misterchip-admin
repository="/home/$owner/misterchip"
env_file="$repository/.env"
compose_file=compose.staging.yaml
[[ -f "$env_file" ]] || { echo "Missing private environment file." >&2; exit 2; }
for config in \
  'DJANGO_DEBUG=0' \
  'DJANGO_STAGING_SSH_TUNNEL=0' \
  'DJANGO_TRUST_PROXY_SSL=1' \
  'DJANGO_TRUST_PROXY_CLIENT_IP=1'; do
  grep -Fxq "$config" "$env_file" || {
    echo "Public configuration is not ready; follow docs/STAGING_DEPLOY.md." >&2
    exit 2
  }
done
# The domain is authorized explicitly by the one-time publication script.
public_domain="$(sed -n 's/^MISTERCHIP_PUBLIC_DOMAIN=//p' "$env_file" | tail -1)"
[[ "$public_domain" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || {
  echo "Missing or invalid Misterchip public domain." >&2; exit 2;
}
grep -Fxq "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,$public_domain,www.$public_domain" "$env_file" || {
  echo "Misterchip allowed-hosts configuration mismatch." >&2; exit 2;
}
grep -Fxq "DJANGO_CSRF_TRUSTED_ORIGINS=https://$public_domain,https://www.$public_domain" "$env_file" || {
  echo "Misterchip CSRF origins not configured." >&2; exit 2;
}
grep -Fxq 'DJANGO_SECURE_SSL_REDIRECT=0' "$env_file" || {
  echo "Misterchip HTTPS termination must be delegated to Caddy." >&2; exit 2;
}
grep -Eq '^DJANGO_SECRET_KEY=.{32,}$' "$env_file" || { echo "DJANGO_SECRET_KEY is not configured." >&2; exit 2; }
grep -Eq '^DB_PASSWORD=.{24,}$' "$env_file" || { echo "DB_PASSWORD is not configured." >&2; exit 2; }
if grep -Eq '(local-development-only|replace-this-with-a-random-secret)' "$env_file"; then
  echo "Example credentials are forbidden." >&2
  exit 2
fi

cd "$repository"
[[ "$(runuser -u "$owner" -- git -C "$repository" branch --show-current)" == main ]] || { echo "Expected main branch." >&2; exit 2; }
if [[ -n "$(runuser -u "$owner" -- git -C "$repository" status --porcelain --untracked-files=no)" ]]; then
  echo "Local tracked changes exist; refusing to overwrite." >&2
  exit 2
fi
runuser -u "$owner" -- env \
  GIT_SSH_COMMAND="ssh -i /home/$owner/.ssh/misterchip_github -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  git -C "$repository" fetch --no-tags origin main
actual="$(runuser -u "$owner" -- git -C "$repository" rev-parse refs/remotes/origin/main)"
[[ "$actual" == "$expected" ]] || {
  echo "Deploy request is stale or does not match origin/main." >&2
  exit 2
}
runuser -u "$owner" -- git -C "$repository" reset --hard "$expected"

# The configuration binds the ONLY HTTP port to host loopback. Database and
# Redis have no published ports. Changes to the Compose file need review.
grep -Fq '"127.0.0.1:8000:8000"' "$compose_file" || {
  echo "Missing required localhost-only port binding." >&2; exit 2;
}
docker compose -f "$compose_file" config -q
docker compose -f "$compose_file" up -d --wait db redis

# Backup is local and temporary. Off-server backups are still required before
# opening the service for real users.
backup_dir=/var/backups/misterchip
install -d -m 700 "$backup_dir"
backup="$backup_dir/postgres-$(date -u +%Y%m%dT%H%M%SZ)-$expected.dump"
docker compose -f "$compose_file" exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup"
[[ -s "$backup" ]] || { echo "Backup failed; deployment aborted." >&2; exit 1; }

docker compose -f "$compose_file" build --build-arg "MISTERCHIP_REVISION=$expected" web
# Validate Django's actual environment parsing without sending a message.
# File mail is still accepted for the existing pilot, but is reported not ready.
docker compose -f "$compose_file" run --rm --no-deps web \
  python manage.py runtime_status --expect-revision "$expected" --check-mail
docker compose -f "$compose_file" run --rm --no-deps web python manage.py migrate --noinput
docker compose -f "$compose_file" run --rm --no-deps web python manage.py seed_demo_catalog
docker compose -f "$compose_file" up -d --wait web
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:8000/healthz/ | grep -qx ok
docker compose -f "$compose_file" exec -T web \
  python manage.py runtime_status --expect-revision "$expected" --check-mail
echo "MISTERCHIP public HTTPS backend deployed: $expected"
echo "The web backend remains loopback-only; Caddy terminates public HTTPS."
