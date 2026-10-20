"""Synthetic cloned-voice/cache timing checks; no phone calls/customer records."""
import base64
import json
from pathlib import Path
import subprocess
import urllib.request
import wave


def post(path, payload):
    request = urllib.request.Request('http://127.0.0.1:8082/' + path,
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


with urllib.request.urlopen('http://127.0.0.1:8080/api/config', timeout=15) as response:
    config = json.load(response)
voice = config['chatterbox_voice']
base = {'text': '', 'voice_name': voice, 'exaggeration': 0.5, 'cfg_weight': 0.5}
first = post('prepare', base)
second = post('prepare', base)
assert first['ok'] and second['ok'] and second['voice_cached']
print('Preparation:', json.dumps({'first': first, 'cached': second}), flush=True)
folder = Path.home() / 'chatterbox-validation'
folder.mkdir(mode=0o700, exist_ok=True)
samples = [('reference', 'The reference number is 7392.'),
           ('address', 'The mailing address is 1310 Test RD, STE 103.')]
for name, phrase in samples:
    result = subprocess.run(['docker', 'exec', 'voice-agent', 'python', '-c',
        'import json,sys; from server.tts_plain import tts_text,_split_plain_chunks; '
        'print(json.dumps(_split_plain_chunks(tts_text(sys.argv[1]))))', phrase],
        check=True, capture_output=True, text=True)
    chunks = json.loads(result.stdout)
    audio = bytearray()
    generation_ms = 0
    for chunk in chunks:
        output = post('tts', {**base, 'text': chunk})
        assert output['voice_cached'], 'Reference unexpectedly re-encoded'
        sr = output['sr']
        audio.extend(base64.b64decode(output['pcm']))
        generation_ms += output['generation_ms']
    path = folder / (name + '.wav')
    with wave.open(str(path), 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sr)
        writer.writeframes(audio)
    assert audio
    print(json.dumps({'sample': name, 'chunks': chunks, 'generation_ms': generation_ms,
                      'audio_seconds': round(len(audio) / 2 / sr, 2), 'file': str(path)}), flush=True)
print('Cloned voice generation/cache checks: OK. Listen to WAVs to assess audible clarity.', flush=True)
