#!/usr/bin/env bash
# Install root-owned; process pending transactional notifications with real SMTP.
set -Eeuo pipefail
umask 077
[[ "$(id -u)" == 0 ]] || { echo '{"status":"error","code":"run_as_root"}'; exit 1; }
install -d -o root -g root -m 0700 /run/misterchip-notifications
exec 9>/run/misterchip-notifications/worker.lock
flock -n 9 || { echo '{"status":"already_running"}'; exit 0; }
cd /home/misterchip-admin/misterchip
if ! docker compose -f compose.staging.yaml exec -T web \
    python manage.py runtime_status --require-smtp >/dev/null 2>&1; then
  echo '{"status":"not_ready","code":"smtp_configuration_check_failed"}'
  exit 1
fi
if ! docker compose -f compose.staging.yaml exec -T web \
    python manage.py send_market_notifications --limit 50 >/dev/null 2>&1; then
  echo '{"status":"error","code":"notification_queue_failed"}'
  exit 1
fi
echo '{"status":"notification_queue_processed"}'
