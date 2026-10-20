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
KEY="/root/.ssh/vm-key.pem"

echo "=== Testing SSH ==="
ssh -i "$KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 azureuser@$VM_IP "echo 'SSH OK'"

echo "=== Creating deploy directory on VM ==="
ssh -i "$KEY" azureuser@$VM_IP 'sudo mkdir -p /opt/ar-voice-agent/deploy && sudo chown -R azureuser:azureuser /opt/ar-voice-agent'

echo "=== Syncing code ==="
rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
  --exclude infra/ --exclude .git/ --exclude __pycache__ --exclude "*.pyc" \
  ./ azureuser@$VM_IP:/opt/ar-voice-agent/deploy/

echo "=== Building and starting on VM (prod + tls) ==="
ssh -i "$KEY" azureuser@$VM_IP '
  cd /opt/ar-voice-agent/deploy &&
  docker compose --profile prod --profile tls up -d --build
'

echo "=== Checking health (waiting 20s for startup) ==="
sleep 20
ssh -i "$KEY" azureuser@$VM_IP 'curl -s http://localhost:8080/health'

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo ""
echo "Access points:"
echo "  Health check:  http://85.211.177.112:8080/health"
echo "  Dashboard:     http://85.211.177.112:8080/dashboard"
echo "  Browser test:  http://85.211.177.112:8080/test"
echo ""
echo "To view logs:"
echo "  ssh -i $KEY azureuser@$VM_IP 'cd /opt/ar-voice-agent/deploy && docker compose --profile prod --profile tls logs -f voice-agent'"
echo ""
echo "To set up DNS + TLS for Twilio:"
echo "  1. Create A record: call.yourdomain.com -> 85.211.177.112"
echo "  2. Edit .env on VM with PUBLIC_DOMAIN=call.yourdomain.com"
echo "  3. Restart: ssh -i $KEY azureuser@$VM_IP 'cd /opt/ar-voice-agent/deploy && docker compose --profile prod --profile tls restart voice-agent caddy'"