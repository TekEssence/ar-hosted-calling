"""Runs each test case's scripted call against a live vLLM Llama endpoint,
using the exact same message-shaping the real server uses (system prompt +
greeting + "[INSURANCE REP] " prefix + 15-message cap + temp=0).

See ../README.md for setup (SSH tunnel) and usage.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

DEPLOY_ROOT = Path(__file__).resolve().parents[2]  # deploy/tests/prompt_eval -> deploy
sys.path.insert(0, str(DEPLOY_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompts import build_call_prompt, build_greeting, load_payer, parse_call_result, strip_markers  # noqa: E402

from llm_client import chat  # noqa: E402
from cases import CASES  # noqa: E402

MAX_TURNS = 16
REF_NUMBER = "REF-1002"
# Matches server/routes/browser_ws.py's max_tokens for the live call handler —
# keep these in sync so the harness reflects production truncation behavior.
LLM_MAX_TOKENS = 260


def rep_reply(script, agent_text, fallback, given_ref, keyword_answers):
    low = agent_text.lower()
    if ("reference number" in low or "incident number" in low) and not given_ref[0]:
        given_ref[0] = True
        return f"The call reference number is {REF_NUMBER}."
    for entry in keyword_answers:
        if entry["used"]:
            continue
        if re.search(entry["pattern"], low, re.I):
            entry["used"] = True
            return entry["answer"]
    # A bare confirmation ("$450 correct?") that doesn't restate the field
    # name won't match any keyword_answers entry -- affirm it rather than
    # falling through to `fallback`, which reads as "no more info" and
    # causes the agent to wrap up the call early even though it isn't done.
    stripped = agent_text.strip()
    if stripped.endswith("?") and re.search(r"\bcorrect\?\s*$", stripped, re.I):
        return "Yes, that's correct."
    if script:
        return script.pop(0)
    return fallback


def run_case(case, verbose=False):
    account = case["account"]
    payer = load_payer(account.get("Responsible Payer", ""))
    system_prompt = build_call_prompt("GREETING", payer, None, account)

    conversation = [{"role": "system", "content": system_prompt}]
    greeting = build_greeting(account)
    conversation.append({"role": "assistant", "content": greeting})

    script = list(case["script"])
    keyword_answers = [dict(e, used=False) for e in case.get("keyword_answers", [])]
    given_ref = [False]
    transcript = [{"role": "assistant", "content": greeting}]
    call_result = None
    prompt_tokens_peak = 0
    completion_tokens_total = 0
    t0 = time.time()

    turn = 0
    # Rep speaks first (reacting to greeting); the agent's own first question
    # drives the rest of the routing (keyword_answers / script FIFO).
    rep_text = "Sure, I can help. What can I look up for you?"
    while turn < MAX_TURNS:
        turn += 1
        conversation.append({"role": "user", "content": f"[INSURANCE REP] {rep_text}"})
        transcript.append({"role": "user", "content": rep_text})

        conv = conversation if len(conversation) <= 15 else [conversation[0]] + conversation[-14:]
        try:
            bot_text, usage = chat(conv, max_tokens=LLM_MAX_TOKENS, temperature=0.0)
        except Exception as e:
            transcript.append({"role": "error", "content": str(e)})
            break

        prompt_tokens_peak = max(prompt_tokens_peak, int(usage.get("prompt_tokens", 0) or 0))
        completion_tokens_total += int(usage.get("completion_tokens", 0) or 0)

        conversation.append({"role": "assistant", "content": bot_text})
        transcript.append({"role": "assistant", "content": bot_text})
        if verbose:
            print(f"  [{turn}] REP: {rep_text}")
            print(f"  [{turn}] AI : {bot_text}")

        cr = parse_call_result(bot_text)
        if cr:
            call_result = cr
            break

        rep_text = rep_reply(script, bot_text, case["fallback"], given_ref, keyword_answers)

    elapsed = time.time() - t0
    return {
        "name": case["name"],
        "doc": case["doc"],
        "transcript": transcript,
        "call_result": call_result,
        "turns": turn,
        "elapsed_s": round(elapsed, 1),
        "prompt_tokens_peak": prompt_tokens_peak,
        "completion_tokens_total": completion_tokens_total,
    }


def check_required_fields(transcript, required_patterns):
    assistant_text = " \n".join(
        m["content"] for m in transcript if m["role"] == "assistant"
    ).lower()
    results = []
    for pat in required_patterns:
        ok = bool(re.search(pat, assistant_text, re.I))
        results.append({"pattern": pat, "covered": ok})
    return results


def check_structural_rules(transcript):
    """Deterministic style checks, independent of scenario content. These
    catch real but low-severity prompt-adherence drift (e.g. the model
    stacking two question marks in one turn) — treat failures here as
    warnings, not blockers; see the content-only pass rate in the summary."""
    issues = []
    assistant_msgs = [strip_markers(m["content"]) for m in transcript if m["role"] == "assistant"]

    # one question per turn (allow a single '?' ; flag multiple '?' as likely stacked questions)
    for i, msg in enumerate(assistant_msgs):
        qmarks = msg.count("?")
        if qmarks > 1:
            issues.append(f"turn {i}: {qmarks} question marks in one response (possible multi-question turn): {msg[:120]!r}")

    # claim id not repeated after greeting
    greeting = assistant_msgs[0] if assistant_msgs else ""
    m = re.search(r"claim\s+([A-Za-z0-9\-]+)", greeting)
    if m:
        claim_id = m.group(1)
        for i, msg in enumerate(assistant_msgs[1:], start=1):
            if claim_id in msg and "repeat" not in transcript[i * 2 - 1]["content"].lower():
                issues.append(f"turn {i}: repeated claim ID {claim_id!r} without being asked to repeat")

    return issues


def validate(case, result):
    findings = {"name": case["name"], "doc": case["doc"]}
    findings["turns"] = result["turns"]
    findings["prompt_tokens_peak"] = result["prompt_tokens_peak"]
    findings["completion_tokens_total"] = result["completion_tokens_total"]

    field_checks = check_required_fields(result["transcript"], case["required"])
    findings["required_fields"] = field_checks
    findings["required_fields_pass"] = all(f["covered"] for f in field_checks)

    findings["structural_issues"] = check_structural_rules(result["transcript"])

    cr = result["call_result"]
    findings["got_call_result"] = cr is not None
    if cr is not None:
        status_ok = cr.get("status", "").lower() == case["expected_status"].lower()
        findings["status_expected"] = case["expected_status"]
        findings["status_got"] = cr.get("status")
        findings["status_pass"] = status_ok
        findings["call_result"] = cr
    else:
        findings["status_pass"] = False
        findings["status_expected"] = case["expected_status"]
        findings["status_got"] = None

    # content_pass = the substantive signal (did it collect the right info and
    # land on the right status). overall_pass additionally requires the style
    # nits in check_structural_rules to be clean.
    findings["content_pass"] = (
        findings["required_fields_pass"] and findings["got_call_result"] and findings["status_pass"]
    )
    findings["overall_pass"] = findings["content_pass"] and not findings["structural_issues"]
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring filter on case name")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args()

    cases = [c for c in CASES if not args.only or args.only in c["name"]]
    all_results = []
    for case in cases:
        print(f"=== {case['name']} ({case['doc']}) ===")
        result = run_case(case, verbose=args.verbose)
        findings = validate(case, result)
        status = "PASS" if findings["overall_pass"] else ("OK(content)" if findings["content_pass"] else "FAIL")
        print(f"  -> {status}  turns={findings['turns']} "
              f"status={findings['status_got']!r} (expected {findings['status_expected']!r}) "
              f"fields_pass={findings['required_fields_pass']} "
              f"structural_issues={len(findings['structural_issues'])}")
        if not findings["required_fields_pass"]:
            for f in findings["required_fields"]:
                if not f["covered"]:
                    print(f"     MISSING: {f['pattern']}")
        for issue in findings["structural_issues"]:
            print(f"     ISSUE: {issue}")
        all_results.append({"case": case, "result": result, "findings": findings})

    out_path = Path(args.out)
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    n_pass = sum(1 for r in all_results if r["findings"]["overall_pass"])
    n_content = sum(1 for r in all_results if r["findings"]["content_pass"])
    print(f"\n{n_pass}/{len(all_results)} passed strictly (incl. style nits).")
    print(f"{n_content}/{len(all_results)} passed on content (required fields + correct status).")
    print(f"Full results -> {out_path}")


if __name__ == "__main__":
    main()
