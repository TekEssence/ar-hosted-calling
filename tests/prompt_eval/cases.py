"""Test-case fixtures: one per branch of the 3 workflow docs.

Each case has:
  - account: claim context dict fed into build_call_prompt
  - script: ordered FIFO list of canned rep answers for sequential factual
    asks (dates, amounts, addresses) -- popped one per agent turn once no
    keyword_answers entry matches
  - keyword_answers: list of {"pattern": regex, "answer": str} -- checked
    BEFORE the FIFO queue on every turn, so branch-determining yes/no
    questions get routed correctly regardless of exact turn order/wording.
    Each entry fires once.
  - required: regex patterns that must each match somewhere across the
    assistant's turns (i.e. the agent asked about / covered that topic)
  - expected_status: the "status" value CALL_RESULT must end up with
  - fallback: answer used once keyword_answers + script are both exhausted
"""

BASE_ACCOUNT = {
    "Patient Name": "John Doe",
    "Member ID": "M998877",
    "DOB": "1980-01-15",
    "DOS": "2026-05-01",
    "CPT": "99214",
    "Billed Amount": "450",
    "Responsible Payer": "Aetna",
    "Account Number": "ACC-778899",
    "Claim ID": "ACC-778899",
    "Group Name": "Test Medical Group",
    "Group NPI": "1234567890",
    "Tax ID": "00-1234567",
    "Billing/Provider Address": "123 Main St, Springfield",
    "Pay-to-address": "123 Main St, Springfield",
    "Individual NPI": "1112223334",
}


def acct(objective, **overrides):
    a = dict(BASE_ACCOUNT)
    a["AR Final Comments"] = objective
    a.update(overrides)
    return a


DEFAULT_FALLBACK = "That's all the information I have. Anything else you need?"

# BASE_PROMPT rule 2 makes the agent open with "is it paid, denied, or
# pending" on essentially every call, regardless of scenario -- route it
# explicitly so the rest of each case's script isn't consumed answering it.
STATUS_Q = r"paid.{0,25}denied.{0,25}pending|is it paid\b|current status of (the|this) claim\b"


def with_status_route(first_answer, keyword_answers):
    return [{"pattern": STATUS_Q, "answer": first_answer}] + keyword_answers

