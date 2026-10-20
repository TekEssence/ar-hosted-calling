"""Conservative IVR decisions, without audio, LLM, Redis or Twilio side effects.

Only explicit menu choices and unambiguous verification requests are handled.
Unsupported wording deliberately yields WaitAction. The orchestrator/detector
must decide when to clarify, escalate, switch mode or end an unresolved call.
"""
import re
from typing import Mapping, Any

from .types import CallContext, CallMode, DtmfAction, PipelineAction, SpeakAction, WaitAction


_MENU = re.compile(
    r'\bpress\s+(?P<key>[0-9]|star|asterisk|pound|hash|\*|#)'
    r'\s+for\s+(?P<label>[^.;!?]+?)(?=\s*(?:,?\s*(?:and\s+)?press\b|[.;!?]|$))',
    re.IGNORECASE,
)
_FIELDS = (
    (r'\bclaim\s+(?:id|number)\b', ('Claim ID', 'claimId')),
    (r'\bmember\s+(?:id|number)\b', ('Member ID',)),
    (r'\b(?:date of birth|dob)\b', ('DOB',)),
    (r'\b(?:date of service|dos)\b', ('DOS', 'dos')),
    (r'\bgroup\s+npi\b', ('Group NPI',)),
    (r'\b(?:individual|provider)\s+npi\b', ('Individual NPI',)),
    (r'\b(?:tax\s+id|tin)\b', ('Tax ID',)),
)
_UNAVAILABLE = {'', 'unknown', 'n/a', 'none', 'null'}


class IvrHandler:
    def __init__(self, payer_data: Mapping[str, Any] | None = None, max_attempts: int = 2):
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError('max_attempts must be a positive integer')
        self.payer_data = payer_data or {}
        self.current_node = 'main'
        self.pending_node: Mapping[str, Any] | None = None
        self.max_attempts = max_attempts
        self._attempts: dict[tuple[str, str], int] = {}
        self.needs_review = False
        self.last_reason = 'listen'

    def _wait(self, reason: str, review: bool = False) -> WaitAction:
        self.last_reason = reason
        self.needs_review = review
        return WaitAction()

    def _bounded(self, prompt: str, action: PipelineAction) -> PipelineAction:
        key = (self.current_node, re.sub(r'\s+', ' ', prompt.strip().lower()))
        attempts = self._attempts.get(key, 0)
        if attempts >= self.max_attempts:
            return self._wait('retry_limit', review=True)
        self._attempts[key] = attempts + 1
        self.last_reason = 'explicit_menu' if isinstance(action, DtmfAction) else 'requested_value'
        return action

    def handle(self, transcript: str, context: CallContext) -> PipelineAction:
        """Return one proposed action; never change conversation mode or claim facts."""
        self.needs_review = False
        if context.mode != CallMode.IVR:
            return self._wait('inactive_mode')
        if not isinstance(transcript, str) or not transcript.strip():
            return self._wait('empty_prompt')
        text = transcript.strip()
        if re.search(r'\b(?:please hold|please wait|remain on the line|call is important)\b', text, re.I):
            return self._wait('hold_prompt')
        if re.search(r'\b(?:incorrect|invalid|not recognized|try again)\b', text, re.I):
            # Do not blindly replay identifiers after a rejection.
            self.pending_node = None
            return self._wait('rejected_input', review=True)

        if self.pending_node:
            verify = str(self.pending_node.get('verify_phrase', '')).strip()
            if verify and re.search(r'(?<!\w)' + re.escape(verify) + r'(?!\w)', text, re.I):
                self.current_node = str(self.pending_node.get('next', self.current_node))
                self.pending_node = None

        choices = list(_MENU.finditer(text))
        if choices:
            candidates = []
            # Match only a claims/status path that was actually announced.
            # A payer map is a hint for the current node, never permission to
            # send a digit absent from the live prompt.
            for match in choices:
                label = match['label'].strip(' ,').lower()
                if re.search(r'\b(?:claims?|claim status)\b', label) and not re.search(
                        r'\b(?:appeal|benefit|payment|eligibility)\b', label):
                    key = {'star': '*', 'asterisk': '*', 'pound': '#', 'hash': '#'}.get(
                        match['key'].lower(), match['key'])
                    candidates.append(key)
            if len(candidates) != 1:
                return self._wait('ambiguous_menu', review=True)
            action = self._bounded(text, DtmfAction(candidates[0]))
            if isinstance(action, DtmfAction):
                nodes = self.payer_data.get('ivr_tree', {}).get(self.current_node, [])
                matches = [node for node in nodes if node.get('dtmf') == action.digits]
                self.pending_node = matches[0] if len(matches) == 1 else None
            return action

        if not re.search(r'\b(?:enter|say|provide|tell me)\b', text, re.I):
            return self._wait('unsupported_prompt')
        fields = [keys for pattern, keys in _FIELDS if re.search(pattern, text, re.I)]
        if len(fields) != 1:
            return self._wait('ambiguous_verification', review=True)
        value = next((str(context.claim_data[key]).strip() for key in fields[0]
                      if context.claim_data.get(key) is not None
                      and str(context.claim_data[key]).strip().lower() not in _UNAVAILABLE), '')
        if not value:
            return self._wait('missing_context', review=True)
        keypad = bool(re.search(r'\b(?:enter|keypad|key in)\b', text, re.I))
        spoken = bool(re.search(r'\b(?:say|speak)\b', text, re.I))
        if keypad and spoken:
            return self._wait('ambiguous_input_mode', review=True)
        if keypad:
            # Do not convert dates or alphanumeric IDs into guessed keypad
            # formats. They need an explicit field-format policy first.
            if not re.fullmatch(r'[0-9]{1,31}', value):
                return self._wait('unsupported_keypad_value', review=True)
            length = re.search(r'\b(\d{1,2})[ -]digit\b', text, re.I)
            if length and len(value) != int(length[1]):
                return self._wait('identifier_length_mismatch', review=True)
            if re.search(r'\b(?:followed by|then press)\s+(?:the\s+)?(?:pound|hash|#)', text, re.I):
                value += '#'
            return self._bounded(text, DtmfAction(value))
        if not spoken:
            return self._wait('unspecified_input_mode', review=True)
        return self._bounded(text, SpeakAction(value))
