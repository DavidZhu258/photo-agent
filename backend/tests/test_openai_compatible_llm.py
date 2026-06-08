import json

import httpx
import pytest

from app.services.openai_compatible_llm import OpenAICompatibleLLMClient, parse_jsonish


def test_parse_jsonish_extracts_first_object_after_think_block():
    content = """
<think>
I will reason before returning the object.
</think>

{
  "answer_mode": "answer_only",
  "capability_plan": {"required_capabilities": ["knowledge"]}
}

Extra trailing text with {"ignored": true}.
"""

    parsed = parse_jsonish(content)

    assert parsed["answer_mode"] == "answer_only"
    assert parsed["capability_plan"]["required_capabilities"] == ["knowledge"]


@pytest.mark.asyncio
async def test_complete_json_retries_truncated_json_with_same_model():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = '{"answer_mode":' if calls == 1 else '{"answer_mode":"answer_only"}'
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=request,
        )

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://deepinfra.test/v1/openai",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_base_delay=0,
    )

    result = await client.complete_json(model="google/gemini-3.1-pro", system="json", payload={})

    assert result["answer_mode"] == "answer_only"
    assert calls == 2


@pytest.mark.asyncio
async def test_complete_text_retries_transient_http_error_with_same_payload():
    calls = 0
    bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        bodies.append(json.loads(request.content.decode("utf-8")))
        if calls == 1:
            return httpx.Response(503, json={"error": "busy"}, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=request,
        )

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://deepinfra.test/v1/openai",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_base_delay=0,
    )

    result = await client.complete_text(
        model="google/gemini-3.1-pro",
        system="plain",
        payload={"query": "河豚是什么"},
    )

    assert result == "ok"
    assert calls == 2
    assert bodies[0] == bodies[1]


@pytest.mark.asyncio
async def test_complete_text_retries_without_token_limit_when_gateway_rejects_it():
    bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        bodies.append(body)
        if "max_tokens" in body:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: max_output_tokens",
                        "type": "invalid_request_error",
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok without limit"}}]},
            request=request,
        )

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://zzshu.cc/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_base_delay=0,
    )

    result = await client.complete_text(
        model="gpt-5.5",
        system="注意回答需要分类",
        payload={"query": "河豚是什么"},
        max_tokens=300,
    )

    assert result == "ok without limit"
    assert "max_tokens" in bodies[0]
    assert "max_tokens" not in bodies[1]


@pytest.mark.asyncio
async def test_gpt55_gateway_requests_default_to_simplified_chinese():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=request,
        )

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://zzshu.cc/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await client.complete_text(
        model="gpt-5.5",
        system="注意回答需要分类",
        payload={"query": "Fukuoka food recommendations"},
    )

    system = captured["payload"]["messages"][0]["content"]
    assert system.startswith("注意回答需要分类")
    assert "默认使用简体中文回答" in system
    assert "除非用户明确要求其他语言" in system


@pytest.mark.asyncio
async def test_complete_text_parses_sse_chat_chunks_from_gateway():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"第一段"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"，第二段"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, request=request)

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://zzshu.cc/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.complete_text(
        model="gpt-5.5",
        system="注意回答需要分类",
        payload={"query": "福冈"},
    )

    assert result == "第一段，第二段"


@pytest.mark.asyncio
async def test_gpt_gateway_requests_streaming_to_avoid_usage_only_sse():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        body = (
            'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, request=request)

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://www.zzshu.cc/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.complete_text(
        model="gpt-5.5",
        system="plain",
        payload={"query": "ping"},
    )

    assert result == "OK"
    assert captured["payload"]["stream"] is True


@pytest.mark.asyncio
async def test_complete_json_can_send_native_tools_with_auto_choice():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer_mode":"answer_only"}'}}]},
            request=request,
        )

    client = OpenAICompatibleLLMClient(
        api_key="test",
        base_url="https://zzshu.cc/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.complete_json(
        model="gpt-5.5",
        system="注意回答需要分类",
        payload={"query": "福冈去哪吃河豚？"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "serper_places",
                    "description": "Search real Google local/places results for travel POIs.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        tool_choice="auto",
    )

    assert result["answer_mode"] == "answer_only"
    assert captured["payload"]["model"] == "gpt-5.5"
    assert captured["payload"]["messages"][0]["content"].startswith("注意回答需要分类")
    assert "默认使用简体中文回答" in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["tools"][0]["function"]["name"] == "serper_places"
    assert captured["payload"]["tool_choice"] == "auto"
