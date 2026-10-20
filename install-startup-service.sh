#!/usr/bin/env bash
# Explicit opt-in installer. Never migrates data or removes cron automatically.
set -euo pipefail
cd "$(dirname "$0")"
EXPECTED=/opt/ar-voice-agent/deploy
[[ "$(pwd -P)" = "$EXPECTED" ]] || { echo "Install from $EXPECTED" >&2; exit 1; }
ROOT=$(docker info --format '{{.DockerRootDir}}')
SOURCE=$(findmnt -n -o SOURCE -T "$ROOT")
TEMP=$(readlink -f /dev/disk/cloud/azure_resource-part1 2>/dev/null || true)
if [[ -f .hybrid.env ]]; then
  [[ "$ROOT" = /mnt/docker-hybrid ]] || { echo 'Unexpected hybrid Docker root' >&2; exit 1; }
  mountpoint -q /mnt || exit 1
  for folder in redis voices caddy; do
    [[ -d "/var/lib/ar-voice-agent/$folder" ]] || exit 1
  done
elif [[ "$ROOT" = /mnt/* || ( -n "$TEMP" && "$(readlink -f "$SOURCE")" = "$TEMP" ) ]]; then
  echo "Refusing installation: Docker is on Azure temporary storage ($ROOT)." >&2
  exit 1
fi
if crontab -l 2>/dev/null | grep -qE '^@reboot.*(docker compose|start.sh)'; then
  echo "Back up and replace the existing app reboot cron first; no cron was changed." >&2
  exit 1
fi
if [[ -e /etc/cron.d/ar-voice-agent-cron ]]; then
  echo "Review and back up /etc/cron.d/ar-voice-agent-cron first; it was not changed." >&2
  exit 1
fi
# Prepared containers must already pass the updated readiness endpoint.
bash ./verify_services.sh
sudo install -m 644 voice-agent.service /etc/systemd/system/voice-agent.service
sudo install -m 644 voice-agent-recovery.timer /etc/systemd/system/voice-agent-recovery.timer
sudo systemctl daemon-reload
sudo systemctl disable voice-agent.service
sudo systemctl enable --now voice-agent-recovery.timer
