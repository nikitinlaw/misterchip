#!/usr/bin/env bash
# Fixed, root-owned deployment procedure; called only through the restricted SSH key.
set -Eeuo pipefail
umask 077
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid commit ID." >&2; exit 2; }
expected="$1"
owner=misterchip-admin
repository="/home/$owner/misterchip"
env_file="$repository/.env"
compose_file=compose.staging.yaml
[[ -f "$env_file" ]] || { echo "Missing private environment file." >&2; exit 2; }
for config in \
  'DJANGO_DEBUG=0' \
  'DJANGO_STAGING_SSH_TUNNEL=1' \
  'DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1' \
  'DJANGO_EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend'; do
  grep -Fxq "$config" "$env_file" || {
    echo "Staging configuration is not ready; run the bootstrap procedure." >&2
    exit 2
  }
done
grep -Eq '^DJANGO_SECRET_KEY=.{32,}$' "$env_file" || { echo "DJANGO_SECRET_KEY is not configured." >&2; exit 2; }
grep -Eq '^DB_PASSWORD=.{24,}$' "$env_file" || { echo "DB_PASSWORD is not configured." >&2; exit 2; }
if grep -Eq '(local-development-only|replace-this-with-a-random-secret)' "$env_file"; then
  echo "Example credentials are forbidden." >&2
  exit 2
fi

cd "$repository"
[[ "$(git branch --show-current)" == main ]] || { echo "Expected main branch." >&2; exit 2; }
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Local tracked changes exist; refusing to overwrite." >&2
  exit 2
fi
runuser -u "$owner" -- env \
  GIT_SSH_COMMAND="ssh -i /home/$owner/.ssh/misterchip_github -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  git -C "$repository" fetch --no-tags origin main
actual="$(git rev-parse refs/remotes/origin/main)"
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

docker compose -f "$compose_file" build web
docker compose -f "$compose_file" run --rm --no-deps web python manage.py migrate --noinput
docker compose -f "$compose_file" run --rm --no-deps web python manage.py seed_demo_catalog
docker compose -f "$compose_file" up -d --wait web
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:8000/healthz/ | grep -qx ok
echo "MISTERCHIP private staging deployed: $expected"
echo "Access only by SSH tunnel; no public HTTP port is opened."
