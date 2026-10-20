#!/usr/bin/env bash
# Recreate disposable state after Azure deallocation; durable data is bind-mounted.
set -euo pipefail
cd "$(dirname "$0")"
set -a
source ./.hybrid.env
set +a
export COMPOSE_PROJECT_NAME=ar-voice-agent
export COMPOSE_FILE=docker-compose.yml:docker-compose.hybrid.yml
exec 9>"$HOME/.ar-voice-agent-recovery.lock"
flock -n 9 || { echo 'Another recovery is already running'; exit 1; }
mountpoint -q /mnt || { echo 'Temporary storage is unavailable'; exit 1; }
[[ "$(docker info --format '{{.DockerRootDir}}')" = /mnt/docker-hybrid ]] || exit 1
[[ "$(docker info --format '{{.Driver}}')" = overlay2 ]] || exit 1
for item in /var/lib/ar-voice-agent/redis /var/lib/ar-voice-agent/voices /var/lib/ar-voice-agent/caddy /mnt/ar-voice-cache/models /mnt/ar-voice-cache/piper; do
  [[ -d "$item" ]] || { echo "Missing prepared folder: $item" >&2; exit 1; }
done
OS_FREE=$(df -Pk /var/lib/ar-voice-agent | awk 'NR==2 {print $4}')
TEMP_FREE=$(df -Pk /mnt | awk 'NR==2 {print $4}')
(( OS_FREE >= 1048576 )) || { echo 'Less than 1 GiB permanent space; recovery paused' >&2; exit 1; }
(( TEMP_FREE >= 10485760 )) || { echo 'Less than 10 GiB temporary space; recovery paused' >&2; exit 1; }
echo "Recovery started at $(date -u --iso-8601=seconds); OS=${OS_FREE}KiB temp=${TEMP_FREE}KiB"
# Resolve registry image references once, then reuse immutable digests after disk loss.
python3 ./pin-hybrid-images.py
set -a
source ./.hybrid-images.env
set +a
docker compose --profile prod --profile tls config --quiet
for service in redis caddy vllm; do
  ref=$(docker compose --profile prod --profile tls config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service")
  docker image inspect "$ref" >/dev/null 2>&1 || docker compose --profile prod --profile tls pull "$service"
done
# Build sequentially to avoid multiple large GPU builds exhausting working space.
for service in frontend voice-agent chatterbox-tts; do
  docker image inspect "ar-voice-agent-$service" >/dev/null 2>&1 || docker compose --profile prod --profile tls build "$service"
done
# This download previously failed silently during image creation.
docker compose --profile prod --profile tls run --rm --no-deps -T voice-agent python -c '
import pathlib, urllib.request
base = pathlib.Path("/models/piper")
for suffix in (".onnx", ".onnx.json"):
    target = base / ("en_US-lessac-medium" + suffix)
    if not target.exists() or target.stat().st_size == 0:
        partial = target.with_name(target.name + ".partial")
        urllib.request.urlretrieve("https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/" + target.name, partial)
        partial.replace(target)
'
docker compose --profile prod --profile tls up -d --no-build --pull never
bash ./verify_services.sh
echo "Recovery completed at $(date -u --iso-8601=seconds)"
