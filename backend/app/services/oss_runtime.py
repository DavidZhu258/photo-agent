from __future__ import annotations

from importlib.util import find_spec


def provider_runtime_refs(scope: str) -> dict[str, object]:
    """Describe the open-source runtime adapters the thin API layer targets."""

    return {
        "haystack_pipeline": {
            "adapter": "haystack.Pipeline",
            "format": "Pipeline",
            "scope": scope,
            "installed": _has_module("haystack"),
            "docs": "https://docs.haystack.deepset.ai/",
        },
        "pydantic_ai": {
            "adapter": "pydantic_ai.Agent",
            "format": "Agent + structured output schema",
            "scope": scope,
            "installed": _has_module("pydantic_ai"),
            "docs": "https://ai.pydantic.dev/",
        },
        "litellm": {
            "adapter": "LiteLLM Proxy / OpenAI-compatible client",
            "format": "chat/completions",
            "installed": _has_module("litellm"),
            "docs": "https://github.com/BerriAI/litellm",
        },
        "redis": {
            "adapter": "redis.asyncio",
            "format": "JSON TTL cache key",
            "installed": _has_module("redis"),
            "docs": "https://github.com/redis/redis",
        },
        "langfuse": {
            "adapter": "langfuse client trace/session/observation",
            "format": "trace",
            "installed": _has_module("langfuse"),
            "docs": "https://github.com/langfuse/langfuse",
        },
    }


def _has_module(module_name: str) -> bool:
    return find_spec(module_name) is not None
