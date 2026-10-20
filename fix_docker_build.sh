#!/bin/bash
set -e

echo "=== Fixing Docker daemon config ==="
sudo mkdir -p /mnt/docker
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "data-root": "/mnt/docker",
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  }
}
EOF

echo "=== Restarting Docker ==="
sudo systemctl daemon-reload
sudo systemctl restart docker
sleep 5

echo "=== Verifying Docker root dir ==="
sudo docker info | grep -A2 "Docker Root Dir"

echo "=== Checking disk space ==="
df -h /mnt
df -h /

echo "=== Cleaning build cache ==="
sudo docker builder prune -af

echo "=== Retrying build ==="
cd /opt/ar-voice-agent/deploy
sudo docker compose --profile prod --profile tls up -d --build