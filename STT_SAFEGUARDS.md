# Conservative live transcription safeguards

The existing architecture is unchanged: browser/Twilio -> VAD -> Faster-Whisper ->
LLM -> selected TTS engine. `audio.py:transcribe_live` is shared by browser and phone
calls and still returns a string. It now optionally fills a numeric diagnostics dict.

## Decisions

- Invalid/empty audio, under 120 ms, or near-silence (RMS below 0.0001): ignore.
- High no-speech probability (>= 0.8) AND low confidence (avg_logprob < -0.5): ignore.
- Weak decoded speech (avg_logprob < -1.0), or high compression ratio plus low
  confidence: ask for repetition rather than forwarding guessed text.
- Mixed accepted/uncertain segments: ask for the complete detail again; do not
  silently forward an incomplete amount/identifier.
- Otherwise accept the text, including genuine short replies and identifiers.

There is NO blacklist for 'Thank you'. These heuristics cannot detect every confident
hallucination; tune against actual failed audio, not the phrase alone. Faster-Whisper's
own VAD/confidence filtering still applies before these checks. Empty decoder output
does not by itself prove uncertain speech, so it is ignored without a repetition loop.

Browser/phone callers request repetition once for uncertain input and suppress repeated
requests until accepted speech arrives. Guessed candidate words are not added to the
representative transcript or LLM history. Confidence logs contain numbers/status, not
candidate patient text or new audio recordings. Existing full-call review recording
behavior is unchanged.

`STT_MIN_AUDIO_MS`, `STT_MIN_RMS`, `STT_WEAK_LOGPROB`, `STT_HIGH_NO_SPEECH` can be set
in the container environment (e.g. the VM `.env`, followed by recreation). Use modest
adjustments: aggressive thresholds can discard legitimate quiet speech. The Silero
iterator now explicitly receives its configured speech threshold; the default remains
0.5. No new denoising package or model is installed.

## Browser microphone comparison

The existing call panel has a microphone automatic-gain checkbox. Default remains
on. Compare on/off in fresh browser sessions using the same headset, speaking level
and background conditions. Echo cancellation/noise suppression remain requested.
The console records actual processing settings without device identifiers; browsers
may not honor every requested constraint. This setting does not affect Twilio audio.

## Validation and next test

Run the existing unit suite with `python -m unittest discover -s tests -p 'test_*.py'`.
`python3 validate-stt-safeguards.py` on the VM uses synthetic silence/noise and Piper
speech with cached CPU Whisper; it does not create phone calls or customer records.
CPU validation does not prove identical GPU behavior or real headset acoustics.

Repeat the problematic browser call and note the time/session ID. Compare incoming
audio in the existing review with STT diagnostics in `docker logs voice-agent`.
Observe normal speech, genuine 'Thank you', 'No', amounts/dates and identifiers.
The separate Chatterbox cold-start/non-streaming latency has not been changed here.
