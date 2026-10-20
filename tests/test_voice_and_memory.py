"""Voice normalization/cache and conversation-memory tests without GPU models."""
import ast
import asyncio
from collections import OrderedDict
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import os

from prompts import conversation_messages, repeated_answered_question, avoid_repeated_question


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def conversation(self):
        turns = [{'role': 'system', 'content': 'AR rules'},
                 {'role': 'assistant', 'content': 'What date did the check clear?'},
                 {'role': 'user', 'content': 'June 10, 2026.'}]
        for i in range(10):
            turns.extend([{'role': 'assistant', 'content': f'Other question {i}?'},
                          {'role': 'user', 'content': f'Other answer {i}.'}])
        return turns

    def test_earlier_answer_not_lost(self):
        messages = conversation_messages(self.conversation())
        self.assertIn('June 10, 2026.', messages[0]['content'])
        self.assertLessEqual(len(messages), 15)

    def test_repeat_detected_but_new_question_allowed(self):
        self.assertTrue(repeated_answered_question('What date did the check clear?', self.conversation()))
        self.assertFalse(repeated_answered_question('Where was the check mailed?', self.conversation()))

    def test_unavailable_answer_is_not_treated_as_confirmed(self):
        turns = [{'role': 'assistant', 'content': 'What date did the check clear?'},
                 {'role': 'user', 'content': "I don't know; let me check."}]
        self.assertFalse(repeated_answered_question('What date did the check clear?', turns))

    def test_polite_acknowledgment_is_not_a_claim_answer(self):
        for answer in ('Thank you.', '[INSURANCE REP] [STATE: APPROVED_HANDLE] Yes.', 'One moment.'):
            turns = [{'role': 'assistant', 'content': 'What date did the check clear?'},
                     {'role': 'user', 'content': answer}]
            self.assertFalse(repeated_answered_question('What date did the check clear?', turns))

    async def test_one_retry_before_speaking_duplicate(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(
            return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Where was the check mailed?'))])))))
        turns = self.conversation()
        reply = await avoid_repeated_question(client, 'test', conversation_messages(turns),
                                              'What date did the check clear?', turns)
        self.assertEqual(reply, 'Where was the check mailed?')
        client.chat.completions.create.assert_awaited_once()


class ChunkTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'server/tts_plain.py').read_text(encoding='utf-8'))
        names = {'_split_plain_chunks', '_format_digits', '_format_money', '_number_to_words', '_say_two'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.ns = {'re': re, '_DIGIT_WORDS': dict(zip('0123456789', 'zero one two three four five six seven eight nine'.split()))}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<voice>', 'exec'), self.ns)

    def test_long_first_clause_is_split_without_losing_words(self):
        text = 'Please verify the mailing address and the suite number for the payment before sending the explanation of benefits.'
        chunks = self.ns['_split_plain_chunks'](text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 70 for chunk in chunks))
        self.assertEqual(' '.join(chunks), text)

    def test_identifiers_group_without_changing_digits(self):
        match = re.match(r'\d+', '1063593739')
        self.assertEqual(self.ns['_format_digits'](match), 'one zero six three, five nine three seven, three nine')

    def test_decimal_currency_is_not_misread(self):
        match = re.match(r'\$(\d+)(\.\d{1,2})?', '$21.5')
        self.assertEqual(self.ns['_format_money'](match), 'twenty-one dollars and fifty cents')


class VoiceCacheTests(unittest.TestCase):
    def test_same_reference_is_encoded_once(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'chatterbox_service/app.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_prepare_voice')
        model = SimpleNamespace(conds=object(), prepare_conditionals=Mock())
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'synthetic.wav').write_bytes(b'not audio; only filesystem metadata is tested')
            ns = {'os': os, 'VOICES_DIR': folder, '_model': model, '_voice_conditions': OrderedDict(),
                  '_default_conditions': object(), 'HTTPException': RuntimeError}
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<cache>', 'exec'), ns)
            self.assertFalse(ns['_prepare_voice']('synthetic', 0.5))
            self.assertTrue(ns['_prepare_voice']('synthetic', 0.5))
            model.prepare_conditionals.assert_called_once()


class SynthesisSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_request_does_not_release_model_while_worker_runs(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'chatterbox_service/app.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_serialized_request')
        lock = asyncio.Lock()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def fake_worker(function, req, text):
            calls.append(req)
            if req == 'first':
                started.set()
                await release.wait()
            return {'ok': True}

        ns = {'asyncio': asyncio, '_generation_lock': lock, '_generate': lambda *args: None, 'TTSRequest': object}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<serialized>', 'exec'), ns)
        with patch('asyncio.to_thread', fake_worker):
            first = asyncio.create_task(ns['_serialized_request']('first', 'test'))
            await asyncio.wait_for(started.wait(), 1)
            first.cancel()
            second = asyncio.create_task(ns['_serialized_request']('second', 'test'))
            await asyncio.sleep(0)
            self.assertTrue(lock.locked())
            self.assertEqual(calls, ['first'])
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertEqual(await asyncio.wait_for(second, 1), {'ok': True})
