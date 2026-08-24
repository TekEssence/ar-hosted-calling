#!/usr/bin/env bash
# The ONE correct way to push local code changes to the VM.
#
# Why this exists: `docker compose restart` reuses the existing image and
# silently keeps serving old code (prompts.py, server/, etc. are baked into
# the image via COPY, not bind-mounted) — this bit us once already: a whole
# session's worth of prompt fixes sat unused in production because a plain
# restart was used instead of a rebuild. This script always rebuilds, and
# always stamps the build with the exact local commit/timestamp so it's
# independently verifiable afterward (see GET /api/config, or the Settings
# page's Build Info card) — never assume a deploy worked; check the running
# build identity.
#
# Usage: ./sync.sh [user@host]   (defaults to azureuser@4.247.26.45)
set -euo pipefail

HOST="${1:-azureuser@4.247.26.45}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/llama-si_key.pem}"
REMOTE_DIR="/home/azureuser/ar-voice-agent"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

GIT_COMMIT="$(git -C "$LOCAL_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DIRTY=""
if [ "$GIT_COMMIT" != "unknown" ] && ! git -C "$LOCAL_DIR" diff --quiet 2>/dev/null; then
  DIRTY=" (with uncommitted local changes)"
fi

echo "==> Syncing commit ${GIT_COMMIT:0:12}${DIRTY} to $HOST..."
# NEVER sync .env: it's gitignored and host-specific (PUBLIC_DOMAIN, API
# keys, etc.) — this bit us once already. A local .env with a different
# PUBLIC_DOMAIN silently overwrote the VM's, which broke Caddy's TLS cert
# lookup (it's keyed by domain) and took HTTPS down until caught and fixed
# by hand. If you need to change a value in the VM's .env, SSH in and edit
# it directly — never push it from a local checkout.
rsync -avz -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  --exclude .git --exclude infra --exclude __pycache__ --exclude .env \
  --exclude 'frontend/node_modules' --exclude 'frontend/.next' \
  --exclude chatterbox-venv \
  "$LOCAL_DIR/" "$HOST:$REMOTE_DIR/"

echo "==> Rebuilding on $HOST (GIT_COMMIT=$GIT_COMMIT, BUILD_TIME=$BUILD_TIME)..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$HOST" \
  "cd $REMOTE_DIR && GIT_COMMIT=$GIT_COMMIT BUILD_TIME=$BUILD_TIME ./rebuild.sh"

echo "==> Verifying..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$HOST" \
  "curl -s http://localhost:8080/api/config | python3 -c 'import json,sys; d=json.load(sys.stdin); print(\"running build_commit=\" + d.get(\"build_commit\",\"?\") + \" build_time=\" + d.get(\"build_time\",\"?\"))'"
echo "==> Done. Cross-check build_commit above against: git rev-parse HEAD -> $GIT_COMMIT"
