#!/bin/bash
set -e

echo "=== Moving containerd to /mnt ==="
sudo mkdir -p /mnt/containerd
sudo systemctl stop docker
sudo systemctl stop containerd 2>/dev/null || true

# Move existing containerd data if any
if [ -d /var/lib/containerd ]; then
    sudo mv /var/lib/containerd/* /mnt/containerd/ 2>/dev/null || true
fi

# Bind mount
sudo mount --bind /mnt/containerd /var/lib/containerd

# Make it persistent
if ! grep -q "/mnt/containerd /var/lib/containerd" /etc/fstab; then
    echo "/mnt/containerd /var/lib/containerd none bind 0 0" | sudo tee -a /etc/fstab
fi

echo "=== Restarting Docker ==="
sudo systemctl start docker
sleep 5

echo "=== Verifying ==="
sudo docker info | grep -A2 "Docker Root Dir"
df -h /

echo "=== Cleaning build cache ==="
sudo docker builder prune -af

echo "=== Building images one by one ==="
cd /opt/ar-voice-agent/deploy

# Build vLLM first (largest)
echo "=== Building vLLM ==="
sudo docker pull vllm/vllm-openai:latest

# Build voice-agent
echo "=== Building voice-agent ==="
sudo docker compose --profile prod --profile tls build voice-agent

# Build frontend
echo "=== Building frontend ==="
sudo docker compose --profile prod --profile tls build frontend

# Pull remaining
echo "=== Pulling redis and caddy ==="
sudo docker pull redis:7-alpine
sudo docker pull caddy:2-alpine

# Start all
echo "=== Starting all services ==="
sudo docker compose --profile prod --profile tls up -d