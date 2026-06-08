# Mira LLM Product Evals

This folder contains local, effectiveness-first evals for Mira/photo_agent.

The harness layers deterministic product checks with optional GPT-as-judge scoring:

1. deterministic checks catch schema, endpoint, card/map, and raw-error regressions;
2. GPT judge checks open-ended quality when exact matching is too brittle;
3. generated cases are review aids, while fixed JSONL cases are the release gate.

## Credentials

Project eval GPT calls use the NewAPI/zzshu OpenAI-compatible endpoint.

Set credentials only in the current process:

```powershell
$env:NEWAPI_BASE_URL = "https://www.zzshu.cc/v1"
$env:NEWAPI_API_KEY = "<set locally; do not commit>"
```

Do not write API keys into JSONL cases, reports, docs, scripts, or logs.

## Run deterministic smoke evals

Start Mira Web/backend separately, then run:

```powershell
python -m evals.mira_eval.run `
  --dataset evals/datasets/mira_smoke.jsonl `
  --base-url http://127.0.0.1:3101 `
  --judge-mode off `
  --output reports/evals/local-smoke.json
```

## Run with GPT judge

```powershell
python -m evals.mira_eval.run `
  --dataset evals/datasets/mira_smoke.jsonl `
  --base-url http://127.0.0.1:3101 `
  --judge-mode auto `
  --model gpt-5.5 `
  --output reports/evals/local-smoke-judged.json
```

`auto` skips judge scoring when `NEWAPI_API_KEY` is absent. Use `required` when judge failure should fail the run.

## Generate candidate cases

Generated cases are not automatically trusted. Review them before merging into a fixed suite.

```powershell
python -m evals.mira_eval.generate_cases --count 20 --output evals/datasets/generated_mira_cases.jsonl
```

## Test the harness

```powershell
python -m pytest evals/tests -q
```
