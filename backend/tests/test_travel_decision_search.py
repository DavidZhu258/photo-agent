from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.travel import TravelPlanRequest
from app.schemas.visual import EvidenceCard, PlaceCandidate
from app.services.travel_planner import LightweightTravelPlanner


class EmptyCatalog:
    async def search(self, query="", city=None, interest_tags=None):
        return []

    async def list_places(self, city=None, query=None):
        return []

    async def get_place(self, place_id):
        return None

    async def evidence_for(self, place_id):
        return []


class MountainCatalog:
    async def search(self, query="", city=None, interest_tags=None):
        return [
            PlaceCandidate(
                place_id=501,
                name="Mount Misen",
                name_ja="弥山",
                category="mountain",
                lat=34.2799,
                lng=132.3196,
                confidence=0.8,
                tags=["mountain", "hike", "view"],
                photo_potential=0.85,
            )
        ]

    async def list_places(self, city=None, query=None):
        return await self.search(query=query, city=city)

    async def get_place(self, place_id):
        return (await self.search())[0]

    async def evidence_for(self, place_id):
        return [
            EvidenceCard(
                source_type="community",
                title="Late arrival hiking warning",
                snippet="Travelers say the summit needs enough daylight and descent time.",
                score=0.78,
                local_signal=0.55,
                tourist_signal=0.4,
            )
        ]


class FakeEvidenceSearch:
    def __init__(self):
        self.calls = []
        self.suggestion_calls = []
        self.runs = []

    async def search(self, request, trigger_reason):
        self.calls.append((request, trigger_reason))
        self.runs.append(
            {
                "query": "Fukuoka quiet local food reddit",
                "city": request.city,
                "trigger_reason": trigger_reason,
                "status": "completed",
                "result_count": 1,
                "imported_count": 1,
            }
        )
        return {
            "search_used": True,
            "search_queries": ["Fukuoka quiet local food reddit"],
            "sources_consulted": ["https://www.reddit.com/r/JapanTravel/example"],
            "data_gaps": [],
            "evidence_freshness": "fresh",
            "candidates": [
                {
                    "place": PlaceCandidate(
                        place_id=-1,
                        name="Yatai Side Street",
                        name_ja="屋台の路地",
                        category="food",
                        lat=33.5902,
                        lng=130.4017,
                        confidence=0.62,
                        match_reason="exa evidence",
                        tags=["food", "local", "night"],
                        photo_potential=0.66,
                    ),
                    "evidence_cards": [
                        EvidenceCard(
                            source_type="reddit",
                            title="Local-feeling yatai discussion",
                            snippet="Multiple travelers mention small side streets instead of the busiest stalls.",
                            url="https://www.reddit.com/r/JapanTravel/example",
                            score=0.74,
                            ad_risk=0.03,
                            local_signal=0.66,
                            tourist_signal=0.45,
                        )
                    ],
                }
            ],
        }

    async def list_runs(self):
        return self.runs

    async def suggestion_groups(self, request, fallback_groups):
        self.suggestion_calls.append(request)
        return [
            group.model_copy(
                update={
                    "items": [
                        f"API {group.title} 1",
                        f"API {group.title} 2",
                        f"API {group.title} 3",
                    ],
                    "reason": f"来自 API 的 {group.title} 前几个候选。",
                }
            )
            for group in fallback_groups
        ]


@pytest.mark.asyncio
async def test_planner_triggers_web_search_when_local_evidence_is_insufficient():
    evidence_search = FakeEvidenceSearch()
    planner = LightweightTravelPlanner(
        place_catalog=EmptyCatalog(),
        evidence_search=evidence_search,
    )

    response = await planner.plan(
        TravelPlanRequest(
            query="福冈 12:00 到，想吃本地人也认可的东西",
            city="Fukuoka",
            interest_tags=["food", "local"],
            allow_web_search=True,
        )
    )

    assert evidence_search.calls
    assert response.search_used is True
    assert response.search_queries == ["Fukuoka quiet local food reddit"]
    assert response.sources_consulted == [
        "https://www.reddit.com/r/JapanTravel/example"
    ]
    assert response.recommendations[0].place.name_ja == "屋台の路地"
    assert response.evidence_cards[0].source_type == "reddit"


