"""LLM-as-judge secondary pass over a runner.py results file.

Caveat: this asks the SAME model under test to judge its own transcripts.
On an 8B model this is a weak, low-resolution judge in practice (in testing
it gave a flat 4/5 to everything, including cases the deterministic checks
in runner.py caught as missing required fields). Treat it as a floor check
("did anything score 1-2, i.e. a catastrophic failure?"), not a substitute
for the deterministic required-field/status checks, which remain the
primary signal.
"""
import json
import sys
from llm_client import chat

RUBRIC = """You are a strict QA auditor for an AR (insurance claims) voice agent. \
You will be shown the workflow rules the agent was supposed to follow for a specific \
scenario, and the transcript of a call it made. Score the agent 1-5 on how well it \
followed the workflow:
5 = collected every required field, in a sensible order, correct final status.
4 = collected everything but order was imperfect or asked a slightly redundant question.
3 = missed one minor required field but got the overall outcome/status right.
2 = missed multiple required fields or got the final status wrong.
1 = ignored the workflow entirely or fabricated information.

Respond with ONLY a JSON object: {"score": <int 1-5>, "reason": "<one sentence>"}"""


def judge_case(doc_name, required_desc, transcript):
    convo_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in transcript)
    user_msg = (
        f"Scenario: {doc_name}\nRequired fields/steps for this scenario: {required_desc}\n\n"
        f"Transcript:\n{convo_text}\n\nScore this call."
    )
    content, _ = chat(
        [{"role": "system", "content": RUBRIC}, {"role": "user", "content": user_msg}],
        max_tokens=120, temperature=0.0,
    )
    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        return json.loads(content[start:end])
    except Exception:
        return {"score": None, "reason": f"unparseable: {content[:150]}"}


def main():
    results_path = sys.argv[1] if len(sys.argv) > 1 else "results.json"
    data = json.load(open(results_path))
    scores = []
    for r in data:
        case = r["case"]
        verdict = judge_case(case["doc"], "; ".join(case["required"]), r["result"]["transcript"])
        scores.append(verdict.get("score"))
        print(f"{case['name']:50s} score={verdict.get('score')}  {verdict.get('reason','')[:100]}")
    valid = [s for s in scores if isinstance(s, int)]
    if valid:
        print(f"\nAverage judge score: {sum(valid)/len(valid):.2f}/5 over {len(valid)}/{len(scores)} cases")


if __name__ == "__main__":
    main()
