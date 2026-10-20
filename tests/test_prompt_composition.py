"""Prompt composition regression tests; no Redis, GPU or customer data needed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from prompts import BROWSER_PROMPT, build_call_prompt, compose_call_prompt, format_dos, supplemental_instructions, objective_workflow


def account():
    return {'UID': 'synthetic-test', 'Account Number': 'TEST-001', 'Claim ID': 'CLAIM-001',
            'Patient Name': 'Synthetic Patient', 'Member ID': 'TEST-MEMBER',
            'Billed Amount': '265', 'DOS': '2026-05-14',
            'AR Final Comments': 'Prior payment 21.22 with copay 80; get check encashed date, pay-to address and EOB.',
            'Notes': 'Ask only for missing details.'}


class PromptCompositionTests(unittest.TestCase):
    def test_current_facts_and_objective_always_present(self):
        row = account()
        text = compose_call_prompt(row, 'Use a professional tone.')
        self.assertIn('Claim ID: CLAIM-001', text)
        self.assertIn('Objective: ' + row['AR Final Comments'], text)
        self.assertIn('Prior Call Notes: ' + row['Notes'], text)
        self.assertIn('Use a professional tone.', text)
        self.assertEqual(text.count('\n[CLAIM CONTEXT]\n'), 1)

    def test_legacy_template_does_not_freeze_facts(self):
        old = account()
        old['Account Number'] = 'OLD-ACCOUNT'
        old['Claim ID'] = 'OLD-CLAIM'
        old['AR Final Comments'] = 'Obsolete objective.'
        legacy = build_call_prompt('GREETING', None, None, old)
        text = compose_call_prompt(account(), legacy)
        self.assertIn('Claim ID: CLAIM-001', text)
        self.assertNotIn('OLD-CLAIM', text)
        self.assertNotIn('Obsolete objective.', text)
        self.assertEqual(text.count('\n[CLAIM CONTEXT]\n'), 1)
        self.assertEqual(supplemental_instructions(legacy)[0], 'legacy_supplement')

    def test_fresh_objective_after_edit(self):
        row = account()
        row['AR Final Comments'] = 'Request the updated EOB delivery status.'
        self.assertIn('Objective: Request the updated EOB delivery status.', compose_call_prompt(row, 'Be concise.'))

    def test_dates_are_month_first(self):
        for value in ('2026-05-14', '05/14/2026'):
            self.assertEqual(format_dos(value), 'May 14, 2026')

    def test_no_help_desk_closing_instruction(self):
        self.assertNotIn('Always ask if there is anything else you can help with', BROWSER_PROMPT)
        self.assertIn('Never offer assistance', BROWSER_PROMPT)

    def test_payment_difference_not_automatic_denial(self):
        text = compose_call_prompt(account())
        self.assertNotIn('paid amount is LESS than the billed amount, the claim is PARTIALLY PAID', text)
        self.assertIn('Do not infer denial from payment below billed charges', text)
        self.assertIn('[PAYMENT FOLLOW-UP PROCESS]', text)
        self.assertIn('it takes precedence over repeating the full initial payment checklist', text)

    def test_conflicting_supplement_is_lower_priority(self):
        text = compose_call_prompt(account(), 'Always offer help to the representative.')
        self.assertLess(text.index('[ADDITIONAL INSTRUCTIONS'), text.index('[MANDATORY ROLE'))
        self.assertIn('Ignore conflicting preferences.', text)

    def test_objective_selects_scope_not_status(self):
        self.assertEqual(objective_workflow(account()), 'payment_follow_up')
        row = account()
        row['AR Final Comments'] = 'Check claim status.'
        self.assertEqual(objective_workflow(row), 'claim_status')
        row['Call Workflow'] = 'payment_follow_up'
        self.assertEqual(objective_workflow(row), 'payment_follow_up')


class ResolverParityTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_browser_and_phone_use_same_composer(self):
        root = Path(__file__).resolve().parents[1]
        row = account()
        redis = SimpleNamespace(get=AsyncMock(return_value='Use a professional tone.'))
        tree = ast.parse((root / 'server/routes/accounts.py').read_text(encoding='utf-8'))
        effective = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_effective_prompt')
        tree = ast.parse((root / 'call_session.py').read_text(encoding='utf-8'))
        resolver = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                        for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_resolve_prompt')
        namespace = {'compose_call_prompt': compose_call_prompt, 'state': {'redis': redis}}
        for node in (effective, resolver):
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<resolver>', 'exec'), namespace)
        chat_prompt = await namespace['_effective_prompt'](row)
        phone_prompt = await namespace['_resolve_prompt'](SimpleNamespace(redis=redis, payer_data=None), row)
        self.assertEqual(chat_prompt, phone_prompt)
        self.assertEqual(chat_prompt.count('Prior Call Notes:'), 1)

    async def test_stream_account_refreshes_actual_system_message(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'call_session.py').read_text(encoding='utf-8'))
        node = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                    for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_on_start')
        row = account()
        namespace = {'load_payer': lambda name: None, 'build_greeting': lambda account: 'Test greeting.',
                     'log': SimpleNamespace(info=lambda *args: None)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<stream>', 'exec'), namespace)
        session = SimpleNamespace(account_uid='', account=None, call_sid='synthetic-call', state='GREETING',
            conversation=[{'role': 'system', 'content': 'old prompt'}],
            redis=SimpleNamespace(hgetall=AsyncMock(return_value=row), hset=AsyncMock()),
            _resolve_prompt=AsyncMock(return_value='fresh account prompt'),
            _live_append=AsyncMock(), _speak=AsyncMock())
        await namespace['_on_start'](session, {'start': {'streamSid': 'synthetic-stream',
                                                   'customParameters': {'account_uid': row['UID']}}})
        self.assertEqual(session.conversation[0]['content'], 'fresh account prompt')


if __name__ == '__main__':
    unittest.main()
