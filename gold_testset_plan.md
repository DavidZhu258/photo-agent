# Gold Testset Plan: photo-agent
> Generated: 2026-06-08  
> Tier: A-core  
> Project bucket: LLM agent / workflow automation  
> Priority score: 96  
> GitHub: https://github.com/DavidZhu258/photo-agent

## Evaluation Goal

验证 LangGraph/GPT 工作流是否能稳定完成真实图片/旅行/任务编排，而不是只在 happy path 成功。

## Target Gold Set

- Target size: **100**
- Eval type: `llm_agent_workflow`
- Seed cases created now: **3**
- First next step from matrix: 建立 tests/evals/photo_agent_gold.jsonl，并做 20 条最小端到端回归。

## Test-set Design

80-120 个冻结任务：正常图像任务、缺字段任务、多轮修改任务、工具失败任务、不可完成任务；每条含期望状态流、最终产物和拒答/降级标准。

## Metrics

Accuracy metrics:

```text
task success rate; step correctness; tool-call precision; hallucination rate; refusal correctness; human preference win-rate
```

Feasibility metrics:

```text
fresh setup success; median/p95 latency; API cost per task; retry recovery rate; secrets/config completeness; demo reproducibility
```

Rubric seed metrics:

- task_success_rate
- step_correctness
- tool_call_precision
- safe_failure_rate
- cost_per_task
- p95_latency

## Required Hard Cases

图片缺失、用户指令冲突、外部 API 超时、模型返回非 JSON、要求生成不存在事实。

## Build Plan

1. Replace the 3 placeholder seed cases in `evals/gold/seed_gold.jsonl` with real examples.
2. Fill `evals/gold/annotation_template.csv` with expected labels, evidence references, and reviewer status.
3. Run a manual seed evaluation and save raw output in `evals/results/`.
4. Only after the seed suite is stable, expand `evals/gold/full_gold.jsonl` toward the target size.
5. Publish evidence only when the report includes both accuracy and feasibility metrics.

## Acceptance Bar

For portfolio use, the project must pass all seed hard negatives, have a reproducible fresh-run path, and show at least one saved result artifact under `evals/results/`.

## Evidence to Add

README demo GIF、架构图、评测表、失败样例、成本表。
