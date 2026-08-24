# Prompt evaluation harness

Tests `prompts.py`'s call-flow logic (`build_call_prompt`, `build_greeting`,
`parse_call_result`) against a **live LLM**, not a mock. It drives full
multi-turn scripted calls through the actual system prompt and checks that
the agent collects the right information and lands on the right
`[CALL_RESULT]` status for each branch of the AR call workflows (Paid,
Claim Not On File, Claim In-Process, Appeal In-Process, Non-Covered
Charges).

Use this whenever `prompts.py` changes — new workflow docs, wording tweaks,
routing changes — to catch regressions before they reach a live call.

## How it works

- `cases.py` — one test case per branch of every workflow doc (currently
  12). Each case has a scripted "insurance rep" persona: a set of
  keyword-triggered canned answers (`keyword_answers`) for branch-deciding
  yes/no questions, a FIFO `script` for sequential factual asks (dates,
  amounts, addresses), and a `required` list of regexes that must show up
  somewhere in the agent's own turns (i.e. it actually asked about that
  topic), plus the `expected_status` the call should close with.
- `runner.py` — builds the real system prompt via `build_call_prompt`,
  simulates the call turn-by-turn against the LLM (same message shaping as
  `server/routes/browser_ws.py`: system + greeting + `[INSURANCE REP] `
  prefix + 15-message history cap), and validates each transcript.
- `judge.py` — optional secondary pass: asks the same LLM to score each
  transcript 1-5 against the workflow rubric. **This is a weak, low-res
  signal on an 8B model** (it tends to hand out a flat 4/5) — use it only
  as a floor check for catastrophic failures, not as your primary signal.
- `llm_client.py` — a stdlib-only (`urllib`, no `pip install` needed)
  OpenAI-compatible chat client, so the harness runs with a bare `python3`.

The rep simulator is intentionally **not another LLM**: two LLMs
improvising at each other compounds randomness and makes failures
unreproducible. A scripted rep with `temperature=0` on the agent side
means the same `prompts.py` always produces the same transcript, so a
diff in `prompts.py` produces a diff in results you can actually attribute.

## Setup

The LLM under test runs in a `vllm/vllm-openai` Docker container on the
Azure T4 GPU VM (not locally — there's no local GPU). Open an SSH tunnel to
it first:

```bash
ssh -i ~/.ssh/llama-si_key.pem -o StrictHostKeyChecking=no -f -N \
    -L 18001:localhost:8001 azureuser@4.247.26.45
```

That backgrounds itself (`-f -N`); leave it running. Verify it's up:

```bash
curl -s http://localhost:18001/v1/models | python3 -m json.tool
```

No `pip install` required — everything here is Python stdlib.

## Running

From this directory:

```bash
# Full suite
python3 runner.py --out results.json

# One case (substring match on name), with full transcript printed
python3 runner.py --only claim_in_process_within_timeframe --verbose

# Secondary LLM-judge pass over a completed results file
python3 judge.py results.json
```

### Reading the output

Each case prints one of:
- `PASS` — collected every required field, correct final status, AND no
  style nits (see below).
- `OK(content)` — collected every required field and correct final status,
  but tripped a style nit. **This is a pass for practical purposes.**
- `FAIL` — missing required fields and/or wrong final status. This is the
  signal that actually matters.

The summary line splits both counts:
```
8/12 passed strictly (incl. style nits).
8/12 passed on content (required fields + correct status).
```
Always look at the **content** number first — it's what "does the agent
actually follow the scenario" means. The strict number additionally
enforces two cosmetic style rules (`check_structural_rules` in
`runner.py`): at most one `?` per turn, and never repeating the claim ID
after the greeting. These matter for call quality but a single miss here
doesn't mean the workflow broke.

`results.json` has the full transcript, findings, and `[CALL_RESULT]` JSON
for every case — read it directly when a case fails to see exactly where
the conversation went wrong.

## Known model-level limitations (not further prompt-fixable without
## whack-a-mole regressions elsewhere — observed directly while tuning)

- The model sometimes answers "is it paid, denied, or pending?" with a
  restated second sentence ("...Is it paid, denied, or pending?"), i.e.
  two `?` in one turn. Cosmetic; harmless for TTS.
- On some runs it skips asking for the claim/appeal received date before
  judging "exceeded the timeframe" (`claim_in_process_exceeded_timeframe_escalation`).
- On some branches (`non_covered_plan_specific_exclusion`,
  `non_covered_oon_no_benefits_appeal`) it occasionally drifts into a
  generic-denial tangent instead of finishing that branch's specific
  fields (allowed amount / bill-patient / appeal address).

These come from testing on `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`
(8B, INT4-quantized) — tightening the prompt further to chase these
reliably regressed a *different* case elsewhere in testing. If the model
is ever upgraded, re-run the suite; a larger/less-quantized model should
close most of these on its own.

## Adding a new test case

Add an entry to `CASES` in `cases.py` following the existing pattern:
`account` (claim context), `keyword_answers` (branch-deciding routing —
wrap the whole list in `with_status_route(...)` so the generic opening
"is it paid, denied, or pending?" question is answered first), `script`
(sequential factual answers), `required` (regexes the agent's own turns
must satisfy), and `expected_status`.
