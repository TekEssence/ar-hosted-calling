#!/usr/bin/env bash
set -euo pipefail
# Run as root, before either container runtime. Never mount an unknown disk.
mountpoint -q /mnt || { echo '/mnt is not mounted' >&2; exit 1; }
SOURCE=$(findmnt -n -o SOURCE -M /mnt)
EXPECTED=$(readlink -f /dev/disk/cloud/azure_resource-part1)
[[ "$(readlink -f "$SOURCE")" = "$EXPECTED" ]] || { echo 'Unexpected /mnt device' >&2; exit 1; }
[[ "$(findmnt -n -o SOURCE -T /var/lib)" != "$SOURCE" ]] || exit 1
mkdir -p /mnt/docker-hybrid /mnt/containerd-hybrid /mnt/ar-voice-cache/models /mnt/ar-voice-cache/piper
mkdir -p /var/lib/ar-voice-agent/{redis,voices,caddy}
chmod 755 /var/lib/ar-voice-agent /var/lib/ar-voice-agent/voices
chmod 700 /var/lib/ar-voice-agent/redis /var/lib/ar-voice-agent/caddy
