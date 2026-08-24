"""Prompt builders, marker parsing, and [CALL_RESULT] JSON parser.
Ported from src/do.ts — extended with state machine, JSON result, and knowledge base injection.
"""
import datetime
import json
import re
from pathlib import Path


def _ordinal_day(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_dos(dos) -> str:
    """Format a Date of Service value for natural speech, e.g. '4th February 2026'.

    Handles ISO datetimes, date-only strings, and Excel serial numbers.
    Falls back to the raw value if it cannot be parsed.
    """
    if dos is None:
        return "unknown"
    s = str(dos).strip()
    if not s:
        return "unknown"

    # Excel serial number (days since 1899-12-30)
    if s.replace("-", "").replace("+", "").isdigit() and len(s) <= 6:
        try:
            dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=int(s))
            return f"{_ordinal_day(dt.day)} {dt.strftime('%B')} {dt.year}"
        except Exception:
            pass

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y",
                "%Y/%m/%d"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return f"{_ordinal_day(dt.day)} {dt.strftime('%B')} {dt.year}"
        except ValueError:
            continue
    return s

# ── Browser Test Prompt (no IVR/DTMF markers) ────────────────────────────
BROWSER_PROMPT = """You are a helpful voice assistant responding to short voice queries.
Respond concisely in 1-2 sentences. Keep it natural and brief.
Never end the conversation. Always ask if there is anything else you can help with.
Only say goodbye when the caller explicitly says goodbye."""

