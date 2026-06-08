# evals/ for photo-agent

Minimum evaluation scaffold for `photo-agent`.

## Layout

```text
evals/
  gold/seed_gold.jsonl
  gold/full_gold.jsonl
  gold/annotation_template.csv
  rubrics/rubric.yaml
  scripts/README.md
  fixtures/
  results/
```

## Contract

- Eval type: `llm_agent_workflow`
- Target full gold size: `100`
- Seed cases: `3`
- Metrics: task_success_rate, step_correctness, tool_call_precision, safe_failure_rate, cost_per_task, p95_latency

Replace placeholders with real fixtures/records before using any result as portfolio evidence.
