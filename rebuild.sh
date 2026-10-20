#!/bin/bash
# Rebuild the app images after code changes, then start the stack.
# (Daily restarts just use start.sh — this only runs when you change code.)
#
# IMPORTANT: always use --build (this script does) for code changes.
# `docker compose restart` reuses the EXISTING image and will silently keep
# serving old code even after files on disk have changed — prompts.py,
# server/, etc. are COPY'd into the image at build time, not bind-mounted.
# The /project bind mount below is for other tooling only; the running app
# imports from /app, which only updates on a rebuild.
#
# GIT_COMMIT/BUILD_TIME should be exported by the caller (see sync.sh, which
# captures them from the LOCAL git repo before rsyncing here — this VM's
# checkout is not itself a git repo). If run standalone with neither set,
# the build is stamped "unknown" rather than silently claiming a commit it
# can't verify. Check GET /api/config (or Settings page) after any deploy to
# confirm the running build's commit/time match what you expect.
set -euo pipefail
cd "${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ar-voice-agent}"
if [[ -f .hybrid.env ]]; then
  set -a
  source ./.hybrid.env
  [[ ! -f .hybrid-images.env ]] || source ./.hybrid-images.env
  set +a
  export COMPOSE_FILE=docker-compose.yml:docker-compose.hybrid.yml
fi

GIT_COMMIT="${GIT_COMMIT:-unknown}" BUILD_TIME="${BUILD_TIME:-unknown}" \
  docker compose --profile prod --profile tls up -d --build
echo "Built commit=${GIT_COMMIT:-unknown} at=${BUILD_TIME:-unknown}"
bash ./verify_services.sh
