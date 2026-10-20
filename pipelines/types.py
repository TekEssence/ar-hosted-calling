"""Transport-independent contracts; no model, server or storage dependencies.

Conversation mode is distinct from AR workflow progress. Changing mode during
a hold/transfer must not discard verified information or restart introductions.
These contracts do not execute actions or decide that a transition is safe.
"""
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Mapping


class CallMode(str, Enum):
    UNKNOWN = 'unknown'
    IVR = 'ivr'
    REPRESENTATIVE = 'representative'
    HOLD = 'hold'
    TRANSFER = 'transfer'


class WorkflowStage(str, Enum):
    VERIFY = 'verify'
    STATUS = 'status'
    PAYMENT = 'payment'
    DENIAL = 'denial'
    APPEAL = 'appeal'
    CLOSING = 'closing'


class FactSource(str, Enum):
    IVR = 'ivr'
    REPRESENTATIVE = 'representative'


@dataclass(frozen=True)
class ConfirmedFact:
    """A confirmed observation, not a fact inferred from pre-call records.

    turn_id links to the existing transcript; do not copy patient text into
    diagnostic reason strings. Arbitrary values must not appear in repr/logs.
    """
    value: Any = field(repr=False)
    source: FactSource
    turn_id: int

    def __post_init__(self):
        if not isinstance(self.source, FactSource):
            raise ValueError('source must be a FactSource')
        if type(self.turn_id) is not int or self.turn_id < 0:
            raise ValueError('turn_id must be a nonnegative integer')


@dataclass
class CallContext:
    """Per-call behavioral state, owned by CallSession, never shared globally.

    claim_data contains pre-call records, NOT confirmed current outcomes.
    Existing conversation/audio buffers stay in CallSession, not here.
    """
    call_id: str
    claim_data: Mapping[str, Any] = field(default_factory=dict, repr=False)
    mode: CallMode = CallMode.UNKNOWN
    workflow_stage: WorkflowStage = WorkflowStage.VERIFY
    confirmed_fields: dict[str, ConfirmedFact] = field(default_factory=dict, repr=False)
    introduction_completed: bool = False

    def __post_init__(self):
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError('call_id must be a nonempty string')
        if not isinstance(self.mode, CallMode):
            raise ValueError('mode must be a CallMode')
        if not isinstance(self.workflow_stage, WorkflowStage):
            raise ValueError('workflow_stage must be a WorkflowStage')
        # Snapshot input records without claiming that their contents were
        # confirmed on this call. Expected Redis claim values are scalar.
        self.claim_data = dict(self.claim_data)
        self.confirmed_fields = dict(self.confirmed_fields)


@dataclass(frozen=True)
class DetectionDecision:
    """Evidence for the orchestrator to evaluate, not an automatic mode switch.

    evidence contains signal codes (e.g. menu_structure), not raw transcripts.
    confidence is a classifier score, not a guarantee of human identification.
    """
    mode: CallMode
    confidence: float
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.mode, CallMode):
            raise ValueError('mode must be a CallMode')
        if (isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or not math.isfinite(self.confidence)
                or not 0 <= self.confidence <= 1):
            raise ValueError('confidence must be finite and between zero and one')
        if (not isinstance(self.evidence, tuple)
                or any(not isinstance(code, str)
                       or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', code)
                       for code in self.evidence)):
            raise ValueError('evidence must be a tuple of diagnostic signal codes')


@dataclass(frozen=True)
class WaitAction:
    """Listen without sending speech or tones; does not itself mean on hold."""


@dataclass(frozen=True)
class SpeakAction:
    text: str = field(repr=False)
    interruptible: bool = True

    def __post_init__(self):
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError('spoken text must be nonempty')
        if type(self.interruptible) is not bool:
            raise ValueError('interruptible must be a boolean')


@dataclass(frozen=True)
class DtmfAction:
    """Validated key sequence, not a WebSocket dtmf event.

    Transport, tone duration and inter-digit timing remain the orchestrator's
    responsibility. Pause directives are deliberately not mixed into digits.
    """
    digits: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.digits, str) or not re.fullmatch(r'[0-9*#]{1,32}', self.digits):
            raise ValueError('DTMF requires one to 32 keys from 0-9, * and #')


# One action per decision prevents simultaneously speaking and pressing keys.
# Completion will use the validated result contract when that stage is added.
PipelineAction = WaitAction | SpeakAction | DtmfAction
