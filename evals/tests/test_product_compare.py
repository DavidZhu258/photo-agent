import json

import httpx
import pytest

from evals.mira_eval.product_compare import (
    InMemoryBaselineClient,
    InMemoryJudgeClient,
    render_markdown_report,
    run_competitive_benchmark,
)


@pytest.mark.asyncio
async def test_competitive_benchmark_scores_mira_and_gpt_baseline_on_same_cases(tmp_path):
    dataset = tmp_path / "competitive.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "travel-answer-fugu",
                        "suite": "travel_answer",
                        "endpoint": "/api/travel/chat",
                        "method": "POST",
                        "body": {"messages": [{"role": "user", "content": "河豚为什么危险？"}], "context": {}},
                        "checks": [{"type": "status_code", "expected": 200}],
                        "judge": {"rubric": "Must explain fugu toxin risk accurately.", "threshold": 0.8, "weight": 2.0},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "travel-rec-fukuoka",
                        "suite": "travel_recommendation",
                        "endpoint": "/api/travel/chat",
                        "method": "POST",
                        "body": {"messages": [{"role": "user", "content": "福冈第一次去推荐哪里？"}], "context": {}},
                        "checks": [{"type": "status_code", "expected": 200}],
                        "judge": {"rubric": "Must recommend relevant Fukuoka places.", "threshold": 0.8, "weight": 1.0},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if "河豚" in request.content.decode("utf-8"):
            text = "河豚可能含河豚毒素，必须由持证厨师处理。"
        else:
            text = "推荐大濠公园、櫛田神社和中洲屋台。"
        return httpx.Response(200, json={"message": {"parts": [{"type": "text", "text": text}]}}, request=request)

    judge_client = InMemoryJudgeClient(
        absolute_scores={
            ("mira", "travel-answer-fugu"): 0.9,
            ("generic_gpt", "travel-answer-fugu"): 0.7,
            ("mira", "travel-rec-fukuoka"): 0.8,
            ("generic_gpt", "travel-rec-fukuoka"): 0.6,
        },
        pairwise_winners={
            ("generic_gpt", "travel-answer-fugu"): "mira",
            ("generic_gpt", "travel-rec-fukuoka"): "mira",
        },
    )
    baseline_client = InMemoryBaselineClient({"generic_gpt": "baseline answer"})

    report = await run_competitive_benchmark(
        dataset_path=dataset,
        base_url="http://mira.test",
        targets=["mira", "generic_gpt"],
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        judge_client=judge_client,
        baseline_client=baseline_client,
    )

    assert report["summary"]["case_count"] == 2
    assert report["summary"]["targets"] == ["mira", "generic_gpt"]
    assert report["targets"]["mira"]["weighted_score"] == pytest.approx((0.9 * 2 + 0.8) / 3)
    assert report["targets"]["generic_gpt"]["weighted_score"] == pytest.approx((0.7 * 2 + 0.6) / 3)
    assert report["pairwise"]["generic_gpt"]["mira_wins"] == 2
    assert report["pairwise"]["generic_gpt"]["competitor_wins"] == 0


def test_render_markdown_report_includes_methodology_and_score_tables():
    report = {
        "summary": {
            "case_count": 2,
            "targets": ["mira", "generic_gpt"],
            "methodology_sources": [
                {"name": "OpenAI Evals", "url": "https://developers.openai.com/api/docs/guides/evals"}
            ],
        },
        "targets": {
            "mira": {"weighted_score": 0.86, "pass_rate": 1.0, "average_latency_ms": 1200, "suite_scores": {"travel_answer": 0.9}},
            "generic_gpt": {
                "weighted_score": 0.66,
                "pass_rate": 0.5,
                "average_latency_ms": 800,
                "suite_scores": {"travel_answer": 0.7},
            },
        },
        "pairwise": {"generic_gpt": {"mira_wins": 2, "competitor_wins": 0, "ties": 0}},
        "cases": [],
    }

    markdown = render_markdown_report(report)

    assert "Mira Competitive LLM Product Evaluation" in markdown
    assert "| Target | Weighted score | Pass rate | Avg latency |" in markdown
    assert "| mira | 0.860 | 100% | 1200 ms |" in markdown
    assert "| generic_gpt | 0.660 | 50% | 800 ms |" in markdown
    assert "OpenAI Evals" in markdown
    assert "Pairwise" in markdown