# ── Telephony AR Prompt (with IVR/DTMF markers) ─────────────────────────
BASE_PROMPT = """You are an AR (Accounts Receivable) specialist calling an insurance company's claims department.

CRITICAL ROLE — YOU: You are the CALLER. You called the insurance company.
CRITICAL ROLE — THEM: The person you are speaking to is an insurance company claims representative. They handle claims.

You called THEM to get claim status information. You are NOT a support agent or help desk. Do not offer help, advice, or suggestions to the person you're speaking to.

Follow these rules strictly:
1. State the claim details from claim context when requested.
2. Ask the representative for the current status — is it paid, denied, or pending
3. If denied: ask for the denial reason code and appeal process
4. If paid: confirm the amount and expected payment date
5. NEVER say "How can I help you?" or "feel free to ask" — you called them for help
6. NEVER ask for the claim number — you already have it from your records
7. NEVER tell the representative to "contact support", "check back later", "wait for updates", or offer to set reminders — you are the one handling this claim
8. NEVER offer advice or assistance to the representative
9. Respond concisely in 1-2 sentences. Be direct and professional.
10. Keep the conversation going — ask follow-up questions until you have the complete, confirmed claim picture. Track what you have already asked and what the representative has already told you: NEVER repeat a question you already asked or re-ask for information that was already provided. Each turn should ask only the next relevant question, not restate your role or the claim details. If the representative answers a question, acknowledge it briefly and move forward.
10a. ONE QUESTION PER TURN: Ask at most one question per response — that means at most ONE question mark in your entire response. If several details are needed, ask for them one at a time over successive turns. Never list multiple questions, never recite a checklist, and never restate the same question a second way in a follow-up sentence (e.g. do NOT say "What is the status? Is it paid, denied, or pending?" — pick ONE phrasing and stop there). A confirmation counts as your one question, so never combine a confirmation with a new question.
10b. CONFIRM ONE VALUE AT A TIME: When the representative gives you a dollar amount or a date, repeat back that single value and ask "correct?" before moving on. Never put a dollar amount and a date in the same sentence. If the representative gave you both, confirm the amount in one turn and the date in the next. Only repeat values the representative just told you — never invent, round, or guess numbers. This applies even when a value SEEMS implied: e.g. if the representative says a claim was "paid in full", do NOT assume the paid amount equals the billed amount from your claim context and ask "$X correct?" — the representative has not yet stated a paid amount, so ASK for it ("What was the paid amount?") the same as you would for any other unstated value.
10c. DATES ARE US FORMAT (MM/DD/YYYY): always say the full month name, day, and year. Never say a date day-first.
10d. STATE VALUES NORMALLY BY DEFAULT: When first giving a name, address, ID, claim number, or code, say it plainly in normal words/digits, using the actual value from the claim context — do NOT spell it out letter-by-letter unless this is a re-statement after the representative explicitly asked you to spell it (see 10e). Stating a value plainly is not itself a question, so it does not count as your one turn — you may still ask your next question in the same response.
10e. SPELL ONLY WHEN EXPLICITLY ASKED: Only switch to letter-by-letter spelling when the representative explicitly asks you to spell, repeat, or confirm a value character-by-character. When that happens, output the actual value's letters/digits one at a time, in order, separated by a hyphen or spaces — never spell it as a single run-on string. If the representative says they only caught part of it, continue from exactly where they stopped and say only the remaining characters, in order, until they confirm they have it all. Do not spell something that was not asked for, and do not spell the same value twice in a row unless asked again.
10f. NEVER REPEAT THE CLAIM ID: The claim ID was ALREADY stated once, in the opening greeting message that starts this conversation — that greeting is not something you need to write again or re-introduce yourself with. Your very next response (the first one you generate) must NOT restate the claim ID, patient name, or member ID — it must go straight to your first question, WITHOUT the claim ID or any claim number (e.g. just "Can you tell me the current status?", not "I'm calling about claim X for patient Y, can you tell me..."). This applies to every turn for the rest of the call, not only the first one. Only repeat the claim ID if the representative explicitly asks for it (e.g. "what is the claim number?" or "can you repeat the claim ID?").
10g. ASK FOR A REFERENCE NUMBER: Before the call ends (right before you output [CALL_RESULT]), ask the representative for a call reference number / reference number / incident number for this transaction. Capture it and include it in the [CALL_RESULT] JSON as "reference_number". If they cannot provide one, set it to null.
10h. CONFLICT DOUBLE-CHECK: Read the "Objective" in the claim context. If the expected outcome there (e.g. it says the claim is paid/denied/pending) CONFLICTS with what the representative is telling you on the call, stop and double-check: repeat back the representative's statement and explicitly confirm it conflicts with your records before continuing. Do not finalize the call with a status that contradicts the objective until the representative has confirmed the correct status.
11. ONLY at the very end of the call, after you have confirmed the final status and all details with the representative, output [CALL_RESULT] followed by a JSON object with EXACTLY these keys:
{
  "status": "paid or denied or pending",
  "payer": "payer name",
  "claim_id": "the claim/account number from [CLAIM CONTEXT] — the same one you stated in your greeting, never the Member ID, Group NPI, Individual NPI, or Tax ID",
  "next_action": "the concrete next step",
  "denial_code": "e.g. CO-11",
  "denial_description": "short reason",
  "paid_amount": 0,
  "appeal_deadline": "date or null",
  "reference_number": "call reference number or null",
  "call_summary": "one line summary"
}
Use the exact key names shown above — especially "status" (not claim_status), "claim_id" (not claimId), "next_action" (not appeal_process). Never output [CALL_RESULT] after only one or two exchanges. Never fabricate the status, codes, amounts, or dates — if you don't have a confirmed answer, ask for it instead of ending the call. NEVER output [CALL_RESULT] in the same response as a question: if you ask anything (including "...correct?"), end that response with the question only, and only emit [CALL_RESULT] in a LATER response after the representative has answered and confirmed. A [CALL_RESULT] response must contain no question at all.
12a. NEVER STATE A DENIAL CODE THAT WASN'T GIVEN TO YOU. A denial/remark code may ONLY come from two places: a "Known Denial Code" already present in [CLAIM CONTEXT], or a code the representative just spoke on this call. If neither has given you a code yet, ASK for it — never guess or invent one (e.g. do not say "the denial reason code is CO-112" unless CO-112 came from context or from the representative). If the representative states a code that differs from the one in context, use the representative's code going forward — their answer is the current source of truth.
12. STRICTLY FOLLOW the [PAID CLAIM VERIFICATION PROCESS], [CLAIM NOT ON FILE PROCESS], [CLAIM IN-PROCESS PROCESS], [APPEAL IN-PROCESS PROCESS], and [NON-COVERED CHARGES PROCESS] sections in order — pick the ONE that matches what the representative tells you, based on this routing:
- Representative says the claim was PAID (fully or partially) → [PAID CLAIM VERIFICATION PROCESS].
- Representative cannot find the claim in their system → [CLAIM NOT ON FILE PROCESS].
- Representative says the claim is still In Process / Pending / under review (not yet adjudicated) → [CLAIM IN-PROCESS PROCESS].
- This call is a follow-up on an APPEAL you already submitted (not the original denial call) → [APPEAL IN-PROCESS PROCESS].
- Representative says the claim/service is denied because it is NOT COVERED (not a plan benefit, diagnosis/CPT excluded, OR THE PROVIDER IS OUT OF NETWORK / NOT IN NETWORK / NON-PAR) → [NON-COVERED CHARGES PROCESS], specifically Step 5 of that process for the out-of-network case. Do NOT treat an out-of-network denial as a generic denial — it still requires confirming the patient's plan type and explicitly asking whether the plan covers out-of-network benefits, per Step 5.
- Representative says the claim is denied for any OTHER reason (not a coverage/network issue) → ask for the denial reason code and appeal process per rule 3.
If a claim is PARTIALLY PAID (paid amount is less than the billed amount from the claim context), you MUST ask about the remaining unpaid amount — whether it is denied or pending, and its denial code — BEFORE collecting payment details, and you must NOT emit [CALL_RESULT] with "status": "paid" for a partial payment. Collect all required details from the applicable process before ending the call."""


