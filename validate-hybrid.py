"""Smoke-test the hybrid VM without phone calls or deleting/restarting anything."""
import json
import subprocess
import urllib.request


def get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.status, response.read()


status, _ = get('https://call.ar-voice.com/')
assert status == 200
print('Public HTTPS homepage: OK')
_, body = get('https://call.ar-voice.com/ready')
assert json.loads(body)['status'] == 'ready'
print('Public core readiness: OK')
_, body = get('http://127.0.0.1:8001/v1/models')
model = json.loads(body)['data'][0]['id']
request = urllib.request.Request('http://127.0.0.1:8001/v1/chat/completions',
    data=json.dumps({'model': model, 'messages': [{'role': 'user', 'content': 'Reply with hello.'}],
                     'max_tokens': 8, 'temperature': 0}).encode(),
    headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=60) as response:
    result = json.load(response)
assert result['choices'][0]['message']['content']
print('Local LLM generation: OK')
get('http://127.0.0.1:8082/health')
print('Chatterbox HTTP health: OK (not a synthesis test)')
subprocess.run(['docker', 'exec', 'voice-agent', 'python', '-c',
    'import io,wave; from piper import PiperVoice; '
    'voice=PiperVoice.load("/models/piper/en_US-lessac-medium.onnx"); '
    'buffer=io.BytesIO(); '
    'writer=wave.open(buffer,"wb"); '
    'voice.synthesize_wav("Hello, this is a development test.", writer); writer.close(); '
    'buffer.seek(0); audio=wave.open(buffer); '
    'assert audio.getnframes()>0; print("Piper audio generation: OK")'], check=True)
for volume, folder in [('redis-data', 'redis'), ('chatterbox-voices', 'voices'), ('caddy-data', 'caddy')]:
    result = subprocess.run(['docker', 'volume', 'inspect', 'ar-voice-agent_' + volume],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)[0]['Options']['device'] == '/var/lib/ar-voice-agent/' + folder
print('Permanent data volume mappings: OK')
