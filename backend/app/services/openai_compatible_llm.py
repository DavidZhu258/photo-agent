from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx


class OpenAICompatibleLLMClient:
    """Small OpenAI-compatible chat client with strict text/JSON helpers."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        retry_base_delay: float = 0.4,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.retry_base_delay = max(0.0, retry_base_delay)

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        payload: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 1400,
        reasoning_effort: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                content = await self.complete_text(
                    model=model,
                    system=system,
                    payload=payload,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format={"type": "json_object"},
                    timeout=timeout,
                )
                parsed = parse_jsonish(content)
                if not isinstance(parsed, dict):
                    raise ValueError("model response was not a JSON object")
                return parsed
            except (json.JSONDecodeError, ValueError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    raise
                await self._sleep_before_retry(attempt)
        if last_exc:
            raise last_exc
        raise ValueError("model response was not a JSON object")

    async def complete_text(
        self,
        *,
        model: str,
        system: str,
        payload: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 1400,
        reasoning_effort: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        request_body = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": _system_with_default_language(system, model)},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        }
        if _needs_streaming_chat(self.base_url, model):
            request_body["stream"] = True
        if reasoning_effort:
            request_body["reasoning_effort"] = reasoning_effort
        if tools:
            request_body["tools"] = tools
        if tool_choice:
            request_body["tool_choice"] = tool_choice
        if response_format:
            request_body["response_format"] = response_format
        last_exc: Exception | None = None
        attempt = 0
        while attempt <= self.max_retries:
            try:
                response = await self.http_client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=timeout,
                    json=request_body,
                )
                response.raise_for_status()
                response_payload = _response_json_or_sse_payload(response)
                content = _message_content(response_payload)
                if not content and tools:
                    content = _tool_calls_content(response_payload)
                if not content:
                    raise ValueError("model response content was empty")
                return content
            except Exception as exc:
                last_exc = exc
                if _is_unsupported_token_limit_error(exc) and "max_tokens" in request_body:
                    request_body.pop("max_tokens", None)
                    continue
                if attempt >= self.max_retries or not _is_retryable_llm_error(exc):
                    raise
                attempt += 1
                await self._sleep_before_retry(attempt)
        if last_exc:
            raise last_exc
        raise ValueError("model response content was empty")

    async def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_base_delay <= 0:
            return
        await asyncio.sleep(self.retry_base_delay * (2**attempt))


def _system_with_default_language(system: str, model: str) -> str:
    text = str(system or "").strip()
    if not _needs_simplified_chinese_default(model):
        return text
    directive = "默认使用简体中文回答；除非用户明确要求其他语言，所有自然语言输出都使用简体中文。"
    if directive in text or "默认使用简体中文回答" in text:
        return text
    return f"{text}\n{directive}" if text else directive


def _needs_simplified_chinese_default(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("gpt-5.5") or "/gpt-5.5" in normalized


def _needs_streaming_chat(base_url: str, model: str) -> bool:
    normalized_base = str(base_url or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    return "zzshu.cc" in normalized_base and (
        normalized_model.startswith("gpt-") or "/gpt-" in normalized_model
    )


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()


def _response_json_or_sse_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return _chat_payload_from_sse(response.text)


def _chat_payload_from_sse(text: str) -> dict[str, Any]:
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or choice.get("message") or {}
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            if isinstance(content, str):
                content_parts.append(content)
            _merge_streaming_tool_calls(tool_calls_by_index, delta.get("tool_calls"))
    tool_calls = [
        tool_calls_by_index[index]
        for index in sorted(tool_calls_by_index)
        if tool_calls_by_index[index].get("function", {}).get("name")
    ]
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_calls:
        message["content"] = message["content"] or None
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def _merge_streaming_tool_calls(
    tool_calls_by_index: dict[int, dict[str, Any]],
    delta_tool_calls: Any,
) -> None:
    if not isinstance(delta_tool_calls, list):
        return
    for item in delta_tool_calls:
        if not isinstance(item, dict):
            continue
        index = int(item.get("index") or 0)
        existing = tool_calls_by_index.setdefault(
            index,
            {
                "id": item.get("id") or f"call_{index}",
                "type": item.get("type") or "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if item.get("id"):
            existing["id"] = item["id"]
        if item.get("type"):
            existing["type"] = item["type"]
        function_delta = item.get("function")
        if not isinstance(function_delta, dict):
            continue
        function = existing.setdefault("function", {"name": "", "arguments": ""})
        if function_delta.get("name"):
            function["name"] = str(function_delta["name"])
        if function_delta.get("arguments"):
            function["arguments"] = str(function.get("arguments") or "") + str(function_delta["arguments"])


def _tool_calls_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return ""
    requested: list[dict[str, Any]] = []
    names: list[str] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        raw_arguments = function.get("arguments")
        arguments: dict[str, Any] = {}
        if isinstance(raw_arguments, str) and raw_arguments.strip():
            try:
                parsed = json.loads(raw_arguments)
                if isinstance(parsed, dict):
                    arguments = parsed
            except json.JSONDecodeError:
                arguments = {"raw_arguments": raw_arguments}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        names.append(name)
        requested.append({"name": name, "arguments": arguments, "required": True})
    if not requested:
        return ""
    answer_mode = "answer_only"
    if "route_lookup" in names:
        answer_mode = "route_map"
    elif any(name in {"serper_places", "serper_images"} for name in names):
        answer_mode = "place_cards"
    return json.dumps(
        {
            "answer_mode": answer_mode,
            "sections": [],
            "tool_calls_requested": requested,
            "cards": [],
            "map_pins": [],
            "itinerary_plan": {},
            "route_options": [],
            "hotel_offers": [],
            "flight_offers": [],
            "warnings": [],
            "data_gaps": [],
        },
        ensure_ascii=False,
    )


def _is_retryable_llm_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            json.JSONDecodeError,
        ),
    ):
        return True
    if isinstance(exc, ValueError) and "empty" in str(exc).lower():
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504, 529}
    return False


def _is_unsupported_token_limit_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    if exc.response.status_code != 400:
        return False
    try:
        body = exc.response.json()
    except json.JSONDecodeError:
        body = exc.response.text
    text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    lowered = text.lower()
    return "unsupported parameter" in lowered and (
        "max_output_tokens" in lowered
        or "max_tokens" in lowered
        or "max_completion_tokens" in lowered
    )


def parse_jsonish(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        candidate = _first_balanced_json_object(text)
        if candidate is None:
            raise
        return json.loads(candidate)


def _first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
