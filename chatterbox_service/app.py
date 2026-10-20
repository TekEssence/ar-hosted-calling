"""Chatterbox TTS — isolated service.

Runs ChatterboxTTS in its own container with its own transformers env so its
heavy/conflicting deps (transformers 5.2.0, matching torch/torchvision) never
touch the main voice-agent environment. The main app calls this over HTTP.
"""
import asyncio
import base64
import os
import time
from collections import OrderedDict

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

VOICES_DIR = os.getenv("CHATTERBOX_VOICES_DIR", "/models/chatterbox/voices")
DEVICE = os.getenv("CHATTERBOX_DEVICE", "cuda")
# Idle time before the model is unloaded from GPU so it doesn't crowd out
# vLLM/Whisper/Kokoro on the shared T4. Reloads on demand (~40s).
IDLE_UNLOAD_S = float(os.getenv("CHATTERBOX_IDLE_UNLOAD_S", "300"))

app = FastAPI()
_model = None
_model_sr = None
_last_used = 0.0
_watchdog = None
_generation_lock = asyncio.Lock()
_voice_conditions = OrderedDict()
_default_conditions = None


class TTSRequest(BaseModel):
    text: str
    voice_name: str = ""
    exaggeration: float = 0.5
    cfg_weight: float = 0.5


def _prepare_voice(voice_name: str, exaggeration: float):
    """Reuse the selected voice embedding; do not reread/re-encode its WAV per chunk."""
    if not voice_name:
        _model.conds = _default_conditions
        return False
    if os.path.basename(voice_name) != voice_name or '/' in voice_name or '\\' in voice_name:
        raise HTTPException(400, 'invalid voice name')
    path = os.path.join(VOICES_DIR, voice_name + '.wav')
    if not os.path.isfile(path):
        raise HTTPException(404, 'voice reference not found')
    stat = os.stat(path)
    key = (path, stat.st_mtime_ns, stat.st_size, exaggeration)
    if key in _voice_conditions:
        _model.conds = _voice_conditions[key]
        _voice_conditions.move_to_end(key)
        return True
    _model.prepare_conditionals(path, exaggeration=exaggeration)
    _voice_conditions[key] = _model.conds
    while len(_voice_conditions) > 4:
        _voice_conditions.popitem(last=False)
    return False


def _cast_fp16(model):
    """Run the heavy parts of Chatterbox in fp16 instead of the SDK's fp32.

    The SDK hard-codes fp32 and exposes no dtype option. The T3 backbone is a
    Llama_520M — the bulk of the weights (~2GB fp32) and the autoregressive
    hot loop, so casting it to fp16 roughly halves memory on the shared T4
    and ~2x's its matmuls; quality loss is inaudible for TTS (the model is
    bf16-born). The voice encoder is LEFT in fp32: the cloned-voice path
    feeds it fp32 mel spectrograms from the reference wav, and its LSTM
    rejects fp16 input (ValueError: input must have the type torch.float16,
    got fp32). It only runs once per clone prep, so fp32 costs nothing in the
    hot loop. S3Gen (flow-matching + HiFTGAN vocoder) is left in fp32 too:
    its torch.istft isn't reliably fp16-safe on the container's torch 2.5.1
    CUDA and it only runs once at the end of a generation.
    """
    import torch

    model.t3.half()

    def _half_t3cond(cond):
        # Only cast floating tensors; token ids stay long. S3Gen's ref
        # embedding dict is intentionally untouched (fp32 vocoder path).
        for k, v in cond.__dict__.items():
            if torch.is_tensor(v) and v.dtype.is_floating_point:
                setattr(cond, k, v.half())
        return cond

    def _half_conds():
        if model.conds is not None:
            _half_t3cond(model.conds.t3)

    _half_conds()

    # Voice-clone path: prepare_conditionals rebuilds conds from numpy (fp32
    # speaker emb, fp32 emotion_adv) — re-cast the T3 part after it runs.
    orig_prepare = model.prepare_conditionals

    def prepare_fp16(wav_fpath, exaggeration=0.5):
        orig_prepare(wav_fpath, exaggeration=exaggeration)
        _half_conds()

    model.prepare_conditionals = prepare_fp16

    # generate() re-arms T3Cond (fresh fp32 emotion_adv) in its
    # exaggeration-update branch — keep conds fp16 so nothing fp32 ever
    # reaches the fp16 T3 modules.
    orig_generate = model.generate

    def generate_fp16(*args, **kwargs):
        _half_conds()
        try:
            return orig_generate(*args, **kwargs)
        finally:
            _half_conds()

    model.generate = generate_fp16


