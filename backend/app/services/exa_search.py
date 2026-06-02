from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.schemas.travel import EvidenceSearchRequest, TravelPlanRequest, TravelSuggestionGroup
from app.schemas.visual import EvidenceCard, PlaceCandidate
from app.services.ad_filter import ad_risk_score


def build_travel_search_query(request: TravelPlanRequest) -> str:
    interests = " ".join(request.interest_tags[:4])
    avoid = " ".join(request.avoid + request.constraints)
    return " ".join(
        part
        for part in [
            request.city,
            request.query or request.question,
            interests,
            avoid,
            "reddit local forum hidden gems real traveler no sponsored",
        ]
        if part
    )


class ExaSearchClient:
    """Small async wrapper around Exa Search API.

    The implementation uses the HTTP API directly to avoid adding a hard SDK
    dependency. Exa's current docs recommend `type=auto` and highlights for
    first integrations, which matches our evidence-card workflow.
    """

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.exa.ai",
        timeout_seconds: float = 8,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        response = await self.http_client.post(
            f"{self.base_url}/search",
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "type": "auto",
                "numResults": max(1, min(max_results, 10)),
                "contents": {"highlights": True},
                "maxAgeHours": 24 * 30,
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results")
        return results if isinstance(results, list) else []


class EvidenceSearchService:
    """Turns Exa search results into transient POI candidates and audit runs."""

    def __init__(self, client: ExaSearchClient) -> None:
        self.client = client
        self._runs: list[dict[str, Any]] = []

    async def search(
        self,
        request: TravelPlanRequest | EvidenceSearchRequest,
        trigger_reason: str,
    ) -> dict[str, Any]:
        query = (
            build_travel_search_query(request)
            if isinstance(request, TravelPlanRequest)
            else self._manual_query(request)
        )
        run = {
            "query": query,
            "city": request.city,
            "trigger_reason": trigger_reason,
            "status": "running",
            "result_count": 0,
            "imported_count": 0,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._runs.append(run)
        try:
            raw_results = await self.client.search(
                query=query,
                max_results=getattr(request, "max_results", 5),
            )
            candidates = self._results_to_candidates(
                raw_results,
                city=request.city,
                interest_tags=getattr(request, "interest_tags", []),
            )
            run["status"] = "completed"
            run["result_count"] = len(raw_results)
            run["imported_count"] = len(candidates)
            data_gaps = [] if candidates else ["联网搜索没有返回足够可用的 POI 证据。"]
            return {
                "search_used": True,
                "search_queries": [query],
                "sources_consulted": [
                    item["url"]
                    for item in raw_results
                    if isinstance(item.get("url"), str)
                ],
                "data_gaps": data_gaps,
                "evidence_freshness": "fresh" if candidates else "insufficient",
                "candidates": candidates,
            }
        except Exception as exc:
            run["status"] = "failed"
            run["error"] = exc.__class__.__name__
            return {
                "search_used": True,
                "search_queries": [query],
                "sources_consulted": [],
                "data_gaps": [f"联网搜索失败：{exc.__class__.__name__}"],
                "evidence_freshness": "search_failed",
                "candidates": [],
            }

    async def list_runs(self) -> list[dict[str, Any]]:
        return list(reversed(self._runs))

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
        groups = []
        for fallback, result in zip(fallback_groups, results, strict=True):
            if isinstance(result, TravelSuggestionGroup):
                groups.append(result)
            else:
                groups.append(fallback)
        return groups

    async def _suggestion_group(
        self,
        request: TravelPlanRequest,
        group: TravelSuggestionGroup,
    ) -> TravelSuggestionGroup:
        query = (
            f"{request.city} {group.title} travel recommendations top places "
            "local traveler practical"
        )
        raw_results = await self.client.search(query=query, max_results=5)
        items = _results_to_suggestion_items(raw_results)
        if len(items) < 3:
            return group
        self._runs.append(
            {
                "query": query,
                "city": request.city,
                "trigger_reason": f"suggestion_group:{group.title}",
                "status": "completed",
                "result_count": len(raw_results),
                "imported_count": 0,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return group.model_copy(
            update={
                "items": items[:5],
                "reason": f"来自 API 的 {group.title} 前几个候选；需要进一步按你的兴趣和路线取舍。",
                "evidence_needed": False,
            }
        )

    @staticmethod
    def _manual_query(request: EvidenceSearchRequest) -> str:
        return " ".join(
            part
            for part in [
                request.city,
                request.query,
                " ".join(request.interest_tags),
                "reddit local forum official travel evidence",
            ]
            if part
        )

    @staticmethod
    def _results_to_candidates(
        raw_results: list[dict[str, Any]],
        *,
        city: str,
        interest_tags: list[str],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for index, result in enumerate(raw_results[:5], start=1):
            url = str(result.get("url") or "")
            title = str(result.get("title") or "Untitled travel evidence").strip()
            highlights = result.get("highlights")
            if isinstance(highlights, list) and highlights:
                snippet = " ".join(str(item).strip() for item in highlights[:2])
            else:
                snippet = str(result.get("summary") or title).strip()
            if not snippet:
                continue
            source_type, source_name = _source_from_url(url)
            evidence = EvidenceCard(
                source_type=source_type,
                title=title[:500],
                snippet=snippet[:1000],
                url=url or None,
                score=_source_score(source_type),
                ad_risk=_ad_risk(source_type, url, title, snippet),
                local_signal=_local_signal(source_type, snippet),
                tourist_signal=_tourist_signal(title, snippet),
                metadata={"city": city, "source_name": source_name},
            )
            place = PlaceCandidate(
                place_id=-index,
                name=_candidate_name(title),
                name_ja=None,
                category=_category_from_text(title, snippet),
                confidence=0.58,
                match_reason="exa evidence search",
                tags=sorted(set(interest_tags + _tags_from_text(title, snippet))),
                photo_potential=0.55,
            )
            candidates.append({"place": place, "evidence_cards": [evidence]})
        return candidates


def _source_from_url(url: str) -> tuple[str, str]:
    domain = urlparse(url).netloc.lower()
    if "reddit.com" in domain:
        return "reddit", domain or "reddit"
    if "tripadvisor" in domain or "google" in domain:
        return "review", domain
    if domain.endswith(".go.jp") or "official" in domain:
        return "official", domain
    if domain:
        return "web", domain
    return "web", "unknown"


def _candidate_name(title: str) -> str:
    cleaned = title.split("|")[0].split("-")[0].strip()
    return cleaned[:120] or "Exa travel candidate"


def _results_to_suggestion_items(raw_results: list[dict[str, Any]]) -> list[str]:
    items = []
    seen = set()
    for result in raw_results:
        title = str(result.get("title") or "").strip()
        name = _candidate_name(title)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        items.append(name)
        if len(items) >= 5:
            break
    return items


def _category_from_text(title: str, snippet: str) -> str:
    text = f"{title} {snippet}".lower()
    if any(word in text for word in ["restaurant", "food", "ramen", "sushi", "yatai"]):
        return "food"
    if any(word in text for word in ["temple", "shrine", "寺", "神社"]):
        return "temple"
    if any(word in text for word in ["mount", "hike", "trail", "山"]):
        return "mountain"
    return "place"


def _tags_from_text(title: str, snippet: str) -> list[str]:
    text = f"{title} {snippet}".lower()
    tags = []
    for word in ["local", "quiet", "food", "history", "garden", "night", "hike"]:
        if word in text:
            tags.append(word)
    if "hidden" in text:
        tags.append("hidden")
    return tags


def _source_score(source_type: str) -> float:
    return {
        "official": 0.82,
        "reddit": 0.74,
        "review": 0.68,
        "web": 0.58,
    }.get(source_type, 0.55)


def _ad_risk(source_type: str, url: str, title: str, snippet: str) -> float:
    return ad_risk_score(
        url=url,
        title=title,
        snippet=snippet,
        base_risk={"official": 0.05, "reddit": 0.03, "review": 0.18}.get(
            source_type, 0.18
        ),
    )


def _local_signal(source_type: str, snippet: str) -> float:
    text = snippet.lower()
    if "local" in text or "locals" in text or "本地" in text:
        return 0.68
    return {"reddit": 0.56, "official": 0.35, "review": 0.42}.get(source_type, 0.34)


def _tourist_signal(title: str, snippet: str) -> float:
    text = f"{title} {snippet}".lower()
    if any(word in text for word in ["crowd", "tourist", "queue", "busy", "游客"]):
        return 0.78
    return 0.42
