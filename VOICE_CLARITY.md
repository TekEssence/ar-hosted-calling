# Cloned voice clarity and repeated questions

The Chatterbox/Whisper/vLLM architecture and the saved reference voice are unchanged.
The selected Chatterbox call mode is plain speech, with bounded word-boundary chunks:
currency is spoken as dollars/cents, long digit runs are grouped without changing
their digits, and common RD/STE/APT/AVE/BLVD labels are expanded. Explicit spelling
still preserves the value. A long first clause is now split instead of being sent as
one oversized generation. Unbroken tokens are not chopped in the middle.

Chatterbox caches up to four reference conditioning sets keyed by path, file
modification time, size and exaggeration. Updating a clip invalidates its cache.
Generation, preparation and unloading are serialized; cancellation waits for the
in-flight worker before another request can change shared model conditioning.
Requests use temperature 0.65 and repetition penalty 1.3 to reduce generation drift.

Voice preparation happens before the browser greeting or placing a Twilio call.
The browser shows a preparation status; after preparation, audio is still returned
as a complete clip per chunk, NOT true incremental model streaming. Cold preparation
may remain slow, and the model still unloads after five minutes idle to protect the
shared T4. Last-use timing is initialized after warm-up, not left at zero.

Browser/chat history now includes a bounded verbatim memory of earlier answers,
rather than simply dropping them. An exactly repeated answered question is retried
once before speech. If that retry still repeats it, a brief acknowledgment replaces
the duplicate. This is conservative: unclear replies and requested repetitions are
not treated as completed answers. Paraphrased repetitions are not guaranteed to be
detected, and very long histories can exceed the bounded memory.

Phone output is buffered through its first question and checked before playback,
instead of restarting/cancelling TTS at every streamed sentence/decimal boundary.
This can slightly delay text generation-to-playback but avoids clipped values and
replayed prefixes. Audio generation itself remains autoregressive and can still
mispronounce or stutter, especially with a noisy reference. Do not claim zero
stuttering without listening and testing actual identifiers/addresses.

`tests/test_voice_and_memory.py` checks digit/currency preservation, chunking,
reference-cache reuse and history/repeat handling without GPU models.
`python3 validate-chatterbox-clarity.py` on the VM makes synthetic voice requests,
reports timing/cache hits and saves two sample WAVs in `~/chatterbox-validation/`.
Listen before using clinical calls. No real patient information or phone calls
are used by that validator. Recorded reference clips/configuration are backed up
before deployment; no paid Azure resource or new voice model is introduced.
