#!/bin/bash
cd /opt/ar-voice-agent/deploy

cat > .env << 'EOF'
# Domain config (enables Caddy TLS + Twilio webhooks)
PUBLIC_DOMAIN=call.ar-voice.com
PUBLIC_SCHEME=https

# Model config
WHISPER_MODEL_SIZE=distil-large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE=float16
VLLM_BASE_URL=http://vllm:8001/v1
LLM_MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4
REDIS_URL=redis://redis:6379
TTS_ENGINE=piper

# Twilio - ADD YOUR CREDENTIALS HERE
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1xxxxxxxxxx

# Optional
HF_TOKEN=
EOF

cat .env