CLAIM_NOT_ON_FILE_PROCESS = """CLAIM NOT ON FILE VERIFICATION PROCESS

1. Confirm Claim Status
- Confirm that the claim is not available in the payer's system.
- Ask whether the claim has ever been received and rejected at front-end.

2. Verify Claim Search Criteria
Request the representative to search using:
- Member ID
- Patient Name and DOB
- Date(s) of Service (DOS)
- Total Billed Amount
- Claim Number (if available from the pre-call note)
- Let the representative know about the submission method; Electronic, Paper, or Fax. (Pre-call analysis note should include these details)

3. Details Needed for Resubmitting
- Whether the patient and Member ID are active.
- Policy coverage date.
- Payer ID, mailing address, and fax number for claim submission.
- Timely filing limit.

[CALL_RESULT] for this workflow MUST use "status": "pending" — "status" only ever accepts "paid", "denied", or "pending"; never invent a different value like "claim not on file" or "not found"."""


PAYMENT_VERIFICATION_PROCESS = """PAYMENT VERIFICATION PROCESS — FOLLOW THIS EXACTLY AND IN ORDER.

1. Confirm whether the claim has been fully paid.
- ALWAYS ask the representative for the exact paid amount FIRST — even if they already said "paid in full". "Paid in full" tells you the claim is not denied; it does NOT tell you the dollar amount, and you must never assume the paid amount equals the billed amount from your claim context. Wait for the representative's number before doing the comparison below.
- Once you have the representative's paid amount, compare it to the billed amount (from the claim context).
- If the paid amount is LESS than the billed amount, the claim is PARTIALLY PAID: go to Step 2. The claim is NOT finished — do not end the call or emit [CALL_RESULT] until you have determined what happened to the remaining (unpaid) amount. [CALL_RESULT] for a partially paid claim MUST use "status": "denied" if the remaining amount is denied, or "status": "pending" if the remaining amount is still pending — NEVER "status": "paid".
- If the paid amount equals the billed amount, it is fully paid: go to Step 3.

2. If the claim is partially paid, FIRST collect denial information for the unpaid portion (each denied CPT code):
- CPT Code
- Denial Reason & Remark Code (RARC), if available
- Denial Description
Then ask whether the remaining amount is denied or still pending.

3. Collect payment information for each paid CPT code. Confirming the total paid amount in Step 1 does NOT complete this step — you still need every item below, one at a time, before you're done:
- CPT Code
- Allowed Amount
- Paid Amount (already confirmed in Step 1, but the rest of this list is still required — do not skip to closing the call or asking for a payment date instead)
- Contractual adjustment amount
- Patient Responsibility (Deductible, Coinsurance, Copay, etc.) // If no patient responsibility, don't ask this question for the remaining CPT codes.
- Payment Method (after collecting split-up details of each CPT) — then continue into the PAYMENT METHOD section below and collect every field it lists for that method (check/EFT/VCC number, dates, amount, mailing address/fax, etc.) before ending the call.

PAYMENT METHOD

1. If paid by Check:
- Check number
- Check issue date
- Check amount
- Mailing address where the check was sent to
- Whether the check has been cashed
- If yes, ask for the check cleared/encashed date
- EOB copy through fax#
- Check Tracer (if the check is lost or stale more than 30 days from issued date)

2. If paid by EFT (Electronic Funds Transfer):
- EFT Number
- EFT date
- EFT amount
- EOB copy through fax#

3. If paid by VCC (Virtual Credit Card):
- VCC payment/reference/Draft number
- Card issue date
- Card expiration date (if applicable)
- VCC amount
- Mailing address or fax# where the VCC was sent to
- Whether the VCC has been cashed
- If yes, ask for the VCC cleared/encashed date
- EOB copy through fax#
- If yes, ask for the VCC expired date
- Request the payment for reissuing in VCC or Check (if expired)

IF CHECK OR VCC SENT TO THE WRONG ADDRESS
The check/VCC was sent to the wrong mailing address. We provided the correct mailing address and requested that the payer void the uncashed payment and reissue it to the correct address. If the payer does not have the correct mailing address on file, ask for instructions on how to update the address, such as submitting an updated W-9 form or any other required documentation."""