def _load():
    global _model, _model_sr, _last_used, _default_conditions
    from chatterbox.tts import ChatterboxTTS
    _model = ChatterboxTTS.from_pretrained(device=DEVICE)
    _cast_fp16(_model)
    _model_sr = _model.sr
    print(f"Chatterbox loaded: device={DEVICE} sr={_model_sr} dtype=fp16(t3)/fp32(ve,s3)", flush=True)
    _warmup()
    _default_conditions = _model.conds
    _last_used = time.time()


def _warmup():
    """Run one throwaway generation right after load. The idle-unload
    watchdog frees GPU memory for vLLM/Whisper between calls, but that means
    a call arriving after IDLE_UNLOAD_S pays full model-load PLUS first-
    inference cost inline — CUDA kernels/cuDNN algo selection for this
    model's shapes haven't run yet either. Paying that here, right after
    load, keeps it off the first real caller."""
    t0 = time.time()
    try:
        _model.generate("Warming up.", exaggeration=0.5, cfg_weight=0.5)
        print(f"Chatterbox warmup: {(time.time() - t0) * 1000:.0f}ms", flush=True)
    except Exception as e:
        print(f"Chatterbox warmup failed (non-fatal): {e}", flush=True)


def _unload():
    global _model, _model_sr, _default_conditions
    if _model is None:
        return
    _model = None
    _model_sr = None
    _default_conditions = None
    _voice_conditions.clear()
    import gc
    import torch
    gc.collect()
    torch.cuda.empty_cache()
    print("Chatterbox unloaded (idle) — GPU freed", flush=True)


async def _watchdog_loop():
    while True:
        await asyncio.sleep(30)
        if _generation_lock.locked():
            continue
        async with _generation_lock:
            if _model is not None and time.time() - _last_used > IDLE_UNLOAD_S:
                _unload()


@app.on_event("startup")
async def startup():
    _load()
    global _watchdog
    _watchdog = asyncio.create_task(_watchdog_loop())


@app.get("/health")
def health():
    return {"ok": _model is not None, "sr": _model_sr}


@app.get("/voices")
def voices():
    if not os.path.isdir(VOICES_DIR):
        return {"voices": []}
    return {"voices": sorted(
        os.path.splitext(f)[0] for f in os.listdir(VOICES_DIR) if f.endswith(".wav")
    )}


@app.post("/tts")
async def tts(req: TTSRequest):
    text = (req.text or '').strip()
    if not text:
        raise HTTPException(400, 'text is required')
    return await _serialized_request(req, text)


@app.post('/prepare')
async def prepare(req: TTSRequest):
    """Pay model/voice preparation cost before the first spoken turn."""
    return await _serialized_request(req, None)


async def _serialized_request(req: TTSRequest, text: str | None):
    # Cancellation must not release shared model state while the worker still runs.
    async with _generation_lock:
        task = asyncio.create_task(asyncio.to_thread(_generate, req, text))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise


def _generate(req: TTSRequest, text: str | None):
    global _last_used
    started = time.perf_counter()
    if _model is None:
        _load()
    _last_used = time.time()
    cached = _prepare_voice(req.voice_name, req.exaggeration)
    if text is None:
        return {'ok': True, 'voice_cached': cached, 'prepare_ms': round((time.perf_counter() - started) * 1000)}
    wav = _model.generate(text, exaggeration=req.exaggeration, cfg_weight=req.cfg_weight,
                          temperature=0.65, repetition_penalty=1.3)
    _last_used = time.time()
    audio = wav.squeeze(0).detach().cpu().numpy().astype(np.float32)
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    return {"pcm": base64.b64encode(pcm.tobytes()).decode(), "sr": _model_sr,
            'generation_ms': round((time.perf_counter() - started) * 1000), 'voice_cached': cached}
