from __future__ import annotations

import pytest
import httpx

from app.schemas.travel import TravelPlanRequest, TravelSuggestionGroup
from app.services.exa_search import EvidenceSearchService
from app.services.travel_api_sources import (
    TabijiClient,
    TrustedTravelSuggestionService,
)


class FakeTabijiClient:
    def __init__(self) -> None:
        self.calls = []

    async def recommend(self, *, intent, location, preferences, limit):
        self.calls.append(
            {
                "intent": intent,
                "location": location,
                "preferences": preferences,
                "limit": limit,
            }
        )
        return [
            {
                "name": "Yanagibashi Rengo Market",
                "category": "market",
                "url": "https://tabiji.ai/popular-picks/fukuoka-market/",
                "provenance": {"sources": ["reddit", "tabiji_editorial"]},
            },
            {
                "title": "Sponsored private food tour",
                "url": "https://www.getyourguide.com/fukuoka/private-food-tour",
                "description": "Book now with affiliate discount.",
                "provenance": {"sources": ["affiliate"]},
            },
            {
                "name": "Kawabata Shopping Arcade",
                "url": "https://tabiji.ai/popular-picks/fukuoka-shopping/",
                "provenance": {"sources": ["reddit"]},
            },
            {
                "name": "Ohori Park",
                "url": "https://tabiji.ai/popular-picks/fukuoka-parks/",
                "provenance": {"sources": ["reddit", "google_places"]},
            },
            {
                "name": "Boston Food Hall",
                "url": "https://tabiji.ai/popular-picks/boston-food-hall/",
                "provenance": {"sources": ["reddit"]},
            },
        ]


def _fallback_group() -> TravelSuggestionGroup:
    return TravelSuggestionGroup(
        title="美食",
        intent="找本地人认可且广告感低的吃法。",
        items=["fallback 1", "fallback 2", "fallback 3"],
        reason="fallback",
    )


@pytest.mark.asyncio
async def test_tabiji_client_uses_static_search_endpoint_when_recommend_post_is_unavailable():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/search.json")
        assert request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "10 Best Yatai in Fukuoka",
                        "type": "pick",
                        "url": "https://tabiji.ai/popular-picks/fukuoka-yatai/",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://tabiji.test/api/v1",
    ) as http_client:
        client = TabijiClient(
            base_url="https://tabiji.test/api/v1",
            http_client=http_client,
        )
        items = await client.recommend(
            intent="local_food_not_sponsored",
            location="Fukuoka",
            preferences={"category": "美食"},
            limit=3,
        )

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert items[0]["title"] == "10 Best Yatai in Fukuoka"


@pytest.mark.asyncio
async def test_tabiji_suggestion_service_filters_commercial_items_and_keeps_group_shape():
    client = FakeTabijiClient()
    service = TrustedTravelSuggestionService(tabiji_client=client)

    groups = await service.suggestion_groups(
        TravelPlanRequest(city="Fukuoka", query="第一次去福冈，帮我安排一下"),
        [_fallback_group()],
    )

    assert client.calls[0]["location"] == "Fukuoka"
    assert groups[0].title == "美食"
    assert groups[0].items == [
        "Yanagibashi Rengo Market",
        "Kawabata Shopping Arcade",
        "Ohori Park",
    ]
    assert groups[0].evidence_needed is False
    assert "Tabiji" in groups[0].reason
    assert "Sponsored private food tour" not in groups[0].items
    assert "Boston Food Hall" not in groups[0].items


@pytest.mark.asyncio
async def test_tabiji_suggestion_service_falls_back_when_safe_items_are_too_few():
    class SparseTabijiClient:
        async def recommend(self, *, intent, location, preferences, limit):
            return [
                {
                    "name": "Only one safe pick",
                    "url": "https://tabiji.ai/example",
                    "provenance": {"sources": ["reddit"]},
                },
                {
                    "name": "Affiliate tour",
                    "url": "https://klook.com/activity/example",
                    "description": "Promo booking link.",
                    "provenance": {"sources": ["affiliate"]},
                },
            ]

    fallback = _fallback_group()
    service = TrustedTravelSuggestionService(tabiji_client=SparseTabijiClient())

    groups = await service.suggestion_groups(
        TravelPlanRequest(city="Fukuoka", query="第一次去福冈，帮我安排一下"),
        [fallback],
    )

    assert groups[0] == fallback


def test_exa_evidence_marks_commercial_booking_sources_as_high_ad_risk():
    candidates = EvidenceSearchService._results_to_candidates(
        [
            {
                "title": "Best Fukuoka Food Tours - Book Now",
                "url": "https://www.getyourguide.com/fukuoka/food-tour",
                "highlights": [
                    "Sponsored food tour with affiliate discount and limited deal."
                ],
            }
        ],
        city="Fukuoka",
        interest_tags=["food"],
    )

    evidence = candidates[0]["evidence_cards"][0]
    assert evidence.ad_risk >= 0.65
    assert evidence.local_signal < 0.5
