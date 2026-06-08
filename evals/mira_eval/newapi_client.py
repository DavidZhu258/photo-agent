from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx


DEFAULT_NEWAPI_BASE_URL = "https://www.zzshu.cc/v1"


def parse_chat_content(body: object) -> str:
    """Extract assistant text from OpenAI-compatible JSON or SSE text."""
    if isinstance(body, str):
        stripped = body.strip()
        if stripped.startswith("data:"):
            return _parse_sse_content(stripped)
        try:
            return parse_chat_content(json.loads(stripped))
        except json.JSONDecodeError:
            return body

    if isinstance(body, Mapping):
        choices = body.get("choices")
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)):
            parts: list[str] = []
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                message = choice.get("message")
                if isinstance(message, Mapping):
                    content = message.get("content")
                    parts.extend(_content_to_text_parts(content))
                delta = choice.get("delta")
                if isinstance(delta, Mapping):
                    parts.extend(_content_to_text_parts(delta.get("content")))
                text = choice.get("text")
                parts.extend(_content_to_text_parts(text))
            return "".join(parts)
    return ""


def _parse_sse_content(raw: str) -> str:
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        chunk = parse_chat_content(parsed)
        if chunk:
            parts.append(chunk)
    return "".join(parts)


def _content_to_text_parts(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return parts
    return []


class NewApiChatClient:
    """Small OpenAI-compatible chat client for NewAPI/zzshu eval calls."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.api_key = (api_key or os.environ.get("NEWAPI_API_KEY") or "").strip()
        self.base_url = (base_url or os.environ.get("NEWAPI_BASE_URL") or DEFAULT_NEWAPI_BASE_URL).rstrip("/")
        self._http_client = http_client
        self.timeout = timeout

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str = "gpt-5.5",
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("NEWAPI_API_KEY is required for GPT eval calls.")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        should_close = self._http_client is None
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                content = parse_chat_content(response.json())
            else:
                content = parse_chat_content(response.text)
            if not content:
                raise RuntimeError("NewAPI returned empty assistant content.")
            return content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise RuntimeError(f"NewAPI chat request failed with HTTP {status}.") from exc
        finally:
            if should_close:
                await client.aclose()