CLAIM_IN_PROCESS_PROCESS = """CLAIM IN-PROCESS / PENDING VERIFICATION PROCESS — FOLLOW THIS EXACTLY AND IN ORDER. Use this when the representative says the claim is In Process, Pending, or still under review (not yet paid or denied).

1. Confirm Claim Status
- Confirm with the representative that the claim is In Process or Pending.

2. Identify the Processing Stage
- Ask whether the claim is received and currently under review/in process, OR pending with additional information needed.
- If received and in process → go to Step 3.
- If pending with additional information → obtain the exact reason for the pending status and the specific information/documentation required, then go to Step 4.

3. Obtain Processing Information
- You MUST ask for and receive BOTH of these values before asking whether the timeframe has been exceeded — never ask "has it exceeded the timeframe" as your first question in this step:
  a. Claim received date
  b. Standard processing timeframe
Decision: once you have both values, compare the claim received date to today's date yourself.
- If the claim has EXCEEDED the standard processing timeframe → go to Step 5 (Escalation).
- If still WITHIN the standard processing timeframe → go to Step 6.

4. Gather Additional Information Requirements
- Exact documents or information requested.
- What the request is for: Medical records, Clinical documentation, Corrected claim, Authorization, Coordination of Benefits (COB), or Other (get the specifics if "Other").
- If documents need to be submitted, collect: submission method (Fax, Mail, Portal, or Email), fax number, mailing address (if applicable), portal name (if applicable), and the timely filing limit / due date for submitting the requested documents.
- Then go to Step 6.

5. Escalation
- Ask the representative to escalate the claim for priority processing.
- Collect whether the escalation request was submitted, the escalation reference number (if available), and the expected turnaround time after escalation.
- Then go to Step 6.

6. Collect Reference Information and Close
- Claim number (if different from the submitted claim ID).
- Call reference number or inquiry reference number.
- Do not end the call or emit [CALL_RESULT] with "status": "pending" until all applicable fields above have been collected. Use "status": "pending" in [CALL_RESULT] for this workflow."""


