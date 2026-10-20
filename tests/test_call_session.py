"""CallSession characterization tests with no GPU, Redis, or telephony access.

Load the real class body without importing model/server dependencies, following
the existing AST-based test pattern. These tests exercise controller behavior,
not dependency wiring, audio quality, or Twilio protocol compatibility.
"""
import ast
import asyncio
import base64
from collections import deque
import datetime
import json
import logging
import os
from pathlib import Path
import re
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

import prompts


def load_session_class():
    path = Path(__file__).resolve().parents[1] / 'call_session.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CallSession')
    namespace = dict(vars(prompts))
    namespace.update(
        asyncio=asyncio, base64=base64, datetime=datetime, json=json,
        logging=logging, os=os, re=re, time=time, deque=deque, np=np,
        WebSocket=object, WebSocketDisconnect=RuntimeError,
        VAD=Mock, log=logging.getLogger('test-call-session'),
        _bg_tasks=set(), _opik_span=Mock(), PIPER_RATE=22050,
        MAX_HOLD_SEC=1800, MAX_SILENCE_MS=19 * 60 * 1000,
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['CallSession']


class CallSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = Mock()
        self.redis.hgetall = AsyncMock(return_value={})
        self.redis.hset = AsyncMock()
        self.redis.set = AsyncMock()
        self.redis.delete = AsyncMock()
        self.redis.publish = AsyncMock()
        self.redis.rpush = AsyncMock()
        self.ws = Mock(send_text=AsyncMock(), close=AsyncMock())
        self.session = load_session_class()(self.ws, 'synthetic-call', {
            'redis': self.redis,
            'stt_model': Mock(),
            'stt_lock': asyncio.Lock(),
            'llm_client': Mock(),
            'llm_model': 'synthetic-model',
            'tts_stream_fn': Mock(),
            'use_silero': False,
        })
        self.session.vad.speech_start = None
        self.session.vad._speech_start_s = None

    async def test_start_preserves_call_identity_and_loads_context(self):
        self.redis.hgetall.return_value = {'UID': 'synthetic-account', 'Claim ID': 'TEST-001'}
        self.session._resolve_prompt = AsyncMock(return_value='synthetic prompt')
        self.session._speak = AsyncMock()
        self.session.conversation = [{'role': 'system', 'content': 'initial'}]
        await self.session._on_start({'start': {
            'streamSid': 'synthetic-stream',
            'customParameters': {'account_uid': 'synthetic-account'},
        }})
        self.assertEqual(self.session.call_sid, 'synthetic-call')
        self.assertEqual(self.session.stream_sid, 'synthetic-stream')
        self.assertEqual(self.session.account['Claim ID'], 'TEST-001')
        self.assertEqual(self.session.conversation[0]['content'], 'synthetic prompt')
        self.assertEqual(self.session.state, 'IVR_NAV')
        self.session._speak.assert_awaited_once_with(
            prompts.build_greeting(self.session.account), interruptible=False)
        self.redis.hset.assert_awaited_with(
            'call:synthetic-call', mapping={'status': 'in-progress'})

    async def test_live_transcript_uses_stable_call_key(self):
        turn = {'role': 'user', 'text': 'Synthetic menu prompt'}
        await self.session._live_append(turn)
        self.redis.rpush.assert_awaited_once_with('call:synthetic-call:live', json.dumps(turn))

    async def test_speak_does_not_start_before_stream_or_after_end(self):
        self.session._stream_tts = AsyncMock()
        await self.session._speak('Synthetic reply')
        self.session.stream_sid = 'synthetic-stream'
        self.session.is_call_ended = True
        await self.session._speak('Synthetic reply')
        self.session._stream_tts.assert_not_called()
        self.assertIsNone(self.session.tts_task)

    async def test_cancel_stops_active_synthesis(self):
        started = asyncio.Event()

        async def synthesize():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(synthesize())
        await started.wait()
        self.session.tts_task = task
        stop = self.session.tts_stop_event = asyncio.Event()
        self.session.is_bot_speaking = True
        await self.session._cancel_tts()
        self.assertTrue(stop.is_set())
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.session.tts_task)
        self.assertFalse(self.session.is_bot_speaking)

    async def test_barge_in_clears_remote_playback(self):
        self.session.stream_sid = 'synthetic-stream'
        self.session.pending_marks.add('old-playback')
        self.session._cancel_tts = AsyncMock(wraps=self.session._cancel_tts)
        await self.session._barge_in()
        self.session._cancel_tts.assert_awaited_once()
        self.assertEqual(json.loads(self.ws.send_text.call_args.args[0]), {
            'event': 'clear', 'streamSid': 'synthetic-stream'})

    async def test_finalize_persists_result_once(self):
        result = {
            'status': 'pending', 'payer': 'Synthetic Payer', 'claim_id': 'TEST-001',
            'next_action': 'Follow up after the confirmed processing window',
            'reference_number': 'TEST-REF', 'call_summary': 'Synthetic pending claim',
        }
        await self.session._finalize('completed', result=result)
        await self.session._finalize('disconnected', result=result)
        updates = [call.kwargs['mapping'] for call in self.redis.hset.await_args_list
                   if call.args[0] == 'call:synthetic-call']
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]['status'], 'pending')
        self.assertEqual(updates[0]['reference_number'], 'TEST-REF')
        review = next(call.args[1] for call in self.redis.set.await_args_list
                      if call.args[0] == 'call:synthetic-call:review')
        self.assertEqual(json.loads(review)['call_result'], result)
        self.redis.publish.assert_awaited_once()
        self.ws.close.assert_awaited_once()

    async def test_disconnect_without_result_is_not_success(self):
        # Disable LLM repair: this test must never invoke an external service.
        self.session.call_result_retries = 2
        await self.session._finalize('disconnected')
        update = next(call.kwargs['mapping'] for call in self.redis.hset.await_args_list
                      if call.args[0] == 'call:synthetic-call')
        self.assertEqual(update['status'], 'failed')
        self.assertTrue(self.session.is_call_ended)
        self.ws.close.assert_awaited_once()

    async def test_media_records_audio_without_transcribing_before_endpoint(self):
        payload = b'\xff' * 160
        decoded = np.zeros(320, dtype=np.float32)
        self.session.vad.add.return_value = None
        self.session._transcribe = AsyncMock()
        self.session._run_llm = AsyncMock()
        decode = Mock(return_value=decoded)
        with patch.dict(self.session._on_media.__globals__, twilio_to_whisper=decode):
            await self.session._on_media({'media': {
                'payload': base64.b64encode(payload).decode()}})
        decode.assert_called_once_with(payload)
        self.assertEqual(bytes(self.session.full_audio), payload)
        self.assertIs(self.session.vad.add.call_args.args[0], decoded)
        self.session._transcribe.assert_not_awaited()
        self.session._run_llm.assert_not_awaited()

    async def test_media_endpoint_transcribes_before_running_conversation(self):
        segment = np.ones(1600, dtype=np.float32)
        self.session.vad.add.return_value = segment
        operations = []

        async def transcribe(audio):
            self.assertIs(audio, segment)
            operations.append('transcribe')
            return 'Synthetic claim is pending'

        async def respond(text):
            self.assertEqual(text, 'Synthetic claim is pending')
            operations.append('respond')

        self.session._transcribe = transcribe
        self.session._run_llm = respond
        with patch.dict(self.session._on_media.__globals__,
                        twilio_to_whisper=Mock(return_value=segment)):
            await self.session._on_media({'media': {'payload': '/w=='}})
        self.assertEqual(operations, [])
        queued = self.session.segment_queue.get_nowait()
        try:
            await self.session._process_segment(queued)
        finally:
            self.session.segment_queue.task_done()
        self.assertEqual(operations, ['transcribe', 'respond'])

    async def test_tts_frames_and_duration_use_eight_khz_mulaw(self):
        self.session.stream_sid = 'synthetic-stream'

        async def synthesize(text, **kwargs):
            yield b'\x00\x00' * 400

        self.session.tts_stream_fn = synthesize
        encoded = b'\xff' * 400  # 50ms at 8kHz: two full frames and a tail.
        encode = Mock(return_value=encoded)
        with patch.dict(self.session._stream_tts.__globals__, piper_to_twilio=encode):
            await self.session._stream_tts('Synthetic reply', asyncio.Event())
        messages = [json.loads(call.args[0]) for call in self.ws.send_text.await_args_list]
        frames = [base64.b64decode(m['media']['payload'])
                  for m in messages if m['event'] == 'media']
        self.assertEqual([len(frame) for frame in frames], [160, 160, 80])
        self.assertEqual(b''.join(frames), encoded)
        self.assertAlmostEqual(self.session.last_tts_duration, 0.05)
        self.assertEqual(self.session.tts_count, 1)
        self.assertEqual(encode.call_args.args[1], 22050)

    async def test_playback_stays_active_until_twilio_acknowledges_mark(self):
        """Synthesis completion is not remote playback completion."""
        self.session.stream_sid = 'synthetic-stream'

        async def synthesize(text, **kwargs):
            yield b'\x00\x00' * 160

        self.session.tts_stream_fn = synthesize
        with patch.dict(self.session._stream_tts.__globals__,
                        piper_to_twilio=Mock(return_value=b'\xff' * 160)):
            await self.session._stream_tts('Synthetic reply', asyncio.Event())
        messages = [json.loads(call.args[0]) for call in self.ws.send_text.await_args_list]
        self.assertTrue(any(m['event'] == 'mark' for m in messages),
                        'Send a playback mark after media before waiting for acknowledgement')
        self.assertTrue(self.session.is_bot_speaking,
                        'Queued audio must remain speaking until playback is acknowledged')
        self.assertFalse(self.session.playback_done.is_set())
        mark = next(m for m in messages if m['event'] == 'mark')
        self.session._on_mark(mark)
        self.assertFalse(self.session.is_bot_speaking)
        self.assertTrue(self.session.playback_done.is_set())

    async def test_stale_or_foreign_marks_cannot_finish_new_playback(self):
        self.session.stream_sid = 'synthetic-stream'
        self.session.pending_marks.add('old')
        await self.session._cancel_tts()
        self.session.pending_marks.add('new')
        self.session.is_bot_speaking = True
        self.session.playback_done.clear()
        self.session._on_mark({'streamSid': 'synthetic-stream', 'mark': {'name': 'old'}})
        self.session._on_mark({'streamSid': 'foreign-stream', 'mark': {'name': 'new'}})
        self.assertEqual(self.session.pending_marks, {'new'})
        self.assertTrue(self.session.is_bot_speaking)
        self.assertFalse(self.session.playback_done.is_set())

    async def test_all_pending_marks_must_be_acknowledged(self):
        self.session.stream_sid = 'synthetic-stream'
        self.session.pending_marks.update(('first', 'second'))
        self.session.playback_done.clear()
        self.session._on_mark({'streamSid': 'synthetic-stream', 'mark': {'name': 'first'}})
        self.assertTrue(self.session.is_bot_speaking)
        self.assertFalse(self.session.playback_done.is_set())
        self.session._on_mark({'streamSid': 'synthetic-stream', 'mark': {'name': 'second'}})
        self.assertFalse(self.session.is_bot_speaking)
        self.assertTrue(self.session.playback_done.is_set())

    async def test_playback_wait_unblocks_on_acknowledgement(self):
        self.session.stream_sid = 'synthetic-stream'
        self.session.pending_marks.add('farewell')
        self.session.playback_done.clear()
        waiter = asyncio.create_task(self.session._wait_for_playback())
        try:
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            self.session._on_mark({'streamSid': 'synthetic-stream', 'mark': {'name': 'farewell'}})
            await asyncio.wait_for(waiter, 1)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def test_cancelling_unfinished_synthesis_clears_already_sent_audio(self):
        self.session.stream_sid = 'synthetic-stream'
        sent = asyncio.Event()

        async def synthesize(text, **kwargs):
            yield b'\x00\x00' * 160
            sent.set()
            await asyncio.Event().wait()

        self.session.tts_stream_fn = synthesize
        with patch.dict(self.session._stream_tts.__globals__,
                        piper_to_twilio=Mock(return_value=b'\xff' * 160)):
            await self.session._speak('Synthetic reply')
            try:
                await asyncio.wait_for(sent.wait(), 1)
                self.assertTrue(self.session.is_bot_speaking)
                self.assertFalse(self.session.pending_marks)
            finally:
                await self.session._cancel_tts()
        messages = [json.loads(call.args[0]) for call in self.ws.send_text.await_args_list]
        self.assertEqual(messages[-1]['event'], 'clear')
        self.assertFalse(self.session.is_bot_speaking)
        self.assertTrue(self.session.playback_done.is_set())

    async def test_receive_loop_keeps_reading_while_a_turn_is_processing(self):
        """Real media ingestion continues while the speech worker is blocked."""
        first_started = asyncio.Event()
        second_received = asyncio.Event()
        release = asyncio.Event()
        self.ws.accept = AsyncMock()

        async def incoming():
            yield json.dumps({'event': 'media', 'media': {'payload': '/w=='}})
            second_received.set()
            yield json.dumps({'event': 'media', 'media': {'payload': '/w=='}})
            await release.wait()

        async def process(segment):
            first_started.set()
            await release.wait()

        async def watchdog():
            await release.wait()

        self.ws.iter_text = incoming
        self.session._resolve_prompt = AsyncMock(return_value='synthetic prompt')
        self.session._process_segment = process
        self.session.vad.add.return_value = np.zeros(1600, dtype=np.float32)
        self.session._silence_watchdog = watchdog
        decode_patch = patch.dict(self.session._on_media.__globals__,
                                 twilio_to_whisper=Mock(return_value=np.zeros(320)))
        decode_patch.start()
        runner = asyncio.create_task(self.session.run())
        try:
            await asyncio.wait_for(first_started.wait(), timeout=1)
            # Yield to ready tasks without relying on real STT/LLM latency.
            for _ in range(3):
                await asyncio.sleep(0)
            self.assertTrue(second_received.is_set(),
                            'The receiver must consume subsequent frames during turn processing')
        finally:
            release.set()
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
            if self.session.watchdog_task:
                await asyncio.gather(self.session.watchdog_task, return_exceptions=True)
            decode_patch.stop()

    async def test_worker_processes_segments_in_order_without_overlap(self):
        first_started = asyncio.Event()
        release = asyncio.Event()
        completed = []

        async def process(segment):
            if segment == 'first':
                first_started.set()
                await release.wait()
            completed.append(segment)

        self.session._process_segment = process
        worker = asyncio.create_task(self.session._process_segments())
        try:
            self.session.segment_queue.put_nowait('first')
            self.session.segment_queue.put_nowait('second')
            await asyncio.wait_for(first_started.wait(), 1)
            self.assertEqual(completed, [])
            self.assertEqual(self.session.segment_queue.qsize(), 1)
            release.set()
            await asyncio.wait_for(self.session.segment_queue.join(), 1)
            self.assertEqual(completed, ['first', 'second'])
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def test_queue_overflow_fails_explicitly_without_waiting(self):
        self.session.vad.add.return_value = np.zeros(1600, dtype=np.float32)
        self.session._finalize = AsyncMock()
        for _ in range(self.session.segment_queue.maxsize):
            self.session.segment_queue.put_nowait(np.zeros(1600))
        with patch.dict(self.session._on_media.__globals__,
                        twilio_to_whisper=Mock(return_value=np.zeros(320))):
            await asyncio.wait_for(
                self.session._on_media({'media': {'payload': '/w=='}}), 1)
        self.session._finalize.assert_awaited_once_with(
            'failed', error='Speech processing backlog exceeded')

    async def test_stop_cancels_worker_and_watchdog(self):
        self.ws.accept = AsyncMock()

        async def incoming():
            yield json.dumps({'event': 'stop'})

        async def watchdog():
            await asyncio.Event().wait()

        self.ws.iter_text = incoming
        self.session._resolve_prompt = AsyncMock(return_value='synthetic prompt')
        self.session._silence_watchdog = watchdog
        self.session._finalize = AsyncMock()
        await asyncio.wait_for(self.session.run(), 1)
        self.assertTrue(self.session.turn_task.done())
        self.assertTrue(self.session.watchdog_task.done())
        self.session._finalize.assert_awaited_once_with('disconnected')

    async def test_worker_error_finalizes_instead_of_silently_stopping(self):
        self.session._process_segment = AsyncMock(side_effect=ValueError('synthetic failure'))
        self.session._finalize = AsyncMock()
        self.session.segment_queue.put_nowait('synthetic segment')
        with self.assertLogs('test-call-session', level='ERROR'):
            await asyncio.wait_for(self.session._process_segments(), 1)
        await asyncio.wait_for(self.session.segment_queue.join(), 1)
        self.session._finalize.assert_awaited_once_with(
            'failed', error='Speech processing failed')

    async def test_silent_media_packets_do_not_refresh_speech_activity(self):
        self.session.last_activity = 123.0
        self.session.vad.add.return_value = None
        with patch.dict(self.session._on_media.__globals__,
                        twilio_to_whisper=Mock(return_value=np.zeros(320))):
            await self.session._on_media({'media': {'payload': '/w=='}})
        self.assertEqual(self.session.last_activity, 123.0)

    async def test_active_speech_refreshes_activity_before_endpoint(self):
        self.session.last_activity = 123.0
        self.session.vad.add.return_value = None
        self.session.vad._speech_start_s = 124.0
        with patch.dict(self.session._on_media.__globals__,
                        twilio_to_whisper=Mock(return_value=np.ones(320))):
            await self.session._on_media({'media': {'payload': '/w=='}})
        self.assertGreater(self.session.last_activity, 123.0)

    def test_hold_announcements_preserve_timer_and_resumption_resets_it(self):
        self.session.hold_start = 100.0
        self.session._update_hold_state(True)
        self.assertEqual(self.session.hold_start, 100.0)
        self.session._update_hold_state(False)
        self.assertIsNone(self.session.hold_start)
        self.session._update_hold_state(True)
        self.assertGreater(self.session.hold_start, 100.0)

    async def test_short_silence_does_not_invent_music_or_call_llm(self):
        self.session.last_activity = 100.0
        self.session._run_llm = AsyncMock()
        self.session._speak = AsyncMock()
        self.session._finalize = AsyncMock()
        await self.session._check_timeouts(115.0)
        self.session._run_llm.assert_not_awaited()
        self.session._speak.assert_not_awaited()
        self.session._finalize.assert_not_awaited()

    async def test_hold_timeout_waits_for_farewell_playback(self):
        self.session.hold_start = 100.0
        operations = []

        async def speak(text):
            operations.append('speak')

        async def playback():
            operations.append('playback')

        async def finalize(status):
            self.assertEqual(status, 'hold_timeout')
            operations.append('finalize')

        self.session._speak = speak
        self.session._wait_for_playback = playback
        self.session._finalize = finalize
        await self.session._check_timeouts(1901.0)
        self.assertEqual(operations, ['speak', 'playback', 'finalize'])

    async def test_hold_does_not_use_normal_silence_limit(self):
        self.session.hold_start = 1000.0
        self.session.last_activity = 0.0
        self.session._finalize = AsyncMock()
        await self.session._check_timeouts(1200.0)
        self.session._finalize.assert_not_awaited()

    async def test_silence_timeout_does_not_interrupt_busy_turn_or_playback(self):
        self.session.last_activity = 0.0
        self.session._finalize = AsyncMock()
        async with self.session.turn_lock:
            await self.session._check_timeouts(2000.0)
        self.session.is_bot_speaking = True
        await self.session._check_timeouts(2000.0)
        self.session.is_bot_speaking = False
        self.session.segment_queue.put_nowait('synthetic answer')
        await self.session._check_timeouts(2000.0)
        self.session._finalize.assert_not_awaited()
        self.session.segment_queue.get_nowait()
        self.session.segment_queue.task_done()
        await self.session._check_timeouts(2000.0)
        self.session._finalize.assert_awaited_once_with('failed', error='Max silence')


if __name__ == '__main__':
    unittest.main()
