from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas.travel import (
    TravelPlanRequest,
    TravelRecommendation,
    TravelSuggestionGroup,
)


class DeepInfraTravelDecisionClient:
    """OpenAI-compatible DeepInfra client for bounded travel decision synthesis."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str = "https://api.deepinfra.com/v1/openai",
        timeout_seconds: float = 1.5,
        http_client: httpx.AsyncClient | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or settings.travel_decision_model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = (
            settings.travel_model_reasoning_effort
            if reasoning_effort is None
            else reasoning_effort
        )
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def decide(
        self,
        request: TravelPlanRequest,
        recommendations: list[TravelRecommendation],
        suggestion_groups: list[TravelSuggestionGroup] | None = None,
    ) -> dict[str, Any]:
        payload = self._build_payload(request, recommendations, suggestion_groups or [])
        response = await self.http_client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _parse_json_object(content)
        return _normalize_decision(parsed)

    def _build_payload(
        self,
        request: TravelPlanRequest,
        recommendations: list[TravelRecommendation],
        suggestion_groups: list[TravelSuggestionGroup],
    ) -> dict[str, Any]:
        compact_recommendations = [
            {
                "place_id": item.place.place_id,
                "name": item.place.name,
                "name_ja": item.place.name_ja,
                "category": item.place.category,
                "score": item.score,
                "algorithm_reasons": item.reasons,
                "algorithm_caution": item.caution,
                "ad_risk_label": item.ad_risk_label,
                "tags": item.place.tags,
                "evidence_cards": [
                    {
                        "source_type": card.source_type,
                        "title": card.title,
                        "snippet": card.snippet,
                        "score": card.score,
                        "ad_risk": card.ad_risk,
                        "local_signal": card.local_signal,
                        "tourist_signal": card.tourist_signal,
                    }
                    for card in item.evidence_cards[:4]
                ],
            }
            for item in recommendations
        ]
        compact_groups = [
            {
                "title": group.title,
                "intent": group.intent,
                "items": group.items,
                "reason": group.reason,
            }
            for group in suggestion_groups
        ]
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a transparent travel decision agent. Use only the "
                        "provided evidence and algorithm scores when evidence is provided. "
                        "Do not force evidence into framework, logistics, preference, or "
                        "planning-style answers that do not need external proof. Never invent sources, "
                        "never promote sponsored content, and be willing to say "
                        "not_recommended when a place conflicts with the user's interests. "
                        "When suggestion_groups are provided, keep the exact group titles "
                        "and order as the answer framework: 美食, 购物, 历史文化, 本地体验, "
                        "购物与街区, 自然与摄影. Each group must stay inside 3-5 items. "
                        "Return concise Chinese. Output strict JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": (
                                "After deterministic ranking, make a decision for the user. "
                                "For each place give decision one of recommended, conditional, "
                                "not_recommended, insufficient_evidence; include pros, cons, "
                                "decision_reason, and caution. Keep evidence cards unchanged. "
                                "If suggestion_groups are present, write summary and notes "
                                "around that framework before individual POI decisions."
                            ),
                            "request": request.model_dump(mode="json"),
                            "suggestion_groups": compact_groups,
                            "ranked_candidates": compact_recommendations,
                            "required_json_schema": {
                                "summary": "string",
                                "decision_notes": ["string"],
                                "uncertainty": ["string"],
                                "needs_user_confirmation": "boolean",
                                "recommendations": [
                                    {
                                        "place_id": "integer|null",
                                        "place_name": "string",
                                        "decision": (
                                            "recommended|conditional|not_recommended|"
                                            "insufficient_evidence"
                                        ),
                                        "decision_reason": "string",
                                        "pros": ["string"],
                                        "cons": ["string"],
                                        "caution": "string",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    return parsed if isinstance(parsed, dict) else {}


def _normalize_decision(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(parsed.get("summary") or "").strip(),
        "decision_notes": _string_list(parsed.get("decision_notes")),
        "uncertainty": _string_list(parsed.get("uncertainty")),
        "needs_user_confirmation": bool(parsed.get("needs_user_confirmation", True)),
        "recommendations": [
            _normalize_recommendation(item)
            for item in _list_of_dicts(parsed.get("recommendations"))
        ],
    }


def _normalize_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    decision = str(item.get("decision") or "conditional").strip().lower()
    if decision not in {
        "recommended",
        "conditional",
        "not_recommended",
        "insufficient_evidence",
    }:
        decision = "conditional"
    place_id = item.get("place_id")
    return {
        "place_id": place_id if isinstance(place_id, int) else None,
        "place_name": str(item.get("place_name") or item.get("name") or "").strip(),
        "decision": decision,
        "decision_reason": str(item.get("decision_reason") or "").strip(),
        "pros": _string_list(item.get("pros")),
        "cons": _string_list(item.get("cons")),
        "caution": str(item.get("caution") or "").strip(),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
