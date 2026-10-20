#!/bin/bash
# Start the AR voice agent stack instantly (no rebuild — uses existing images).
# Use bootstrap-new-vm.sh on a fresh VM; run rebuild.sh after changing code.
set -euo pipefail
cd "${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ar-voice-agent}"
if [[ -f .hybrid.env ]]; then
  exec /bin/bash ./recover-hybrid.sh
fi

# prod+tls brings up voice-agent, vllm, redis, frontend and caddy. No --build:
# instant start from cached images.
docker info >/dev/null
# Boot must never silently download or rebuild the GPU stack.
docker compose --profile prod --profile tls up -d --no-build --pull never

# Opik runs as its own compose at /opt/opik (the built-in compose `opik`
# profile is not the real stack). Start it too if present.
if [ -d /opt/opik/deployment/docker-compose ]; then
  (
    cd /opt/opik/deployment/docker-compose
    FILES="-f docker-compose.yaml"
    [ -f docker-compose.override.yaml ] && FILES="$FILES -f docker-compose.override.yaml"
    [ -f docker-compose.override.yml ] && FILES="$FILES -f docker-compose.override.yml"
    sudo docker compose $FILES --profile opik up -d
  ) && sudo docker network connect ar-voice-agent_default opik-frontend-1 2>/dev/null || true
fi

bash ./verify_services.sh
echo "----------------------------------------"
echo "  API health : curl https://\$(grep ^PUBLIC_DOMAIN .env | cut -d= -f2)/health"
echo "  UI         : https://\$(grep ^PUBLIC_DOMAIN .env | cut -d= -f2)"
echo "  Opik       : https://optik.\$(grep ^PUBLIC_DOMAIN .env | cut -d= -f2)"
echo "  Twilio     : /voice webhook base = https://\$(grep ^PUBLIC_DOMAIN .env | cut -d= -f2)"
echo "----------------------------------------"
