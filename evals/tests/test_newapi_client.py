import httpx
import pytest

from evals.mira_eval.newapi_client import NewApiChatClient, parse_chat_content


def test_parse_chat_content_extracts_normal_message():
    body = {"choices": [{"message": {"content": "hello"}}]}
    assert parse_chat_content(body) == "hello"


def test_parse_chat_content_extracts_sse_delta_chunks():
    raw = (
        'data: {"choices":[{"delta":{"content":"第一段"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"，第二段"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    assert parse_chat_content(raw) == "第一段，第二段"


@pytest.mark.asyncio
async def test_client_uses_newapi_env_without_leaking_key(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    monkeypatch.setenv("NEWAPI_API_KEY", "secret-key")
    client = NewApiChatClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = await client.chat(messages=[{"role": "user", "content": "ping"}], model="gpt-5.5")

    assert result == "ok"
    assert captured["authorization"] == "Bearer secret-key"
    assert "secret-key" not in captured["payload"]


@pytest.mark.asyncio
async def test_client_requests_streaming_because_newapi_non_stream_can_be_usage_only(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.content.decode("utf-8")
        body = (
            'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, request=request)

    monkeypatch.setenv("NEWAPI_API_KEY", "secret-key")
    client = NewApiChatClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = await client.chat(messages=[{"role": "user", "content": "ping"}], model="gpt-5.5")

    assert result == "OK"
    assert '"stream":true' in captured["payload"].replace(" ", "")


@pytest.mark.asyncio
async def test_client_stops_reading_sse_after_done_without_waiting_for_connection_close(monkeypatch):
    class NeverEndingSseResponse:
        headers = {"content-type": "text/event-stream"}

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"done-fast"}}]}'
            yield "data: [DONE]"
            raise AssertionError("client should stop reading once [DONE] is received")

    class StreamingOnlyClient:
        def __init__(self):
            self.stream_called = False

        def stream(self, method, url, *, headers, json):
            self.stream_called = True
            assert method == "POST"
            assert url.endswith("/chat/completions")
            assert headers["Authorization"] == "Bearer secret-key"
            assert json["stream"] is True

            class Context:
                async def __aenter__(self):
                    return NeverEndingSseResponse()

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return Context()

        async def post(self, *args, **kwargs):
            raise AssertionError("streaming NewAPI calls must not use post(), which waits for EOF")

    monkeypatch.setenv("NEWAPI_API_KEY", "secret-key")
    fake_client = StreamingOnlyClient()
    client = NewApiChatClient(http_client=fake_client)

    result = await client.chat(messages=[{"role": "user", "content": "ping"}], model="gpt-5.5")

    assert result == "done-fast"
    assert fake_client.stream_called is True
