import json

import httpx
import pytest

from evals.mira_eval.runner import run_eval_suite


@pytest.mark.asyncio
async def test_runner_loads_jsonl_calls_endpoint_and_writes_results(tmp_path):
    dataset = tmp_path / "suite.jsonl"
    output = tmp_path / "result.json"
    dataset.write_text(json.dumps({
        "id": "travel-answer",
        "suite": "travel_answer",
        "endpoint": "/api/travel/chat",
        "method": "POST",
        "body": {"messages": [{"role": "user", "content": "河豚是什么？"}], "context": {}},
        "checks": [{"type": "status_code", "expected": 200}],
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://mira.test/api/travel/chat"
        return httpx.Response(200, json={"message": {"parts": [{"type": "text", "text": "ok"}]}}, request=request)

    result = await run_eval_suite(
        dataset_path=dataset,
        base_url="http://mira.test",
        output_path=output,
        judge_mode="off",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert result.summary["total"] == 1
    assert result.summary["failed"] == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["summary"]["passed"] == 1
