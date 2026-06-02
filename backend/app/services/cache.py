from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from app.schemas.visual import VisualExploreResponse


TModel = TypeVar("TModel", bound=BaseModel)


class RedisJsonCache:
    """Redis TTL cache using Pydantic JSON payloads, with an in-process fallback."""

    def __init__(
        self,
        redis_url: str,
        model_cls: type[TModel],
        *,
        namespace: str,
        ttl_seconds: int = 900,
    ) -> None:
        self.redis_url = redis_url
        self.model_cls = model_cls
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self._client: Any | None = None
        self._redis_available: bool | None = None
        self._fallback: dict[str, TModel] = {}

    async def get(self, key: str) -> TModel | None:
        redis_key = self._redis_key(key)
        client = await self._get_client()
        if client is not None:
            try:
                payload = await client.get(redis_key)
                if payload is None:
                    return None
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                return self.model_cls.model_validate_json(payload)
            except Exception:
                self._redis_available = False
        return self._fallback.get(redis_key)

    async def put(self, key: str, value: TModel) -> None:
        redis_key = self._redis_key(key)
        client = await self._get_client()
        if client is not None:
            try:
                await client.setex(redis_key, self.ttl_seconds, value.model_dump_json())
                return
            except Exception:
                self._redis_available = False
        self._fallback[redis_key] = value

    async def _get_client(self) -> Any | None:
        if self._redis_available is False:
            return None
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as redis_async

            self._client = redis_async.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            self._redis_available = True
            return self._client
        except Exception:
            self._redis_available = False
            return None

    def _redis_key(self, key: str) -> str:
        return f"{self.namespace}:{key}"


class InMemorySnapCache:
    """Simple async cache for self-use/dev runs; MySQL-backed cache can replace it."""

    def __init__(self) -> None:
        self._items: dict[str, VisualExploreResponse] = {}

    async def get(self, key: str) -> VisualExploreResponse | None:
        return self._items.get(key)

    async def put(self, key: str, value: VisualExploreResponse) -> None:
        self._items[key] = value
