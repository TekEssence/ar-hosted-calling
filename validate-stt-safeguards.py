"""Run synthetic CPU STT checks inside the API container, without a second GPU model."""
import subprocess

code = r'''
import json
import numpy as np
from faster_whisper import WhisperModel
from piper import PiperVoice
from audio import transcribe_live, resample

class NeverDecode:
    def transcribe(self, *args, **kwargs):
        raise AssertionError("Whisper should not run for near-silence")

for label, samples in [('silence', np.zeros(16000, dtype=np.float32)),
                       ('very_quiet_noise', np.random.default_rng(7).normal(0, 0.00002, 16000).astype(np.float32))]:
    diagnostics = {}
    assert transcribe_live(NeverDecode(), samples, diagnostics) == ''
    print(label + ': ' + json.dumps(diagnostics), flush=True)

# Reuse downloaded files; never start another GPU instance or download a new model.
model = WhisperModel('distil-large-v3', device='cpu', compute_type='int8', local_files_only=True)
diagnostics = {}
noise = np.random.default_rng(17).normal(0, 0.008, 32000).astype(np.float32)
text = transcribe_live(model, noise, diagnostics)
print('broadband_noise: ' + json.dumps(diagnostics), flush=True)
assert not text, 'Synthetic non-speech was accepted; thresholds need further investigation'

voice = PiperVoice.load('/models/piper/en_US-lessac-medium.onnx')
for phrase in ('No, the payment is still pending.', 'The reference number is seven three nine two.'):
    samples = []
    sr = None
    for chunk in voice.synthesize(phrase):
        sr = chunk.sample_rate
        samples.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16).astype(np.float32) / 32768)
    audio = resample(np.concatenate(samples), sr, 16000)
    diagnostics = {}
    text = transcribe_live(model, audio, diagnostics)
    print('synthetic_speech: ' + json.dumps({'text': text, 'diagnostics': diagnostics}), flush=True)
    assert text and diagnostics['status'] == 'accepted', 'Synthetic speech unexpectedly filtered'
print('Synthetic STT checks: OK', flush=True)
'''

subprocess.run(['docker', 'exec', '-i', 'voice-agent', 'python', '-'], input=code,
               text=True, check=True)
