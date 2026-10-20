#!/bin/bash
# Small synchronous snapshot; not a substitute for an off-VM backup.
set -euo pipefail
umask 077
BK="${BACKUP_DIR:-$HOME/ar-voice-agent-backups}"
mkdir -p "$BK"
SOURCE=$(findmnt -n -o SOURCE -T "$BK")
TEMP=$(readlink -f /dev/disk/cloud/azure_resource-part1 2>/dev/null || true)
if [[ "$BK" = /mnt/* || ( -n "$TEMP" && "$(readlink -f "$SOURCE")" = "$TEMP" ) ]]; then
  echo "Refusing backup to Azure temporary storage." >&2
  exit 1
fi
# SAVE completes before copying, unlike BGSAVE followed by a guessed sleep.
[[ "$(docker exec redis redis-cli SAVE)" = OK ]] || { echo "Redis SAVE failed" >&2; exit 1; }
TS=$(date -u +%Y%m%d-%H%M%S)
FILE="$BK/redis-$TS.rdb"
[[ ! -e "$FILE" && ! -e "$FILE.partial" ]] || { echo "Snapshot already exists" >&2; exit 1; }
docker cp redis:/data/dump.rdb "$FILE.partial"
[[ -s "$FILE.partial" ]] || { echo "Empty snapshot; backup failed" >&2; exit 1; }
chmod 600 "$FILE.partial"
mv "$FILE.partial" "$FILE"
# Only prune completed snapshots created by this script, never directories.
mapfile -t OLD < <(find "$BK" -maxdepth 1 -type f -name 'redis-????????-??????.rdb' | sort | head -n -7)
for file in "${OLD[@]}"; do rm -- "$file"; done
echo "Redis snapshot saved: $FILE"