CASES = [
    # ── Claim In-Process ──────────────────────────────────────────────
    {
        "name": "claim_in_process_within_timeframe",
        "doc": "Claim In-Process",
        "account": acct("Check claim status"),
        "keyword_answers": with_status_route(
            "The claim is in process, it's currently under review.",
            [
                {"pattern": r"under review|currently.*process|process.*stage|received.*process",
                 "answer": "The claim is in process, it's currently under review."},
                {"pattern": r"exceed|within.*timefram|still within",
                 "answer": "No, it's still within the standard processing timeframe."},
            ],
        ),
        "script": [
            "We received the claim on July 1st, 2026.",
            "Our standard processing timeframe is 30 business days.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"under review|in process|processing stage",
                     r"received", r"processing timefram|turnaround|how long"],
        "expected_status": "pending",
    },
    {
        "name": "claim_in_process_exceeded_timeframe_escalation",
        "doc": "Claim In-Process",
        "account": acct("Check claim status"),
        "keyword_answers": with_status_route(
            "The claim is in process, currently under review.",
            [
                {"pattern": r"under review|currently.*process|process.*stage|received.*process",
                 "answer": "The claim is in process, currently under review."},
                {"pattern": r"exceed|within.*timefram",
                 "answer": "Yes, it has exceeded the standard processing timeframe."},
                {"pattern": r"escalat",
                 "answer": "Yes, I can escalate this for priority processing. The escalation reference number is ESC-4471, expected turnaround after escalation is 5 business days."},
            ],
        ),
        "script": [
            "It was received on January 5th, 2026.",
            "Standard processing time is 30 business days.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"received", r"processing timefram|turnaround time|how long",
                     r"escalat", r"escalation reference|reference number|case number"],
        "expected_status": "pending",
    },
    {
        "name": "claim_pending_additional_info_medical_records",
        "doc": "Claim In-Process",
        "account": acct("Check claim status"),
        "keyword_answers": with_status_route(
            "The claim is pending, we need additional information.",
            [
                {"pattern": r"under review|currently.*process|process.*stage|received.*process|pending.*information",
                 "answer": "The claim is pending, we need additional information."},
            ],
        ),
        "script": [
            "We need medical records for this date of service.",
            "Please fax the records to 555-201-9988.",
            "The timely filing limit to submit is August 30th, 2026.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"pending|additional information|what.*need|what.*document",
                     r"medical record|clinical documentation|corrected claim|authorization|coordination of benefits|cob",
                     r"fax|mail|portal|email|submission method",
                     r"timely filing|due date|deadline"],
        "expected_status": "pending",
    },

    # ── Appeal In-Process ────────────────────────────────────────────
    {
        "name": "appeal_received_in_process_within_timeframe",
        "doc": "Appeal In-Process",
        "account": acct("Follow up on appeal submitted 06/01/2026 via fax to 555-100-2000",
                         **{"Notes": "Appeal submitted 06/01/2026 by fax to 555-100-2000"}),
        "keyword_answers": with_status_route(
            "This is a follow-up on an appeal we already submitted. Let me pull that up.",
            [
                {"pattern": r"receive.*appeal|appeal.*receive|was.*appeal.*receiv",
                 "answer": "Yes, we received the appeal."},
                {"pattern": r"exceed|within.*timefram",
                 "answer": "No, it's still within the standard 45 calendar day timeframe."},
            ],
        ),
        "script": [
            "It was received on June 3rd, 2026.",
            "The DCN is DCN-55231.",
            "The appeal is currently in process.",
            "Standard appeal processing timeframe is 45 calendar days.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"receive.*appeal|appeal.*receiv", r"dcn|document control number|case number",
                     r"current.*status|appeal status|in process|completed",
                     r"processing timefram|how long|turnaround"],
        "expected_status": "pending",
    },
    {
        "name": "appeal_in_process_exceeded_timeframe_escalation",
        "doc": "Appeal In-Process",
        "account": acct("Follow up on appeal", **{"Notes": "Appeal submitted 01/01/2026 by mail"}),
        "keyword_answers": with_status_route(
            "This is a follow-up on an appeal we already submitted. Let me pull that up.",
            [
                {"pattern": r"receive.*appeal|appeal.*receive|was.*appeal.*receiv",
                 "answer": "Yes, we received the appeal."},
                {"pattern": r"exceed|within.*timefram",
                 "answer": "Yes, it has exceeded the standard processing timeframe."},
                {"pattern": r"escalat",
                 "answer": "Yes, I'll escalate it for priority processing. Escalation case number is ESC-3301, expected turnaround after escalation is 10 business days."},
            ],
        ),
        "script": [
            "It was received January 3rd, 2026.",
            "The case number is CASE-9091.",
            "It's still in process.",
            "Standard timeframe is 45 calendar days.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"escalat", r"escalation reference|escalation case|reference number|case number"],
        "expected_status": "pending",
    },
    {
        "name": "appeal_completed_denied",
        "doc": "Appeal In-Process",
        "account": acct("Follow up on appeal", **{"Notes": "Appeal submitted 05/01/2026 via portal"}),
        "keyword_answers": with_status_route(
            "This is a follow-up on an appeal we already submitted. Let me pull that up.",
            [
                {"pattern": r"receive.*appeal|appeal.*receive|was.*appeal.*receiv|pending or.*decision|decision.*been made",
                 "answer": "Yes, we received the appeal, on May 3rd, 2026."},
                {"pattern": r"dcn|document control number|case number",
                 "answer": "The DCN is DCN-77120."},
                {"pattern": r"in process|completed|current.*status|appeal status",
                 "answer": "The appeal has been completed."},
                {"pattern": r"outcome|determination|approved.{0,10}denied.{0,10}partially",
                 "answer": "The determination was Denied, upheld original decision."},
                {"pattern": r"completion date|when.{0,10}complet|complet.{0,10}date",
                 "answer": "It was completed on June 15th, 2026."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"completion date|when.*complet|completed", r"determination|outcome|approved|denied|partially approved"],
        "expected_status": "denied",
    },
    {
        "name": "appeal_not_received_wrong_address",
        "doc": "Appeal In-Process",
        "account": acct("Follow up on appeal", **{"Notes": "Appeal submitted 07/01/2026 by fax to 555-777-0000"}),
        "keyword_answers": with_status_route(
            "This is a follow-up on an appeal we already submitted. Let me pull that up.",
            [
                {"pattern": r"receive.*appeal|appeal.*receive|was.*appeal.*receiv|pending or.*decision|decision.*been made|submission date and.*mailing address|submission date and.*fax",
                 "answer": "No, we don't show any appeal received. The submission date was July 1st, 2026 and it was sent by fax to 555-777-0000."},
                {"pattern": r"correct destination|correct fax|correct address|verify.*sent|sent to the correct|current status of the claim",
                 "answer": "That fax number is incorrect, our correct fax is 555-777-9999."},
                {"pattern": r"resubmit",
                 "answer": "Yes, the appeal will need to be resubmitted to the correct fax."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"correct destination|correct fax|correct address|verify.*sent|sent to the correct|incorrect",
                     r"resubmit"],
        "expected_status": "pending",
    },

    # ── Non-Covered Charges ──────────────────────────────────────────
    {
        "name": "non_covered_diagnosis_exclusion",
        "doc": "Non-Covered",
        "account": acct("Check denial reason", **{"Denial Code": "CO-167"}),
        "keyword_answers": with_status_route(
            "It's denied, it's a non-covered charge.",
            [
                {"pattern": r"benefit plan|provider contract|network agreement",
                 "answer": "This is non-covered under the patient's benefit plan."},
                {"pattern": r"diagnosis|plan.specific exclusion",
                 "answer": "It's related to the diagnosis, it's not covered."},
            ],
        ),
        "script": [
            "The denial code is CO-167.",
            "The diagnosis code causing the issue is Z71.3.",
            "Corrected claims go to PO Box 4400, Hartford CT, fax 555-333-2211, payer ID 60054, timely limit is 90 days from denial.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"denial code|remark code", r"diagnosis|not covered",
                     r"mailing address|payer id|timely|fax"],
        "expected_status": "denied",
    },
    {
        "name": "non_covered_plan_specific_exclusion",
        "doc": "Non-Covered",
        "account": acct("Check denial reason", **{"Denial Code": "CO-96"}),
        "keyword_answers": with_status_route(
            "It's denied, it's a non-covered charge.",
            [
                {"pattern": r"benefit plan|provider contract|network agreement",
                 "answer": "This is non-covered under the patient's benefit plan."},
                {"pattern": r"diagnosis|plan.specific exclusion",
                 "answer": "It's a plan-specific exclusion, not diagnosis-related."},
                {"pattern": r"allowed amount",
                 "answer": "There is no allowed amount for this service."},
                {"pattern": r"bill.*patient|patient.*bill",
                 "answer": "Yes, this can be billed to the patient."},
            ],
        ),
        "script": [
            "Denial code is CO-96.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"plan.specific exclusion|exclusion", r"allowed amount", r"bill.*patient|patient.*bill"],
        "expected_status": "denied",
    },
    {
        "name": "non_covered_cpt_provider_contract_resubmit",
        "doc": "Non-Covered",
        "account": acct("Check denial reason", **{"Denial Code": "CO-50"}),
        "keyword_answers": with_status_route(
            "It's denied, it's a non-covered charge under the provider contract.",
            [
                {"pattern": r"benefit plan|provider contract|network agreement",
                 "answer": "This is non-covered under the provider's contract."},
                {"pattern": r"resubmit.*corrected code|resubmit.*new code|can.*resubmit",
                 "answer": "Yes, you can resubmit this as a corrected code."},
            ],
        ),
        "script": [
            "Denial code is CO-50.",
            "The CPT code causing the issue is 99499.",
            "Corrected claims go to PO Box 1200, Chicago IL, fax 555-444-1122, payer ID 60054, timely limit 120 days.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"cpt code", r"resubmit|corrected code|new.{0,4}code", r"mailing address|fax|payer id|timely"],
        "expected_status": "denied",
    },
    {
        "name": "non_covered_oon_with_benefits_reprocess",
        "doc": "Non-Covered",
        "account": acct("Check denial reason", **{"Denial Code": "CO-109"}),
        "keyword_answers": with_status_route(
            "It's denied, the provider is out of network.",
            [
                {"pattern": r"benefit plan|provider contract|network agreement",
                 "answer": "This is non-covered because the provider is out of network."},
                {"pattern": r"out.of.network benefit",
                 "answer": "Yes, the plan does cover out-of-network benefits."},
                {"pattern": r"send.*back.*reprocess|reprocess",
                 "answer": "Yes, I can send the claim back for reprocessing."},
            ],
        ),
        "script": [
            "Denial code is CO-109.",
            "The patient has a PPO plan.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"out.of.network|network", r"plan type|ppo|hmo", r"out.of.network benefit",
                     r"send.*back.*reprocess|reprocess"],
        "expected_status": "pending",
    },
    {
        "name": "non_covered_oon_no_benefits_appeal",
        "doc": "Non-Covered",
        "account": acct("Check denial reason", **{"Denial Code": "CO-109"}),
        "keyword_answers": with_status_route(
            "It's denied, the provider is out of network.",
            [
                {"pattern": r"benefit plan|provider contract|network agreement",
                 "answer": "This is non-covered because the provider is out of network."},
                {"pattern": r"denial (reason )?code|remark code",
                 "answer": "The denial code is CO-109."},
                {"pattern": r"plan type|ppo|hmo|what.{0,10}plan",
                 "answer": "The patient has an HMO plan."},
                {"pattern": r"out.of.network benefit|specific reason.{0,20}(doesn.t|does not) cover|cover this service",
                 "answer": "No, this plan does not cover out-of-network benefits — I confirmed it directly, that's not an assumption based on plan type."},
                {"pattern": r"appeal.*mailing address|appeal.*fax|appeal.*address|payer id|claims submission address",
                 "answer": "Appeals go to PO Box 900, Denver CO, fax 555-222-3344."},
                {"pattern": r"filing limit|turnaround",
                 "answer": "The appeal filing limit is 60 days."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"out.of.network benefit|cover.{0,15}(service|out.of.network)", r"appeal.*mailing address|appeal.*fax|appeal.*address",
                     r"appeal filing limit|filing limit"],
        "expected_status": "denied",
    },

    # ── Paid Claim Verification (pre-existing workflow) ───────────────
    # Fully keyword-routed (no FIFO): with this many sequential fields, the
    # model's exact question order varies run to run, so a positional script
    # produced false failures (rep answering the wrong question) even when
    # the agent's behavior was correct. See README's "Adding a new test case".
    {
        "name": "paid_fully_eft",
        "doc": "Paid Claim Verification",
        "account": acct("Confirm payment", **{"Billed Amount": "450"}),
        "keyword_answers": with_status_route(
            "Yes, this claim was paid in full.",
            [
                {"pattern": r"cpt code", "answer": "The CPT code is 99214."},
                {"pattern": r"paid amount|how much.{0,15}paid|what.{0,15}(was|is).{0,10}paid(?!.{0,10}method)",
                 "answer": "The paid amount was $450."},
                {"pattern": r"allowed amount", "answer": "The allowed amount is $450."},
                {"pattern": r"contractual adjustment", "answer": "There was no contractual adjustment."},
                {"pattern": r"patient responsib", "answer": "There's no patient responsibility on this one."},
                {"pattern": r"payment method|check or eft|check,? eft,? or vcc|paid by (check|eft|vcc)",
                 "answer": "It was paid by EFT."},
                {"pattern": r"eft number|eft.{0,10}reference", "answer": "The EFT number is EFT-88221."},
                {"pattern": r"eft date", "answer": "The EFT date was July 10th, 2026."},
                {"pattern": r"eft amount", "answer": "The EFT amount was $450."},
                {"pattern": r"eob", "answer": "You can get the EOB copy by fax at 555-909-1122."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"paid amount", r"cpt code", r"allowed amount",
                     r"contractual adjustment", r"patient responsib",
                     r"payment method|check or eft|paid by",
                     r"eft number|eft.{0,10}reference", r"eft date", r"eob"],
        "expected_status": "paid",
    },
    {
        "name": "paid_fully_check_cashed",
        "doc": "Paid Claim Verification",
        "account": acct("Confirm payment", **{"Billed Amount": "450"}),
        "keyword_answers": with_status_route(
            "Yes, this claim was paid in full.",
            [
                {"pattern": r"cpt code", "answer": "The CPT code is 99214."},
                {"pattern": r"paid amount|how much.{0,15}paid|what.{0,15}(was|is).{0,10}paid(?!.{0,10}method)",
                 "answer": "The paid amount was $450."},
                {"pattern": r"allowed amount", "answer": "The allowed amount is $450."},
                {"pattern": r"contractual adjustment", "answer": "There was no contractual adjustment."},
                {"pattern": r"patient responsib", "answer": "There's no patient responsibility on this one."},
                {"pattern": r"payment method|check or eft|check,? eft,? or vcc|paid by (check|eft|vcc)",
                 "answer": "It was paid by check."},
                {"pattern": r"check number", "answer": "The check number is CHK-33110."},
                {"pattern": r"check.{0,15}(issue|issued)|when.{0,10}(was|check).{0,10}issued",
                 "answer": "The check was issued June 20th, 2026."},
                {"pattern": r"check amount", "answer": "The check amount was $450."},
                {"pattern": r"mailing address|where.{0,10}(was|check).{0,10}(sent|mailed)",
                 "answer": "It was mailed to 123 Main St, Springfield."},
                {"pattern": r"cashed|encashed", "answer": "Yes, the check has been cashed."},
                {"pattern": r"clear.{0,10}date|encashed date|when.{0,10}clear",
                 "answer": "It cleared on June 28th, 2026."},
                {"pattern": r"eob", "answer": "You can get the EOB copy by fax at 555-909-1122."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"paid amount", r"cpt code", r"allowed amount",
                     r"payment method|check or eft|paid by",
                     r"check number", r"check.{0,15}(issue|issued)", r"mailing address|mailed to|sent to",
                     r"cashed|encashed", r"clear.{0,10}date|encashed date"],
        "expected_status": "paid",
    },
    {
        "name": "paid_partially_denied_remainder",
        "doc": "Paid Claim Verification",
        "account": acct("Confirm payment", **{"Billed Amount": "500"}),
        "keyword_answers": with_status_route(
            "It was partially paid — $300 of the $500 billed.",
            [
                {"pattern": r"paid amount|how much.{0,15}paid|what.{0,15}(was|is).{0,10}paid(?!.{0,10}method)",
                 "answer": "$300 was paid."},
                {"pattern": r"remaining.{0,15}(denied|pending)|rest.{0,15}(denied|pending)|unpaid.{0,15}(denied|pending)|denied or.{0,10}pending",
                 "answer": "The remaining $200 was denied."},
                {"pattern": r"cpt code.{0,20}denied|denied.{0,20}cpt code",
                 "answer": "The CPT code for the denied portion is 99215."},
                {"pattern": r"denial (reason )?code|remark code|rarc",
                 "answer": "The remark code is CO-45."},
                {"pattern": r"denial description|reason for the denial",
                 "answer": "The denial description is charge exceeds fee schedule."},
                {"pattern": r"cpt code", "answer": "The CPT code for the paid portion is 99214."},
                {"pattern": r"allowed amount", "answer": "The allowed amount is $300."},
                {"pattern": r"contractual adjustment", "answer": "There was a $0 contractual adjustment."},
                {"pattern": r"patient responsib", "answer": "No patient responsibility on this one."},
                {"pattern": r"payment method|check or eft|check,? eft,? or vcc|paid by (check|eft|vcc)",
                 "answer": "The $300 was paid by EFT."},
                {"pattern": r"eft number|eft.{0,10}reference", "answer": "The EFT number is EFT-77332."},
                {"pattern": r"eft date", "answer": "The EFT date was July 15th, 2026."},
                {"pattern": r"eft amount", "answer": "The EFT amount was $300."},
                {"pattern": r"eob", "answer": "EOB copy is available by fax at 555-909-1122."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"paid amount", r"cpt code", r"remark code|rarc|denial reason",
                     r"denial description", r"allowed amount"],
        "expected_status": "denied",
    },
    {
        "name": "paid_vcc_expired_reissue",
        "doc": "Paid Claim Verification",
        "account": acct("Confirm payment", **{"Billed Amount": "450"}),
        "keyword_answers": with_status_route(
            "Yes, this claim was paid in full.",
            [
                {"pattern": r"cpt code", "answer": "The CPT code is 99214."},
                {"pattern": r"paid amount|how much.{0,15}paid|what.{0,15}(was|is).{0,10}paid(?!.{0,10}method)",
                 "answer": "The paid amount was $450."},
                {"pattern": r"allowed amount", "answer": "The allowed amount is $450."},
                {"pattern": r"contractual adjustment", "answer": "No contractual adjustment."},
                {"pattern": r"patient responsib", "answer": "No patient responsibility."},
                {"pattern": r"payment method|check or eft|check,? eft,? or vcc|paid by (check|eft|vcc)",
                 "answer": "It was paid by VCC, virtual credit card."},
                {"pattern": r"vcc.{0,20}(number|reference|draft)", "answer": "The VCC reference number is VCC-55210."},
                {"pattern": r"card.{0,10}issue|issue date", "answer": "The card was issued June 1st, 2026."},
                {"pattern": r"expir", "answer": "Yes, the VCC has expired, it expired June 30th, 2026."},
                {"pattern": r"vcc amount", "answer": "The VCC amount was $450."},
                {"pattern": r"mailing address|fax.{0,10}(where|sent)|where.{0,10}(was|vcc).{0,10}sent",
                 "answer": "It was sent by fax to 555-909-1122."},
                {"pattern": r"cashed|been used|card.{0,10}used",
                 "answer": "No, the VCC was never used."},
                {"pattern": r"reissu|new (vcc|check)",
                 "answer": "Yes, please reissue the payment by check."},
                {"pattern": r"eob", "answer": "EOB copy is available by fax at 555-909-1122."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"vcc|virtual credit card", r"expir", r"reissu"],
        "expected_status": "paid",
    },
    {
        "name": "paid_check_wrong_address_reissue",
        "doc": "Paid Claim Verification",
        "account": acct("Confirm payment", **{"Billed Amount": "450"}),
        "keyword_answers": with_status_route(
            "Yes, this claim was paid in full.",
            [
                {"pattern": r"cpt code", "answer": "The CPT code is 99214."},
                {"pattern": r"paid amount|how much.{0,15}paid|what.{0,15}(was|is).{0,10}paid(?!.{0,10}method)",
                 "answer": "The paid amount was $450."},
                {"pattern": r"allowed amount", "answer": "The allowed amount is $450."},
                {"pattern": r"contractual adjustment", "answer": "No contractual adjustment."},
                {"pattern": r"patient responsib", "answer": "No patient responsibility."},
                {"pattern": r"payment method|check or eft|check,? eft,? or vcc|paid by (check|eft|vcc)",
                 "answer": "It was paid by check."},
                {"pattern": r"check number", "answer": "The check number is CHK-90011."},
                {"pattern": r"check.{0,15}(issue|issued)|when.{0,10}(was|check).{0,10}issued",
                 "answer": "The check was issued June 20th, 2026."},
                {"pattern": r"mailing address|where.{0,10}(was|check).{0,10}(sent|mailed)",
                 "answer": "It was mailed to 456 Old St — that's not our correct address."},
                {"pattern": r"cashed|encashed",
                 "answer": "No, the check has not been cashed. It was sent to the wrong address."},
                {"pattern": r"void|reissue|correct address|update.{0,10}address|w-?9",
                 "answer": "Yes, we can void it and reissue to the correct address once you send an updated W-9."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"wrong (mailing )?address|incorrect address", r"void", r"reissu|correct address"],
        "expected_status": "paid",
    },

    # ── Claim Not On File (pre-existing workflow) ─────────────────────
    {
        "name": "claim_not_on_file_never_received",
        "doc": "Claim Not On File",
        "account": acct("Verify claim receipt", **{"Notes": "Submitted electronically 06/15/2026"}),
        "keyword_answers": with_status_route(
            "The claim isn't showing on file, can you check?",
            [
                {"pattern": r"available.{0,10}(system|file)|show.{0,10}(system|file)|find.{0,10}claim|claim.{0,10}(on file|available)",
                 "answer": "No, I don't see this claim in our system at all."},
                {"pattern": r"rejected.{0,15}front.end|received.{0,15}rejected|front.end",
                 "answer": "No, we never received it, not even a front-end rejection."},
                {"pattern": r"member id|patient name|date.{0,10}service|billed amount|search",
                 "answer": "I searched by member ID, patient name and DOB, date of service, and billed amount — nothing comes up."},
                {"pattern": r"submission method|electronic|paper|fax",
                 "answer": "It was submitted electronically on June 15th, 2026."},
                {"pattern": r"active|policy coverage|coverage date",
                 "answer": "Yes, the patient and member ID are active, coverage started January 1st, 2026."},
                {"pattern": r"payer id|mailing address|fax number.{0,15}submi",
                 "answer": "Payer ID is 60054, mailing address is PO Box 5000, Hartford CT, fax 555-111-2222."},
                {"pattern": r"timely filing|filing limit",
                 "answer": "The timely filing limit is 180 days from date of service."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"available.{0,10}(system|file)|show.{0,10}(system|file)|find.{0,10}claim|claim.{0,10}(on file|available)|not.{0,10}(showing|on file)",
                     r"rejected.{0,15}front.end|front.end",
                     r"member id", r"date.{0,10}of.{0,10}service|dos",
                     r"active", r"payer id|mailing address", r"timely filing|filing limit"],
        "expected_status": "pending",
    },
    {
        "name": "claim_not_on_file_rejected_frontend",
        "doc": "Claim Not On File",
        "account": acct("Verify claim receipt", **{"Notes": "Submitted via fax 06/15/2026 to 555-333-4444"}),
        "keyword_answers": with_status_route(
            "The claim isn't showing on file, can you check?",
            [
                {"pattern": r"available.{0,10}(system|file)|show.{0,10}(system|file)|find.{0,10}claim|claim.{0,10}(on file|available)",
                 "answer": "No, I don't see this claim in our system."},
                {"pattern": r"rejected.{0,15}front.end|received.{0,15}rejected|front.end",
                 "answer": "Yes, it was received but rejected at front-end for an invalid member ID."},
                {"pattern": r"member id|patient name|date.{0,10}service|billed amount|search",
                 "answer": "I searched member ID, patient name, DOB, DOS, and billed amount — I can only find the rejection record."},
                {"pattern": r"submission method|electronic|paper|fax",
                 "answer": "It was submitted by fax on June 15th, 2026 to 555-333-4444."},
                {"pattern": r"active|policy coverage|coverage date",
                 "answer": "The patient and member ID are active, coverage started January 1st, 2026."},
                {"pattern": r"payer id|mailing address|fax number.{0,15}submi",
                 "answer": "Payer ID is 60054, resubmit by fax to 555-333-4444."},
                {"pattern": r"timely filing|filing limit",
                 "answer": "Timely filing limit is 180 days from date of service."},
            ],
        ),
        "script": [],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"rejected.{0,15}front.end|front.end", r"member id",
                     r"active", r"payer id|fax number", r"timely filing|filing limit"],
        "expected_status": "pending",
    },

    # ── Generic Denial, non-coverage related (pre-existing, rule 3 path) ─
    {
        "name": "generic_denial_missing_info",
        "doc": "Generic Denial (rule 3)",
        "account": acct("Check denial reason", **{"Denial Code": "CO-16"}),
        "keyword_answers": with_status_route(
            "It's denied.",
            [
                {"pattern": r"denial (reason )?code|remark code",
                 "answer": "The denial code is CO-16, claim lacks information needed to process it."},
                {"pattern": r"appeal process|how.{0,10}appeal|what.{0,10}appeal",
                 "answer": "You'd need to resubmit the claim with the missing information — there's no formal appeal needed for this one."},
                {"pattern": r"what.{0,15}(missing|information|documentation)|specific.{0,15}(missing|needed)",
                 "answer": "We're missing the referring provider's NPI on the claim."},
            ],
        ),
        "script": [
            "You can resubmit by fax to 555-909-1122.",
            "The timely filing limit is 90 days from the denial date.",
        ],
        "fallback": DEFAULT_FALLBACK,
        "required": [r"denial (reason )?code|remark code", r"appeal process|resubmit"],
        "expected_status": "denied",
    },
]
