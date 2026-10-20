#!/bin/bash
set -e

echo "=== Restarting Docker and checking config ==="
sudo systemctl restart docker
sleep 5
sudo docker info | grep -A5 "Docker Root Dir"

echo "=== Checking build cache location ==="
sudo docker builder prune -af

echo "=== Retrying build ==="
cd /opt/ar-voice-agent/deploy
sudo docker compose --profile prod --profile tls up -d --build