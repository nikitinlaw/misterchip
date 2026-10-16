#!/usr/bin/env bash
# GitHub Actions SSH key may execute ONLY an approved deployment command.
set -euo pipefail
requested="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$requested" =~ ^deploy:([0-9a-f]{40})$ ]]; then
  echo "This SSH key is restricted to deploying a main-branch commit." >&2
  exit 1
fi
exec sudo -n /usr/local/sbin/misterchip-deploy "${BASH_REMATCH[1]}"
