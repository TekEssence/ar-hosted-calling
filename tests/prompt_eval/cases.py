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
]
