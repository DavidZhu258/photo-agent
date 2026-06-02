from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.schemas.travel import TravelPlanRequest, TravelSuggestionGroup
from app.services.ad_filter import is_commercially_risky


class TabijiClient:
    """Small client for Tabiji's no-key travel recommendation API."""

    def __init__(
        self,
        base_url: str = "https://tabiji.ai/api/v1",
        timeout_seconds: float = 6,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def recommend(
        self,
        *,
        intent: str,
        location: str,
        preferences: dict[str, Any],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        response = await self.http_client.get(
            f"{self.base_url}/search.json",
            params={
                "q": _search_query(intent, location, preferences),
                "type": "pick",
                "limit": max(8, min(limit * 4, 20)),
            },
        )
        response.raise_for_status()
        return _payload_items(response.json())


class TrustedTravelSuggestionService:
    """Builds broad suggestions from ad-light APIs before falling back locally."""

    source_name = "api"

    def __init__(
        self,
        tabiji_client: object,
        fallback_service: object | None = None,
    ) -> None:
        self.tabiji_client = tabiji_client
        self.fallback_service = fallback_service

    async def suggestion_groups(
        self,
        request: TravelPlanRequest,
        fallback_groups: list[TravelSuggestionGroup],
    ) -> list[TravelSuggestionGroup]:
        tasks = [
            self._suggestion_group(request, group)
            for group in fallback_groups
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        groups: list[TravelSuggestionGroup] = []
        for fallback, result in zip(fallback_groups, results, strict=True):
            groups.append(result if isinstance(result, TravelSuggestionGroup) else fallback)
        fallback_provider = getattr(self.fallback_service, "suggestion_groups", None)
        if callable(fallback_provider) and any(
            group is fallback
            for group, fallback in zip(groups, fallback_groups, strict=True)
        ):
            fallback_api_groups = await fallback_provider(request, fallback_groups)
            groups = [
                fallback_api if group is fallback else group
                for group, fallback, fallback_api in zip(
                    groups,
                    fallback_groups,
                    fallback_api_groups,
                    strict=True,
                )
            ]
        return groups

    async def _suggestion_group(
        self,
        request: TravelPlanRequest,
        group: TravelSuggestionGroup,
    ) -> TravelSuggestionGroup:
        raw_items = await self.tabiji_client.recommend(
            intent=_intent_for_group(group),
            location=request.city,
            preferences={
                "atmosphere": ["local_feeling", "practical"],
                "avoid": ["touristy", "sponsored", "affiliate"],
                "category": group.title,
            },
            limit=5,
        )
        items = _safe_item_names(raw_items, location=request.city)
        if len(items) < 3:
            return group
        return group.model_copy(
            update={
                "items": items[:5],
                "reason": (
                    f"来自 Tabiji/API 的 {group.title} 前几个候选；已过滤订票、"
                    "affiliate 和明显商单导流来源。"
                ),
                "evidence_needed": False,
            }
        )


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ["items", "recommendations", "results", "places"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        return _payload_items(data)
    return []


def _intent_for_group(group: TravelSuggestionGroup) -> str:
    return {
        "美食": "local_food_not_sponsored",
        "购物": "local_shopping_no_tourist_traps",
        "历史文化": "deep_culture_history",
        "本地体验": "local_experiences_authentic",
        "购物与街区": "walkable_neighborhoods_and_shopping",
        "自然与摄影": "nature_photography_route_practical",
    }.get(group.title, group.title)


def _search_query(intent: str, location: str, preferences: dict[str, Any]) -> str:
    category = str(preferences.get("category") or "").strip()
    return " ".join(
        part
        for part in [
            location,
            category,
            intent.replace("_", " "),
            "local traveler reddit practical",
        ]
        if part
    )


def _safe_item_names(raw_items: list[dict[str, Any]], *, location: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        name = str(item.get("name") or item.get("title") or item.get("place") or "").strip()
        if not name:
            continue
        url = str(item.get("url") or item.get("mapsUrl") or item.get("website") or "")
        snippet = str(item.get("description") or item.get("summary") or item.get("reason") or "")
        provenance = _provenance_sources(item.get("provenance"))
        if not _matches_location(item, location):
            continue
        if is_commercially_risky(
            url=url,
            title=name,
            snippet=snippet,
            provenance=provenance,
        ):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name[:120])
        if len(names) >= 5:
            break
    return names


def _matches_location(item: dict[str, Any], location: str) -> bool:
    location_text = location.lower().replace("-", " ")
    haystack_parts = [
        item.get("name"),
        item.get("title"),
        item.get("subtitle"),
        item.get("url"),
        item.get("siteUrl"),
        item.get("slug"),
        item.get("region"),
    ]
    tags = item.get("tags")
    if isinstance(tags, list):
        haystack_parts.extend(tags)
    haystack = " ".join(
        str(part).lower().replace("-", " ")
        for part in haystack_parts
        if part
    )
    return location_text in haystack


def _provenance_sources(value: Any) -> list[str]:
    if isinstance(value, dict):
        sources = value.get("sources")
        if isinstance(sources, list):
            return [str(source) for source in sources]
        return [str(item) for item in value.values()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
