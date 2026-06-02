from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.schemas.visual import EvidenceCard, VisualExploreInput


class SerperOfficialHistoryClient:
    """Lightweight official-source history enrichment for visual discoveries."""

    provider_name = "serper_official_history"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://google.serper.dev",
        timeout_seconds: float = 8,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def enrich(
        self,
        request: VisualExploreInput,
        visual_reasoning: dict[str, Any],
    ) -> dict[str, Any]:
        if not _should_enrich_history(request, visual_reasoning):
            return {}
        target = _history_target(request, visual_reasoning)
        if not target:
            return {}
        query = _history_query(target)
        response = await self.http_client.post(
            f"{self.base_url}/search",
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "q": query,
                "gl": "jp",
                "hl": "zh-cn",
                "location": "Japan",
                "num": 8,
                "autocorrect": True,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        source = _best_official_source(_list_of_dicts(payload.get("organic")))
        if not source:
            return {}
        summary = _history_summary(source)
        card = EvidenceCard(
            source_type="official_history",
            title=source["title"],
            snippet=summary,
            url=source["url"],
            score=0.86,
            local_signal=0.8,
            metadata={"provider": self.provider_name, "query": query},
        )
        return {
            "meaning_layers": {"cultural_history": summary},
            "official_history_sources": [source | {"query": query}],
            "confidence_notes": [f"历史补全使用官方来源：{source['title']}"],
            "evidence_cards": [card],
        }


def _should_enrich_history(
    request: VisualExploreInput,
    visual_reasoning: dict[str, Any],
) -> bool:
    focus = request.exploration_focus.strip().lower()
    combined = " ".join(
        [
            focus,
            request.user_context_text,
            " ".join(request.interest_tags),
            str(visual_reasoning.get("subject") or ""),
            " ".join(str(item) for item in visual_reasoning.get("place_candidates") or []),
            _hypothesis_text(visual_reasoning),
        ]
    ).lower()
    explicit_history = any(
        token in combined
        for token in [
            "history",
            "historical",
            "heritage",
            "origin",
            "founder",
            "founded",
            "created",
            "历史",
            "歷史",
            "由来",
            "由緒",
            "起源",
            "创建",
            "創建",
            "谁创建",
            "誰創建",
            "沿革",
        ]
    )
    historic_subject = any(
        token in combined
        for token in [
            "temple",
            "shrine",
            "castle",
            "landmark",
            "monzeki",
            "heritage",
            "寺",
            "神社",
            "城",
            "跡",
            "門跡",
            "地标",
            "古迹",
            "遗产",
        ]
    )
    return explicit_history or (focus in {"auto", ""} and historic_subject)


def _history_target(
    request: VisualExploreInput,
    visual_reasoning: dict[str, Any],
) -> str:
    parts: list[str] = []
    subject = str(visual_reasoning.get("subject") or "").strip()
    if subject and not subject.lower().startswith("unknown"):
        parts.append(subject)
    for candidate in visual_reasoning.get("place_candidates") or []:
        text = str(candidate or "").strip()
        if text and text not in parts:
            parts.append(text)
        if len(parts) >= 2:
            break
    if not parts:
        context = request.user_context_text.strip()
        if context:
            parts.append(context[:80])
    return " ".join(parts).strip()


def _history_query(target: str) -> str:
    return f"{target} official history origin founder 公式 歴史 由緒 創建"


def _best_official_source(items: list[dict[str, Any]]) -> dict[str, str] | None:
    scored: list[tuple[int, dict[str, str]]] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        url = str(item.get("link") or item.get("url") or "").strip()
        snippet = str(item.get("snippet") or item.get("description") or "").strip()
        if not title or not url or _is_blocked_source(url):
            continue
        text = f"{title} {url} {snippet}".lower()
        score = 0
        for token in ["official", "公式", "official site", "官网", "官方网站"]:
            if token in text:
                score += 5
        for token in ["history", "historical", "origin", "founded", "founder", "由緒", "沿革", "創建", "创建", "歴史", "历史"]:
            if token.lower() in text:
                score += 2
        domain = urlparse(url).netloc.lower()
        if domain.endswith(".go.jp") or ".city." in domain or ".pref." in domain:
            score += 4
        if score <= 0:
            continue
        scored.append((score, {"title": title, "url": url, "snippet": snippet}))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _history_summary(source: dict[str, str]) -> str:
    snippet = source.get("snippet", "").strip()
    title = source.get("title", "").strip()
    if snippet:
        return snippet
    return f"官方历史来源：{title}。"


def _is_blocked_source(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    blocked = [
        "wikipedia.org",
        "wikivoyage.org",
        "tripadvisor.",
        "booking.",
        "expedia.",
        "agoda.",
        "klook.",
        "reddit.",
        "facebook.",
        "instagram.",
        "tiktok.",
        "x.com",
        "twitter.",
        "youtube.",
    ]
    return any(token in domain for token in blocked)


def _hypothesis_text(visual_reasoning: dict[str, Any]) -> str:
    values: list[str] = []
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict):
                values.extend(str(item.get(key) or "") for key in ["name", "entity_type", "region", "rationale"])
    return " ".join(values)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
