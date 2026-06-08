# Mira LLM Product Evals

This folder contains local, effectiveness-first evals for Mira/photo_agent.

The harness layers deterministic product checks with optional GPT-as-judge scoring:

1. deterministic checks catch schema, endpoint, card/map, and raw-error regressions;
2. GPT judge checks open-ended quality when exact matching is too brittle;
3. competitive scoring compares Mira with GPT-backed text baselines on the same cases;
4. generated cases are review aids, while fixed JSONL cases are the release gate.

The default weighting follows the product priority **effectiveness >> novelty**.

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

## Run the larger competitive benchmark

The competitive suite uses `evals/datasets/mira_competitive.jsonl` and evaluates the same cases against:

- `mira`: the deployed Mira product endpoint, including cards/maps where the product returns them;
- `generic_gpt`: a mainstream GPT-backed text-only assistant baseline;
- `travel_gpt`: a GPT-backed travel-planning text-only baseline.

These baselines are intentionally described as GPT text baselines, not as logged-in third-party commercial UIs.

```powershell
python -m evals.mira_eval.compare `
  --dataset evals/datasets/mira_competitive.jsonl `
  --base-url http://127.0.0.1:3101 `
  --targets mira,generic_gpt,travel_gpt `
  --model gpt-5.5 `
  --output-json reports/evals/local-competitive.json `
  --output-md reports/evals/local-competitive.md
```

Use `--limit 5` for a fast dry run. Full runs can be slow because each case may call the product, GPT baselines, absolute judges, and pairwise judges.

## Methodology references

The harness borrows proven patterns from public LLM-evaluation practice:

- [OpenAI Evals](https://developers.openai.com/api/docs/guides/evals): fixed datasets plus explicit graders/testing criteria.
- [Inspect AI](https://inspect.aisi.org.uk/index.html): tasks composed from datasets, solvers, and scorers.
- [HELM](https://crfm-helm.readthedocs.io/en/stable/): transparent multi-scenario, multi-metric evaluation.
- [LangSmith pairwise evaluation](https://docs.langchain.com/langsmith/evaluate-pairwise): compare multiple experiment outputs on the same dataset.
- [Ragas metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/): separate response relevancy, faithfulness, and context/retrieval metrics.
- [MLCommons AILuminate](https://mlcommons.org/benchmarks/ailuminate/): system-under-test safety prompts and evaluator-based violation scoring.

## Generate candidate cases

Generated cases are not automatically trusted. Review them before merging into a fixed suite.

```powershell
python -m evals.mira_eval.generate_cases --count 20 --output evals/datasets/generated_mira_cases.jsonl
```

## Test the harness

```powershell
python -m pytest evals/tests -q
```
