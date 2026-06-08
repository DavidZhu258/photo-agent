# GPT-Only LLM Product Evaluation Harness Design

## Purpose

Build an effectiveness-first evaluation layer for Mira/photo_agent. The harness should measure whether the product answers real travel and visual-discovery tasks usefully, safely, and with stable response contracts. Innovation-heavy benchmark chasing is explicitly lower priority than catching practical regressions in the current product.

## External Practice Applied

The design follows recent open-source LLM evaluation practice from Promptfoo, DeepEval, Ragas, Inspect AI, and OpenAI Evals:

- deterministic contract checks before model grading;
- GPT-as-judge only for open-ended product quality;
- generated prompts are useful, but fixed golden cases must remain the release gate;
- judge rubrics should be decomposed, low-precision, and calibrated against human labels;
- results should be stored as artifacts so score drift can be reviewed over time.

## Scope

First version covers GPT-only evaluation. It does not add DeepSeek comparisons yet. It also does not introduce a hosted eval platform. Everything runs locally from CLI scripts and writes local JSON/Markdown artifacts.

## Credential Policy

Project LLM calls use the NewAPI/zzshu OpenAI-compatible channel:

- `NEWAPI_BASE_URL`, default `https://www.zzshu.cc/v1`
- `NEWAPI_API_KEY`, required only when GPT generation or GPT judge is enabled

The API key value must never be committed, written to logs, included in reports, printed in CLI output, or stored in project summaries. Scripts should read it from the current process environment.

## Architecture

Create a small Python package under `evals/mira_eval/`.

Main units:

- `schemas.py`: dataclasses for test cases, deterministic check results, judge verdicts, and run results.
- `newapi_client.py`: minimal OpenAI-compatible chat client that normalizes normal JSON and SSE-style responses.
- `judge.py`: builds injection-resistant judge prompts and parses strict JSON verdicts.
- `checks.py`: deterministic product contract checks for travel chat, visual discovery, and safety regression outputs.
- `runner.py`: loads JSONL cases, calls the product endpoint, applies deterministic checks, optionally calls GPT judge, and writes result artifacts.
- `generate_cases.py`: optional GPT-based test-case generator that emits reviewable JSONL cases.
- `run.py`: CLI entrypoint for running an eval suite.

## Dataset Shape

JSONL cases are intentionally simple and reviewable:

```json
{
  "id": "travel-answer-fugu-001",
  "suite": "travel_answer",
  "endpoint": "/api/travel/chat",
  "method": "POST",
  "body": {"messages": [{"role": "user", "content": "河豚是什么，为什么危险？"}], "context": {}},
  "checks": [
    {"type": "status_code", "expected": 200},
    {"type": "assistant_text_contains_any", "terms": ["河豚", "毒素", "危险"]},
    {"type": "no_trip_cards"}
  ],
  "judge": {
    "rubric": "Answer the user's direct factual question accurately, without inventing travel recommendations or unrelated place cards.",
    "threshold": 0.8
  }
}
```

## Initial Suites

1. **Travel answer-only**
   - Direct knowledge questions should return a useful text answer.
   - They should not fabricate recommendation cards.

2. **Travel recommendation**
   - Destination recommendation prompts should return relevant cards and a ready map.
   - Cards should be region-appropriate and avoid unrelated categories.

3. **Visual discovery contract**
   - Visual POST should return `one_line_answer` and exactly three deep cards.
   - Judge checks should reward visible-clue use and calibrated uncertainty.

4. **Mobile/background job contract**
   - Job endpoints should preserve `job_id`, `status`, `query`, and final message shape.
   - This suite may start as deterministic-only because live jobs can be slow.

5. **Safety/regression**
   - Prompt injection, secret extraction, dangerous travel advice, and raw provider errors should fail fast.

## Result Artifacts

Default output path:

```text
reports/evals/YYYYMMDD-HHMMSS-mira-eval.json
```

Artifacts include:

- run metadata;
- per-case deterministic check results;
- optional judge verdicts;
- pass/fail counts;
- score averages;
- endpoint latency;
- warnings for skipped judge calls.

`reports/` is already ignored by git.

## Pass Gates

- Local smoke: fixed 10-20 cases; no critical deterministic failures; judge pass rate at least 90% when judge is enabled.
- Nightly/manual: fixed + generated 50-100 cases; track averages by suite.
- Release: fixed golden suite plus holdout suite; judge rubrics should be spot-checked against a small human-labeled calibration set.

## Non-Goals

- No hosted eval dashboard in v1.
- No automatic prompt optimization in v1.
- No multi-model tournament in v1.
- No storage of API keys in repo files.
