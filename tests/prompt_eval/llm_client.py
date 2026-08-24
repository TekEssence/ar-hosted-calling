"""Minimal stdlib-only OpenAI-compatible chat client for the vLLM endpoint.

Talks to whatever OpenAI-compatible server is at VLLM_BASE_URL — normally an
SSH tunnel to the vLLM container on the GPU VM (see ../README.md for how to
open it). No third-party HTTP client required, so this runs with a bare
python3 and no venv/pip install.
"""
import json
import os
import urllib.request

BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:18001/v1")
MODEL = os.environ.get("LLM_MODEL", "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4")


def chat(messages, max_tokens=260, temperature=0.0, model=None, timeout=120):
    payload = {
        "model": model or MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choice = data["choices"][0]
    content = choice["message"]["content"]
    usage = data.get("usage", {})
    return content, usage
