# 2026-06-08 Competitive LLM Product Eval

This report summarizes a representative remote run of the Mira LLM product evaluation harness.

## Scope

- Product under test: Mira deployed at `http://87.99.146.185:3101`
- Dataset source: `evals/datasets/mira_competitive.jsonl`
- Fixed suite size: 33 cases
- Representative remote run size: 5 cases
- Targets:
  - `mira`: deployed Mira product, including structured cards/maps where returned
  - `generic_gpt`: GPT-backed text-only general assistant baseline
  - `travel_gpt`: GPT-backed text-only travel assistant baseline
- Judge model: `gpt-5.5` through the NewAPI/zzshu OpenAI-compatible channel
- Scoring priority: effectiveness >> novelty

The representative run used one case from each of these suites:

- `travel_answer`
- `travel_recommendation`
- `travel_planning`
- `travel_constraints`
- `safety_regression`

## Methodology

The same prompts were sent to each target. Mira was evaluated through the deployed product endpoint. Baselines were evaluated as GPT-backed text-only products using the same GPT channel. Each output received an absolute 0..1 rubric score, and Mira was also compared pairwise against each baseline.

This setup follows common public LLM-evaluation practice:

- [OpenAI Evals](https://developers.openai.com/api/docs/guides/evals): fixed datasets plus explicit graders/testing criteria.
- [Inspect AI](https://inspect.aisi.org.uk/index.html): tasks composed from datasets, solvers, and scorers.
- [HELM](https://crfm-helm.readthedocs.io/en/stable/): transparent multi-scenario, multi-metric evaluation.
- [LangSmith pairwise evaluation](https://docs.langchain.com/langsmith/evaluate-pairwise): compare multiple experiment outputs on the same dataset.
- [Ragas metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/): separate response relevancy, faithfulness, and retrieval-oriented dimensions.
- [MLCommons AILuminate](https://mlcommons.org/benchmarks/ailuminate/): system-under-test safety prompts with evaluator-based violation scoring.

## Results

| Target | Weighted score | Pass rate | Average latency |
| --- | ---: | ---: | ---: |
| `mira` | 0.920 | 100% | 55,100 ms |
| `generic_gpt` | 0.961 | 100% | 20,198 ms |
| `travel_gpt` | 0.959 | 100% | 25,305 ms |

## Suite Scores

| Suite | Mira | generic_gpt | travel_gpt |
| --- | ---: | ---: | ---: |
| `safety_regression` | 0.960 | 1.000 | 0.980 |
| `travel_answer` | 0.950 | 0.960 | 0.960 |
| `travel_constraints` | 0.930 | 0.950 | 0.960 |
| `travel_planning` | 0.880 | 0.950 | 0.940 |
| `travel_recommendation` | 0.880 | 0.940 | 0.950 |

## Pairwise

| Competitor | Mira wins | Competitor wins | Ties | Mira win rate |
| --- | ---: | ---: | ---: | ---: |
| `generic_gpt` | 1 | 4 | 0 | 20% |
| `travel_gpt` | 0 | 5 | 0 | 0% |

## Interpretation

Mira passed the representative gate, but the text-only GPT baselines scored higher on absolute quality and pairwise preference. The most visible gap is not basic answer correctness; it is concise usefulness and latency. Mira’s structured product output is valuable, but the current orchestration appears slower and not yet strong enough in rubric-level recommendation/planning quality to beat a direct GPT text baseline on these samples.

## Verification Notes

- Local eval harness tests: `python -m pytest evals/tests -q` → 15 passed.
- Local Python compile check: `python -m compileall -q evals/mira_eval` → passed.
- Remote deployment sync marker: `/opt/photo-agent-visual/.evals-deployed-commit` → `4066dce`.
- Remote service health: `GET http://87.99.146.185:3101/api-backend/v1/visual/discover` → HTTP 200.
- Remote harness import/data check: 33 cases loaded across `safety_regression`, `travel_answer`, `travel_constraints`, `travel_planning`, `travel_recommendation`, and `visual_discovery`.

Full 33-case remote runs are intentionally left for scheduled or overnight execution because the product path can involve live LLM/search calls and exceeded a 15-minute interactive window during ad-hoc testing.

## Limits

- This report compares Mira against GPT-backed text baselines, not logged-in commercial product UIs such as ChatGPT, Gemini, Perplexity, or Claude.
- GPT-as-judge is useful for regression triage and broad coverage, but human review is still needed before high-stakes product decisions.
- Raw model outputs and local `reports/` artifacts are not committed.
