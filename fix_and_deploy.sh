#!/bin/bash
set -e

cd "/mnt/c/Users/karthikeyan/Desktop/Calling Bot/ar-hosted-calling"

echo "=== Fixing line endings ==="
find . -name "*.sh" -exec sed -i 's/\r$//' {} +

echo "=== Fixing ollama create syntax in start-local.sh ==="
sed -i "s/printf 'FROM llama3.1:8b\\\\nPARAMETER num_ctx 8192\\\\n' | ollama create ar-agent -/printf 'FROM llama3.1:8b\\nPARAMETER num_ctx 8192\\n' | ollama create ar-agent -f -/" start-local.sh

echo "=== Verifying fix ==="
head -10 start-local.sh

echo "=== Syncing to VM ==="
VM_IP="85.211.177.112"
KEY="/mnt/c/Users/karthikeyan/Desktop/Calling Bot/vm-llama-t4-16gb_key.pem"

# Check if key exists
if [ ! -f "$KEY" ]; then
    # Try alternative paths
    for alt in \
        "/mnt/c/Users/karthikeyan/vm-llama-t4-16gb_key.pem" \
        "/mnt/c/Users/karthikeyan/Desktop/vm-llama-t4-16gb_key.pem" \
        "$HOME/vm-llama-t4-16gb_key.pem" \
        "$HOME/.ssh/vm-llama-t4-16gb_key.pem"; do
        if [ -f "$alt" ]; then
            KEY="$alt"
            echo "Found key at: $KEY"
            break
        fi
    done
fi

if [ ! -f "$KEY" ]; then
    echo "ERROR: SSH key not found. Tried:"
    echo "  $KEY"
    echo "  /mnt/c/Users/karthikeyan/vm-llama-t4-16gb_key.pem"
    echo "  /mnt/c/Users/karthikeyan/Desktop/vm-llama-t4-16gb_key.pem"
    echo "  $HOME/vm-llama-t4-16gb_key.pem"
    echo "  $HOME/.ssh/vm-llama-t4-16gb_key.pem"
    exit 1
fi

chmod 600 "$KEY"

echo "=== Testing SSH ==="
ssh -i "$KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 azureuser@$VM_IP "echo 'SSH OK'"

echo "=== Syncing code ==="
rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
  --exclude infra/ --exclude .git/ --exclude __pycache__ --exclude "*.pyc" \
  ./ azureuser@$VM_IP:/opt/ar-voice-agent/deploy/

echo "=== Building and starting on VM ==="
ssh -i "$KEY" azureuser@$VM_IP '
  cd /opt/ar-voice-agent/deploy &&
  docker compose --profile prod --profile tls up -d --build
'

echo "=== Checking health ==="
sleep 10
ssh -i "$KEY" azureuser@$VM_IP 'curl -s http://localhost:8080/health'

echo "=== Done! Check logs with: ==="
echo "ssh -i $KEY azureuser@$VM_IP 'cd /opt/ar-voice-agent/deploy && docker compose --profile prod --profile tls logs -f voice-agent'"