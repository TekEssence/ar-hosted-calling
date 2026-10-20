# Claim prompt composition

Browser voice tests, text chats and phone calls use the same `compose_call_prompt`
function. The effective prompt always includes current account facts, Final Comments
as the Objective, prior Notes, the AR caller role, voice/privacy rules and the result
schema. Custom text is supplementary, lower-priority instructions, not a replacement.

## Excel and objective

`Final Comments` maps to `AR Final Comments`. Standard claim-status objectives use
the existing status workflows. Payment-related objectives mentioning clearance,
encashment, trace, EOB or pay-to address select a focused payment follow-up inquiry.
This selects the scope of questions, NOT the final claim status. Current outcomes
must still be confirmed by the representative.

An optional `Call Workflow` column can explicitly set `payment_follow_up` or
`claim_status` when the automatic text-based selection is inappropriate. Unknown
values fall back to objective-based selection. Inspect Show Current Context before
calling; objective-text detection is a heuristic, not proof that a payment exists.

For payment follow-up, ask whether the recorded payment cleared, obtain/confirm the
cleared date, mailing/pay-to address and EOB delivery details, then collect missing
confirmed payment information and a reference number. The competing initial paid-
claim checklist is omitted. A contradictory payer response must be double-checked
and handled through the applicable confirmed-status workflow.

A payer payment below billed charges is NOT automatically a denial. The bot must
reconcile contractual adjustments and patient responsibility; denied/pending
portions require their own confirmed status. Do not invent the balance breakdown.

## Custom instructions and legacy prompts

On the account page, LLM Context -> Add/Edit Instructions accepts concise additional
preferences. Show Current Context previews the actual composed system prompt. Fixed
rules/current facts take precedence over conflicting preferences.

Existing saved full prompts remain in Redis unchanged. When a copied prompt with
a real `[CLAIM CONTEXT]` section is detected, its frozen facts and generated
workflows are excluded. For recognized old AR templates, only a supplemental voice/
call-control section is retained. The UI displays a legacy-template notice. Reset
to Original removes only the custom preference entry; it does not remove claim data.

This is prompt-level instruction priority, not a security boundary or guaranteed
LLM compliance. Review unusual custom instructions and test representative scenarios.

## Conversation and output

One question per turn; confirm a newly spoken amount/date before another question.
Dates use full month name, day, year. No help-desk closing offers. Obtain a reference
number, thank the representative and finalize in a question-free turn. Unavailable
details need a truthful limitation/next action, not indefinite looping or guesses.

The existing CALL_RESULT schema is retained. Cleared date, address and EOB details
are captured in call_summary/next_action rather than new structured fields.

Changes take effect in subsequent calls. Start a fresh text chat/browser session
when testing changes so old conversation history does not influence the result.
Updating a custom preference does not rewrite a call already in progress.

## Tests

`python -m unittest discover -s tests -p 'test_*.py'` checks composition, refreshed
facts, legacy handling, dates and resolver parity without Redis/GPU/customer data.
`python3 validate-prompt-composition.py` on the VM makes three synthetic local LLM
requests; it does not write accounts or make phone calls. These smoke tests are not
a guarantee of all multi-turn behavior. Actual IVR/DTMF, transfers and Twilio calls
still need end-to-end testing.
