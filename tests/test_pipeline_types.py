"""Pure contract tests using synthetic values only."""
from dataclasses import FrozenInstanceError
import unittest

from pipelines.types import (
    CallContext, CallMode, ConfirmedFact, DetectionDecision, DtmfAction,
    FactSource, SpeakAction, WaitAction, WorkflowStage,
)


class PipelineContractTests(unittest.TestCase):
    def test_new_call_is_uncertain_not_assumed_ivr(self):
        context = CallContext('synthetic-call')
        self.assertEqual(context.mode, CallMode.UNKNOWN)
        self.assertEqual(context.workflow_stage, WorkflowStage.VERIFY)
        self.assertEqual(context.confirmed_fields, {})

    def test_hold_and_transfer_preserve_workflow_and_confirmed_fields(self):
        fact = ConfirmedFact('TEST-REF', FactSource.REPRESENTATIVE, 4)
        context = CallContext('synthetic-call', mode=CallMode.REPRESENTATIVE,
                              workflow_stage=WorkflowStage.PAYMENT,
                              confirmed_fields={'reference_number': fact},
                              introduction_completed=True)
        for mode in (CallMode.HOLD, CallMode.TRANSFER, CallMode.REPRESENTATIVE):
            context.mode = mode
            self.assertEqual(context.workflow_stage, WorkflowStage.PAYMENT)
            self.assertIs(context.confirmed_fields['reference_number'], fact)
            self.assertTrue(context.introduction_completed)

    def test_calls_do_not_share_mutable_defaults(self):
        first, second = CallContext('first'), CallContext('second')
        first.confirmed_fields['reference'] = ConfirmedFact('TEST-REF', FactSource.IVR, 0)
        self.assertEqual(second.confirmed_fields, {})

    def test_pre_call_records_are_snapshotted_not_confirmed(self):
        records = {'Claim ID': 'TEST-001', 'Prior Status': 'paid'}
        context = CallContext('synthetic-call', claim_data=records)
        records['Claim ID'] = 'TEST-002'
        self.assertEqual(context.claim_data['Claim ID'], 'TEST-001')
        self.assertEqual(context.confirmed_fields, {})

    def test_invalid_context_is_rejected(self):
        for kwargs in ({'call_id': ''}, {'call_id': 'test', 'mode': 'ivr'},
                       {'call_id': 'test', 'workflow_stage': 'payment'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                CallContext(**kwargs)

    def test_detection_is_evidence_not_a_context_mutation(self):
        context = CallContext('synthetic-call')
        decision = DetectionDecision(CallMode.IVR, 0.9, ('menu_structure', 'keypad_request'))
        self.assertEqual(context.mode, CallMode.UNKNOWN)
        self.assertEqual(decision.mode, CallMode.IVR)

    def test_invalid_confidence_is_rejected(self):
        for confidence in (-0.1, 1.1, float('nan'), float('inf'), True, 'high'):
            with self.subTest(confidence=confidence), self.assertRaises(ValueError):
                DetectionDecision(CallMode.IVR, confidence)

    def test_evidence_uses_codes_not_transcript_text(self):
        for evidence in (['menu_structure'], ('Claim TEST-001 is paid',), ('',)):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                DetectionDecision(CallMode.IVR, 0.8, evidence)

    def test_wait_is_not_a_hold_transition(self):
        context = CallContext('synthetic-call')
        self.assertIsInstance(WaitAction(), WaitAction)
        self.assertEqual(context.mode, CallMode.UNKNOWN)

    def test_dtmf_supports_key_sequences_and_terminators(self):
        for digits in ('1', '1234567890#', '*0', '#'):
            self.assertEqual(DtmfAction(digits).digits, digits)

    def test_invalid_dtmf_is_rejected_before_transport(self):
        for digits in ('', '1w2', '1 2', '12A', '1\n', '1' * 33, None):
            with self.subTest(digits=digits), self.assertRaises(ValueError):
                DtmfAction(digits)

    def test_spoken_action_requires_nonempty_text(self):
        for text in ('', '  ', None):
            with self.subTest(text=text), self.assertRaises(ValueError):
                SpeakAction(text)
        self.assertTrue(SpeakAction('Synthetic response').interruptible)

    def test_actions_and_confirmed_facts_are_immutable(self):
        for obj, attr, value in ((DtmfAction('1'), 'digits', '2'),
                                 (SpeakAction('Synthetic'), 'text', 'Changed'),
                                 (ConfirmedFact('TEST', FactSource.IVR, 0), 'turn_id', 1)):
            with self.subTest(obj=type(obj).__name__), self.assertRaises(FrozenInstanceError):
                setattr(obj, attr, value)

    def test_confirmed_fact_requires_source_and_turn(self):
        for source, turn in (('ivr', 0), (FactSource.IVR, -1), (FactSource.IVR, True)):
            with self.subTest(source=source, turn=turn), self.assertRaises(ValueError):
                ConfirmedFact('TEST', source, turn)

    def test_sensitive_values_are_not_in_diagnostic_representations(self):
        synthetic = 'SYNTHETIC-PRIVATE-VALUE'
        values = (SpeakAction(synthetic), DtmfAction('1234567890#'),
                  ConfirmedFact(synthetic, FactSource.IVR, 0),
                  CallContext('synthetic-call', claim_data={'Claim ID': synthetic}))
        for value in values:
            self.assertNotIn(synthetic, repr(value))
            self.assertNotIn('1234567890#', repr(value))


if __name__ == '__main__':
    unittest.main()
