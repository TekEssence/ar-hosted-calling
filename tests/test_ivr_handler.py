"""IVR proposals only: synthetic claim data, no telephony or inference."""
import unittest

from pipelines.ivr_handler import IvrHandler
from pipelines.types import CallContext, CallMode, DtmfAction, SpeakAction, WaitAction


class IvrHandlerTests(unittest.TestCase):
    def setUp(self):
        self.context = CallContext('synthetic-call', mode=CallMode.IVR, claim_data={
            'Claim ID': '123456', 'Member ID': 'TEST-M001', 'DOB': 'January 2, 2000',
            'Individual NPI': '1234567890',
        })
        self.handler = IvrHandler()

    def test_explicit_claims_menu(self):
        action = self.handler.handle('Press 1 for benefits. Press 2 for claims.', self.context)
        self.assertEqual(action, DtmfAction('2'))

    def test_comma_separated_menu(self):
        action = self.handler.handle('Press 1 for claims, press 2 for benefits.', self.context)
        self.assertEqual(action, DtmfAction('1'))

    def test_ambiguous_menu_does_not_choose(self):
        action = self.handler.handle('Press 1 for dental claims. Press 2 for medical claims.', self.context)
        self.assertIsInstance(action, WaitAction)
        self.assertTrue(self.handler.needs_review)

    def test_hold_is_silent_and_does_not_switch_mode(self):
        self.assertIsInstance(self.handler.handle('Please hold for a representative.', self.context), WaitAction)
        self.assertEqual(self.context.mode, CallMode.IVR)

    def test_representative_mode_cannot_send_menu_keys(self):
        self.context.mode = CallMode.REPRESENTATIVE
        self.assertIsInstance(self.handler.handle('Press 1 for claims.', self.context), WaitAction)

    def test_speech_verification_uses_exact_context(self):
        for prompt, value in (('Say your member ID.', 'TEST-M001'),
                              ('Say the date of birth.', 'January 2, 2000')):
            self.assertEqual(self.handler.handle(prompt, self.context), SpeakAction(value))
        self.assertEqual(self.context.confirmed_fields, {})

    def test_numeric_entry_and_terminator(self):
        action = self.handler.handle('Enter your 6 digit claim number followed by pound.', self.context)
        self.assertEqual(action, DtmfAction('123456#'))

    def test_provider_npi_entry(self):
        self.assertEqual(self.handler.handle('Enter your 10-digit provider NPI.', self.context),
                         DtmfAction('1234567890'))

    def test_missing_field_is_not_invented(self):
        self.assertIsInstance(self.handler.handle('Say your tax ID.', self.context), WaitAction)
        self.assertEqual(self.handler.last_reason, 'missing_context')

    def test_multiple_requested_fields_are_not_guessed(self):
        self.assertIsInstance(self.handler.handle('Say member ID and date of birth.', self.context), WaitAction)
        self.assertEqual(self.handler.last_reason, 'ambiguous_verification')

    def test_alphanumeric_keypad_value_requires_a_format_policy(self):
        self.assertIsInstance(self.handler.handle('Enter your member ID.', self.context), WaitAction)
        self.assertEqual(self.handler.last_reason, 'unsupported_keypad_value')

    def test_length_mismatch_is_not_corrected_by_guessing(self):
        self.assertIsInstance(self.handler.handle('Enter your 8 digit claim number.', self.context), WaitAction)
        self.assertEqual(self.handler.last_reason, 'identifier_length_mismatch')

    def test_rejected_input_requires_review(self):
        self.assertIsInstance(self.handler.handle('Invalid claim number, try again.', self.context), WaitAction)
        self.assertTrue(self.handler.needs_review)

    def test_repeated_menu_is_bounded(self):
        prompt = 'Press 1 for claims.'
        for _ in range(2):
            self.assertEqual(self.handler.handle(prompt, self.context), DtmfAction('1'))
        self.assertIsInstance(self.handler.handle(prompt, self.context), WaitAction)
        self.assertEqual(self.handler.last_reason, 'retry_limit')

    def test_nested_node_advances_only_after_expected_evidence(self):
        handler = IvrHandler({'ivr_tree': {'main': [
            {'dtmf': '1', 'next': 'claims', 'verify_phrase': 'claims department'}]}})
        handler.handle('Press 1 for claims.', self.context)
        self.assertEqual(handler.current_node, 'main')
        handler.handle('Welcome to the claims department. Say your member ID.', self.context)
        self.assertEqual(handler.current_node, 'claims')
        self.assertIsNone(handler.pending_node)

    def test_unknown_prompt_is_silent(self):
        for prompt in ('', 'This call may be recorded.', 'What is your secret password?'):
            self.assertIsInstance(self.handler.handle(prompt, self.context), WaitAction)


if __name__ == '__main__':
    unittest.main()