@pytest.mark.asyncio
async def test_planner_cache_only_does_not_call_web_search():
    evidence_search = FakeEvidenceSearch()
    planner = LightweightTravelPlanner(
        place_catalog=EmptyCatalog(),
        evidence_search=evidence_search,
    )

    response = await planner.plan(
        TravelPlanRequest(
            query="福冈有什么真实推荐？",
            city="Fukuoka",
            evidence_refresh="cache_only",
        )
    )

    assert evidence_search.calls == []
    assert response.search_used is False
    assert response.needs_user_confirmation is True
    assert "证据不足" in response.data_gaps[0]


@pytest.mark.asyncio
async def test_planner_returns_broad_suggestion_groups_when_request_is_generic():
    evidence_search = FakeEvidenceSearch()
    planner = LightweightTravelPlanner(
        place_catalog=EmptyCatalog(),
        evidence_search=evidence_search,
    )

    response = await planner.plan(
        TravelPlanRequest(
            query="第一次去福冈，帮我安排一下",
            city="Fukuoka",
            allow_web_search=True,
        )
    )

    assert evidence_search.calls == []
    assert len(evidence_search.suggestion_calls) == 1
    assert response.search_used is False
    assert response.suggestion_source == "api"
    assert response.evidence_cards == []
    assert response.data_gaps == []
    assert [group.title for group in response.suggestion_groups] == [
        "美食",
        "购物",
        "历史文化",
        "本地体验",
        "购物与街区",
        "自然与摄影",
    ]
    for group in response.suggestion_groups:
        assert 3 <= len(group.items) <= 5
        assert group.items[0].startswith("API ")
    assert response.needs_user_confirmation is True


@pytest.mark.asyncio
async def test_planner_uses_local_framework_when_api_suggestions_are_unavailable():
    planner = LightweightTravelPlanner(
        place_catalog=EmptyCatalog(),
        evidence_search=object(),
    )

    response = await planner.plan(
        TravelPlanRequest(
            query="第一次去福冈，帮我安排一下",
            city="Fukuoka",
            allow_web_search=True,
        )
    )

    assert response.suggestion_source == "fallback"
    assert response.search_used is False
    assert response.suggestion_groups[0].items[0] == "Fukuoka 本地人常去的早餐/午餐"


@pytest.mark.asyncio
async def test_planner_force_refresh_still_searches_when_user_explicitly_requests_evidence():
    evidence_search = FakeEvidenceSearch()
    planner = LightweightTravelPlanner(
        place_catalog=EmptyCatalog(),
        evidence_search=evidence_search,
    )

    response = await planner.plan(
        TravelPlanRequest(
            query="福冈有哪些真实评价好的本地美食？",
            city="Fukuoka",
            evidence_refresh="force",
            allow_web_search=True,
        )
    )

    assert evidence_search.calls
    assert response.search_used is True


@pytest.mark.asyncio
async def test_planner_says_not_recommended_when_route_time_is_not_feasible():
    planner = LightweightTravelPlanner(place_catalog=MountainCatalog())

    response = await planner.plan(
        TravelPlanRequest(
            query="我 15:00 到宫岛，还建议爬山吗？",
            city="Miyajima",
            arrive_at=datetime.fromisoformat("2026-05-15T15:00:00+09:00"),
            current_location={"lat": 34.3052, "lng": 132.3183},
            interest_tags=["hike", "view"],
            transport_mode="walking",
        )
    )

    assert response.route_summary["used"] is True
    assert response.recommendations[0].decision == "not_recommended"
    assert any("时间" in item for item in response.recommendations[0].cons)
    assert response.not_recommended[0].place.name_ja == "弥山"


def test_admin_exa_search_endpoint_requires_token_and_lists_runs():
    evidence_search = FakeEvidenceSearch()
    app = create_app(
        app_settings=Settings(admin_token="local-secret"),
        evidence_search=evidence_search,
    )
    client = TestClient(app)

    unauthorized = client.post(
        "/v1/admin/evidence/search-exa",
        json={"city": "Fukuoka", "query": "local food"},
    )
    ok = client.post(
        "/v1/admin/evidence/search-exa",
        json={"city": "Fukuoka", "query": "local food"},
        headers={"X-Admin-Token": "local-secret"},
    )
    runs = client.get(
        "/v1/admin/evidence/search-runs",
        headers={"X-Admin-Token": "local-secret"},
    )

    assert unauthorized.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["search_used"] is True
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["status"] == "completed"