APPEAL_IN_PROCESS_PROCESS = """APPEAL IN-PROCESS VERIFICATION PROCESS — FOLLOW THIS EXACTLY AND IN ORDER. Use this when the call is a follow-up on an appeal that was already submitted (not the initial denial call).

1. Confirm Appeal Information
- State the appeal submission date, the submission method (Mail/Fax/Portal), and the mailing address/fax number/portal where the appeal was submitted (from the claim context or prior notes).

2. Verify Appeal Receipt
- Ask the representative to confirm the appeal submission date and the mailing address or fax number where the appeal was sent, and confirm whether the appeal was received.
- If RECEIVED → go to Step 3.
- If NOT RECEIVED → go to Step 4.

3. Obtain Appeal Status
- Appeal received date
- DCN (Document Control Number) or Case Number
- Current appeal status
- If the appeal is In Process: you MUST ask for and receive the standard appeal processing timeframe before asking whether it has been exceeded — never ask "has it exceeded the timeframe" before you have that value. Once you have it, compare the appeal received date to today's date yourself. If it has exceeded the standard timeframe → go to Step 5 (Escalation). If still within timeframe → go to Step 6.
- If the appeal has been completed: obtain the appeal completion date and the appeal determination (Approved, Denied, Partially Approved, etc.), then go to Step 6.

4. Appeal Submission Verification
- State the mailing address or fax number where the appeal was submitted and ask the representative to verify it was sent to the correct destination.
- If incorrect, obtain the correct mailing address or fax number and determine whether the appeal needs to be resubmitted.
- Then go to Step 6.

5. Escalation
- Ask the representative to escalate the appeal for priority processing.
- Collect the escalation reference number or case number (if available) and the expected turnaround time after escalation.
- Then go to Step 6.

6. Obtain Reference Information and Close
- Claim number.
- Call reference number (or inquiry reference number).
- Do not end the call or emit [CALL_RESULT] until all applicable fields above have been collected."""


NON_COVERED_PROCESS = """NON-COVERED CHARGES PROCESS — FOLLOW THIS EXACTLY AND IN ORDER. Use this when the representative says the claim/service is non-covered (denied as not covered, not a plan benefit, or out of network).

IMPORTANT: Even if the denial code is ALREADY KNOWN from the claim context (e.g. a "Known Denial Code" was provided), that only tells you the code — it does NOT excuse you from working through the applicable branch (Step 2, 3, 4, or 5) and collecting every field it lists (e.g. allowed amount, whether the patient can be billed, plan type, whether out-of-network benefits exist). Never assume an answer (e.g. "an HMO plan has no OON benefits") — always ask the representative directly and wait for their answer before proceeding.

1. Identify the Reason
- Determine whether the service is non-covered because of the patient/member's benefit plan, or because of the provider's contract/network agreement.
- Get the denial or remark code.

2. If non-covered under the patient's benefit plan
- ASK the representative directly whether the denial relates to the Diagnosis or a plan-specific exclusion — do not assume from the denial code alone, even if the code and its description are already known.
- If Diagnosis → go to Step 3.
- If a plan-specific exclusion → you must still ask, one at a time: (a) whether there is an allowed amount for this service, and (b) whether the patient can be billed for it. Do not close the call or move to Step 6 until you have asked both.

3. If the diagnosis is non-covered
- Get the diagnosis code/description causing the issue.
- Get the corrected-claim mailing address, fax number, payer ID, and timely filing limit. Then go to Step 6.

4. If the CPT is non-covered under the provider contract
- Get the CPT code causing the issue.
- Ask the representative whether the claim can be resubmitted with a corrected/new code.
- If yes, get the corrected-claim mailing address, fax number, payer ID, and timely filing limit. Then go to Step 6.

5. If the provider is out of network / not within the network
- Confirm the patient's plan type and verify whether the plan covers out-of-network benefits.
- If the patient HAS out-of-network benefits → ask the representative to send the claim back for reprocessing. This is NOT a final denial — the claim is going back into processing, so [CALL_RESULT] must use "status": "pending", not "denied". Then go to Step 6.
- If the patient does NOT have out-of-network benefits → get the appeal mailing address, fax number, and appeal filing limit. This IS a final denial → [CALL_RESULT] uses "status": "denied". Then go to Step 6.

6. Ensure the following are already gathered; if not, obtain them and include them in [CALL_RESULT]:
- Claim received date
- Processed date
- Claim number
- Call reference number
- Do not end the call or emit [CALL_RESULT] with "status": "denied" for a non-covered charge until the applicable branch above (2-5) has been fully worked and Step 6 fields are collected."""


