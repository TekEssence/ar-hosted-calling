#!/bin/bash
set -e

echo "=== Installing Docker + NVIDIA runtime on VM ==="

# Update & install basics
sudo apt update
sudo apt install -y curl gnupg lsb-release ca-certificates

# Install Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Configure Docker data root + NVIDIA runtime
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  },
  "data-root": "/mnt/docker"
}
EOF

# Move Docker data to /mnt (larger disk)
sudo systemctl stop docker 2>/dev/null || true
sudo mkdir -p /mnt/docker
sudo mv /var/lib/docker/* /mnt/docker/ 2>/dev/null || true
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $USER

# Install NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Install NVIDIA drivers (if not present)
if ! command -v nvidia-smi &> /dev/null; then
    echo "Installing NVIDIA drivers..."
    sudo apt install -y ubuntu-drivers-common
    sudo ubuntu-drivers autoinstall
    echo "REBOOT REQUIRED for NVIDIA drivers"
else
    echo "NVIDIA drivers already installed"
    nvidia-smi
fi

# Verify
docker version
docker run --rm --gpus all nvidia/cuda:12.4-base-ubuntu22.04 nvidia-smi

echo "=== Bootstrap complete ==="