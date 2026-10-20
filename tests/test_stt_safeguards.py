"""Confidence gates with fake Whisper segments; no GPU or real call audio."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import numpy as np

from audio import transcribe_live


def segment(text, logprob=-0.2, no_speech=0.05, ratio=1.1):
    return SimpleNamespace(text=text, avg_logprob=logprob, no_speech_prob=no_speech,
                           compression_ratio=ratio)


class SttSafeguardsTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.sin(np.arange(16000, dtype=np.float32) * 0.1) * 0.02
        self.diagnostics = {}

    def transcribe(self, *segments):
        model = Mock()
        model.transcribe.return_value = (iter(segments), SimpleNamespace(duration_after_vad=0.8))
        return transcribe_live(model, self.audio, self.diagnostics)

    def test_noise_thank_you_is_not_forwarded(self):
        self.assertEqual(self.transcribe(segment('Thank you.', -0.8, 0.95)), '')
        self.assertEqual(self.diagnostics['status'], 'rejected')

    def test_genuine_thank_you_is_preserved(self):
        self.assertEqual(self.transcribe(segment('Thank you.')), 'Thank you.')
        self.assertEqual(self.diagnostics['status'], 'accepted')

    def test_short_replies_and_identifiers_are_preserved(self):
        for text in ('Yes', 'No', 'OK', '7', 'CO-11', '2026148EF7209', '$21.22', 'June 10, 2026'):
            with self.subTest(text=text):
                self.assertEqual(self.transcribe(segment(text)), text)

    def test_weak_speech_requests_clarification(self):
        self.assertEqual(self.transcribe(segment('claim number guessed', -1.3, 0.1)), '')
        self.assertEqual(self.diagnostics['status'], 'uncertain')

    def test_mixed_segments_do_not_forward_partial_details(self):
        self.assertEqual(self.transcribe(segment('The payment is'), segment('ninety', -1.3)), '')
        self.assertEqual(self.diagnostics['status'], 'uncertain')

    def test_silence_does_not_invoke_whisper(self):
        model = Mock()
        self.assertEqual(transcribe_live(model, np.zeros(16000, dtype=np.float32), self.diagnostics), '')
        model.transcribe.assert_not_called()

    def test_tiny_and_invalid_audio_are_rejected(self):
        for audio in (np.zeros(0), np.ones(100) * 0.1, np.array([np.nan, np.inf])):
            self.assertEqual(transcribe_live(Mock(), audio, self.diagnostics), '')
            self.assertEqual(self.diagnostics['status'], 'rejected')

    def test_diagnostics_do_not_store_candidate_text(self):
        self.transcribe(segment('Private patient detail', -1.3))
        self.assertNotIn('Private patient detail', str(self.diagnostics))
        self.assertIn('avg_logprob', self.diagnostics['segments'][0])

    def test_missing_confidence_does_not_invent_rejection(self):
        self.assertEqual(self.transcribe(SimpleNamespace(text='Yes')), 'Yes')


class ClarificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = (Path(__file__).resolve().parents[1] / 'call_session.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        method = next(n for cls in tree.body if isinstance(cls, ast.ClassDef) for n in cls.body
                       if isinstance(n, ast.AsyncFunctionDef) and n.name == '_process_segment')
        branch = next(n for n in method.body if isinstance(n, ast.If) and
                      isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not) and
                      isinstance(n.test.operand, ast.Name) and n.test.operand.id == 'text')
        reset = method.body[method.body.index(branch) + 1]
        wrapper = ast.parse('async def check(self, text):\n    pass').body[0]
        wrapper.body = [branch, reset]
        namespace = {}
        exec(compile(ast.Module(body=[wrapper], type_ignores=[]), '<clarification>', 'exec'), namespace)
        self.check = namespace['check']
        self.session = SimpleNamespace(last_stt_diagnostics={'status': 'uncertain'},
            conversation=[], _end_trace=Mock(), _live_append=AsyncMock(), _speak=AsyncMock())

    async def test_uncertain_speech_only_prompts_once(self):
        await self.check(self.session, '')
        await self.check(self.session, '')
        self.session._speak.assert_awaited_once_with('Could you repeat that last part?')
        self.assertEqual(len(self.session.conversation), 1)

    async def test_noise_never_prompts(self):
        self.session.last_stt_diagnostics['status'] = 'rejected'
        await self.check(self.session, '')
        self.session._speak.assert_not_awaited()

    async def test_short_answer_resets_pending_clarification(self):
        self.session.stt_clarification_pending = True
        await self.check(self.session, 'No')
        self.assertFalse(self.session.stt_clarification_pending)


if __name__ == '__main__':
    unittest.main()