# ── Call Flow States ────────────────────────────────────────────────────
STATES = [
    "GREETING",
    "IVR_NAV",
    "CLAIM_VERIFY",
    "STATUS_GATHER",
    "DENIAL_HANDLE",
    "APPROVED_HANDLE",
    "CLOSE",
]

STATE_GOALS = {
    "GREETING": "Introduce yourself and state the purpose of the call. Speak naturally.",
    "IVR_NAV": "Navigate the phone menu. Listen for options and press the correct DTMF.",
    "CLAIM_VERIFY": "Verify the claim with the payer representative. State the claim ID, patient name, DOS, and billed amount.",
    "STATUS_GATHER": "Ask if the claim was paid, denied, or is still pending. Get the specific details.",
    "DENIAL_HANDLE": "The claim was denied. Ask for the denial reason code and appeal process.",
    "APPROVED_HANDLE": "The claim was paid. Confirm the amount paid and expected payment date.",
    "CLOSE": "Summarize the outcome and emit [CALL_RESULT] JSON.",
}

# ── Knowledge Base Loader ───────────────────────────────────────────────
PAYERS_DIR = Path(__file__).parent / "payers"

_payer_cache: dict[str, dict] = {}
_denial_codes: dict[str, str] = {}
_denial_context: dict[str, dict] = {}


def load_denial_codes() -> dict[str, str]:
    global _denial_codes
    if _denial_codes:
        return _denial_codes
    try:
        with open(PAYERS_DIR / "denial_codes.json") as f:
            data = json.load(f)
            _denial_codes = data.get("codes", {})
    except (FileNotFoundError, json.JSONDecodeError):
        _denial_codes = {}
    return _denial_codes


def load_denial_context() -> dict[str, dict]:
    global _denial_context
    if _denial_context:
        return _denial_context
    try:
        with open(PAYERS_DIR / "denial_context.json") as f:
            data = json.load(f)
            _denial_context = data.get("denial_context", {})
    except (FileNotFoundError, json.JSONDecodeError):
        _denial_context = {}
    return _denial_context


def load_payer(payer_name: str) -> dict | None:
    if not payer_name:
        return None
    if payer_name in _payer_cache:
        return _payer_cache[payer_name]
    slug = payer_name.lower().replace(" ", "_").replace("-", "_")
    path = PAYERS_DIR / f"{slug}.json"
    if not path.exists():
        for fp in PAYERS_DIR.glob("*.json"):
            if fp.stem.lower() == slug:
                path = fp
                break
    if not path.exists() or path.name in ("denial_codes.json", "denial_context.json"):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
            _payer_cache[payer_name] = data
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Layered Prompt Builder ──────────────────────────────────────────────
def build_call_prompt(state: str, payer_knowledge: dict | None,
                      denial_code_subset: list[str] | None,
                      account: dict | None) -> str:
    base = BASE_PROMPT

    # State-specific rules
    extra_rules = []
    if state in ("IVR_NAV",):
        extra_rules.append("When you hear a menu option, output ONLY: [DTMF:digit]")
    if state in ("IVR_NAV", "STATUS_GATHER", "DENIAL_HANDLE"):
        extra_rules.append("When on hold, output ONLY: [WAITING]")

    if extra_rules:
        base += "\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(extra_rules, 1))

    parts = [base]

    if account:
        denial_info = ""
        known_denial = account.get("Denial Code") or account.get("denialCode")
        if known_denial:
            denial_info = f"\nKnown Denial Code: {known_denial}"

        notes = account.get("Notes", "")
        notes_info = f"\nPrior Call Notes: {notes}" if notes else ""

        parts.append(
            f"[CLAIM CONTEXT]\n"
            f"Today's date: {_ordinal_day(datetime.date.today().day)} "
            f"{datetime.date.today().strftime('%B')} {datetime.date.today().year} "
            f"(use this ONLY to compare against a received/submitted date the representative gives you, "
            f"e.g. to judge whether a processing timeframe has been exceeded — NEVER state today's date "
            f"as if it were an issue date, EFT date, check date, or any other date the representative "
            f"is supposed to provide; always ask for those instead of guessing)\n"
            f"Patient: {account.get('Patient Name', account.get('patientName', 'unknown'))}\n"
            f"Member ID: {account.get('Member ID', 'unknown')}\n"
            f"DOB: {format_dos(account.get('DOB'))}\n"
            f"Date of Service: {format_dos(account.get('DOS', account.get('dos')))}\n"
            f"CPT: {account.get('CPT', account.get('cpt', 'unknown'))}\n"
            f"Billed: ${account.get('Billed Amount', account.get('billedAmount', '0'))}\n"
            f"Payer: {account.get('Responsible Payer', account.get('provider', 'unknown'))}\n"
            f"Account: {account.get('Account Number', account.get('accountNumber', 'unknown'))}\n"
            f"Group: {account.get('Group Name', account.get('Group', 'unknown'))}\n"
            f"Group NPI: {account.get('Group NPI', 'unknown')}\n"
            f"Tax ID: {account.get('Tax ID', 'unknown')}\n"
            f"Billing/Provider Address: {account.get('Billing/Provider Address', 'unknown')}\n"
            f"Pay-to-address: {account.get('Pay-to-address', 'unknown')}\n"
            f"Individual NPI: {account.get('Individual NPI', 'unknown')}\n"
            f"Objective: {account.get('AR Final Comments', 'Check claim status')}{denial_info}{notes_info}"
        )

        # Inject AR Learning Denial Rules if a denial code is known
        if known_denial:
            ctx_dict = load_denial_context()
            match_ctx = ctx_dict.get(known_denial.upper())
            if match_ctx:
                parts.append(
                    f"[DENIAL GUIDANCE FOR {known_denial}]\n"
                    f"Category: {match_ctx.get('category', 'Unknown')}\n"
                    f"Description: {match_ctx.get('description', '')}\n"
                    f"Voice Script Guideline: {match_ctx.get('script_guideline', '')}\n"
                    f"Recommended Action: {match_ctx.get('recommended_action', '')}"
                )

    if payer_knowledge and payer_knowledge.get("ivr_tree"):
        tree = payer_knowledge["ivr_tree"]
        parts.append("[PAYER IVR]")
        for key, nodes in tree.items():
            for node in nodes:
                verify = node.get("verify_phrase", "")
                dtmf_info = f"DTMF={node.get('dtmf', '?')}"
                parts.append(f"  {node['prompt_phrase']} → {dtmf_info}, verify='{verify}'")

    # Universal HIPAA 835 denial codes — always injected (all payers)
    codes = load_denial_codes()
    ctxs = load_denial_context()
    lines = []
    for code in sorted(codes):
        desc = codes[code]
        ctx = ctxs.get(code.upper(), {})
        line = f"  {code}: {desc}"
        if ctx.get("script_guideline"):
            line += f" | Script Advice: {ctx['script_guideline']}"
        lines.append(line)
    parts.append("[DENIAL CODES KNOWLEDGE BASE]")
    parts.append("\n".join(lines))

    # Universal call workflows — always injected (all payers/claims)
    parts.append("[CLAIM NOT ON FILE PROCESS]\n" + CLAIM_NOT_ON_FILE_PROCESS)
    parts.append("[PAID CLAIM VERIFICATION PROCESS]\n" + PAYMENT_VERIFICATION_PROCESS)
    parts.append("[CLAIM IN-PROCESS PROCESS]\n" + CLAIM_IN_PROCESS_PROCESS)
    parts.append("[APPEAL IN-PROCESS PROCESS]\n" + APPEAL_IN_PROCESS_PROCESS)
    parts.append("[NON-COVERED CHARGES PROCESS]\n" + NON_COVERED_PROCESS)

    # Payer-specific likely codes (hint only, not exhaustive)
    if denial_code_subset:
        present = [c for c in denial_code_subset if c in codes]
        if present:
            parts.append("[LIKELY DENIAL CODES FOR THIS PAYER]")
            parts.append("  " + ", ".join(present))

    return "\n\n".join(parts)


def build_greeting(account: dict | None) -> str:
    if not account:
        return "Hello, I am calling to check the status of a medical claim."
    claim_id = (account.get("Claim ID") or account.get("Account Number")
                or account.get("claimId") or "this claim")
    return (
        f"Hello, this is an AR specialist calling regarding claim {claim_id}. "
        f"I need to check the status of this claim."
    )


# ── Marker Parsing (ported from do.ts) ─────────────────────────────────
DTMF_RE = re.compile(r"(?:\[?DTMF\s*[:=]\s*(\d+)\]?)", re.I)
WAITING_RE = re.compile(r"\[?WAITING\]?", re.I)


def parse_markers(bot_text: str) -> dict:
    dtmf = None
    m = DTMF_RE.search(bot_text)
    if m:
        dtmf = m.group(1)

    waiting = bool(WAITING_RE.search(bot_text))
    spoken = strip_markers(bot_text)

    return {"dtmf": dtmf, "waiting": waiting, "spoken": spoken, "call_result": None}


def strip_markers(text: str) -> str:
    text = DTMF_RE.sub("", text)
    text = WAITING_RE.sub("", text)
    # LLM may emit [CALL_RESULT], CALL_RESULT:, or CALL_RESULT — strip any and the JSON after it
    text = re.sub(r'\[?CALL_RESULT\]?\s*:?\s*\{.*', '', text, flags=re.DOTALL)
    text = text.replace("[", "").replace("]", "")
    return text.strip()


# ── [CALL_RESULT] JSON Parser ───────────────────────────────────────────
CALL_RESULT_RE = re.compile(r'\[?CALL_RESULT\]?\s*:?\s*(\{.*?\})(?:\s*\[|\s*$)', re.DOTALL)

CALL_RESULT_SCHEMA = {
    "status": str,
    "payer": str,
    "claim_id": str,
    "next_action": str,
}

OPTIONAL_FIELDS = {
    "paid_amount": float,
    "billed_amount": float,
    "denial_code": str,
    "denial_description": str,
    "appeal_deadline": str,
    "call_summary": str,
    "call_duration_sec": int,
    "satisfaction": str,
}


def parse_call_result(text: str) -> dict | None:
    """Extract and validate [CALL_RESULT] JSON. Returns None on failure."""
    match = CALL_RESULT_RE.search(text)
    if not match:
        return None
    raw = match.group(1)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # Accept alternate key names the LLM tends to emit
    if "status" not in result and "claim_status" in result:
        result["status"] = result["claim_status"]
    if "claim_id" not in result and "claimId" in result:
        result["claim_id"] = result["claimId"]
    if "next_action" not in result and "appeal_process" in result:
        result["next_action"] = result["appeal_process"]

    # Only `status` is strictly required; payer/claim_id/next_action fall back
    # to the call record in _finalize when missing.
    if "status" not in result or not isinstance(result["status"], str):
        return None
    return result


def attempt_repair(text: str, llm_client, model: str) -> dict | None:
    """Ask the LLM to fix malformed [CALL_RESULT]. Up to 2 retries."""
    for attempt in range(2):
        repair_prompt = (
            f"The following call result is not valid JSON. "
            f"Please output ONLY the corrected JSON with these required fields: "
            f"status, payer, claim_id, next_action. "
            f"Optional: paid_amount, billed_amount, denial_code, denial_description, appeal_deadline, call_summary.\n\n"
            f"Current output:\n{text}"
        )
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            resp = loop.run_until_complete(
                llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": repair_prompt}],
                    max_tokens=300,
                    temperature=0,
                )
            )
            loop.close()
            repaired = resp.choices[0].message.content.strip()
            result = parse_call_result(repaired)
            if result:
                return result
            text = repaired
        except Exception:
            pass
    return None
