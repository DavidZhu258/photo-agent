from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.travel import TravelPlanRequest, TravelPlanResponse
from app.schemas.visual import ShootHint, VisualExploreResponse
from app.services.cache import RedisJsonCache
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


class FakeVisualUrlAgent:
    async def explore(self, request):
        assert request.image_url == "https://example.com/small-shrine.jpg"
        return VisualExploreResponse(
            session_id="snap_url",
            what_it_is="一张可公开访问的神社照片",
            why_it_matters="SerpAPI Google Lens 可以先找视觉匹配，VLM 再解释意义。",
            why_popular_or_overhyped="当前只标记为 API 候选，不伪造成证据。",
            related_places=[],
            shoot_hint=ShootHint(
                best_time="柔和侧光时",
                stand_where="站在鸟居侧边",
                face_where="朝向主体与背景关系",
                how_to_shoot="保留环境和入口线索",
            ),
            evidence_cards=[],
            confidence=0.5,
            needs_user_confirmation=True,
        )


@pytest.mark.asyncio
async def test_travel_plan_exposes_open_source_stack_metadata():
    planner = LightweightTravelPlanner(place_catalog=EmptyCatalog())

    response = await planner.plan(
        TravelPlanRequest(
            query="第一次去福冈，帮我安排一下",
            city="Fukuoka",
            allow_web_search=True,
        )
    )

    frameworks = {step.framework for step in response.thinking_steps}
    assert {"haystack", "pydantic_ai", "litellm", "redis", "langfuse"}.issubset(
        frameworks
    )
    assert response.cache.provider == "redis"
    assert response.category_groups == response.suggestion_groups
    assert response.raw_provider_refs["haystack_pipeline"]["format"] == "Pipeline"
    assert "Agent" in response.raw_provider_refs["pydantic_ai"]["format"]
    assert response.raw_provider_refs["redis"]["adapter"] == "redis.asyncio"
    assert response.source_breakdown["commercial_api"] >= 1
    assert not any(source.provider == "google_places" for source in response.api_sources_used)
    assert any(source.provider == "serper" for source in response.api_sources_used)
    assert "Serper.dev" in response.commercial_disclosure
    assert "DeepInfra" in response.commercial_disclosure


def test_visual_explore_accepts_image_url_and_returns_open_source_metadata():
    app = create_app(agent=FakeVisualUrlAgent())
    client = TestClient(app)

    response = client.post(
        "/v1/visual/explore",
        json={
            "image_url": "https://example.com/small-shrine.jpg",
            "user_context_text": "京都附近",
            "exploration_focus": "place",
        },
    )

    assert response.status_code == 200
    body = response.json()
    frameworks = {step["framework"] for step in body["thinking_steps"]}
    assert {"haystack", "pydantic_ai", "litellm", "redis", "langfuse"}.issubset(
        frameworks
    )
    assert body["cache"]["provider"] == "redis"
    assert body["api_sources_used"][0]["provider"] == "serpapi_google_lens"
    assert body["visual_matches"][0]["provider"] == "serpapi_google_lens"
    assert body["knowledge_cards"][0]["source_type"] in {"exa", "wikivoyage"}


@pytest.mark.asyncio
async def test_redis_json_cache_uses_standard_json_contract_with_fallback():
    cache = RedisJsonCache(
        "redis://127.0.0.1:1/0",
        TravelPlanResponse,
        namespace="test:travel",
        ttl_seconds=1,
    )
    expected = TravelPlanResponse(
        summary="cached response",
        needs_user_confirmation=False,
    )

    await cache.put("same-request", expected)
    cached = await cache.get("same-request")

    assert cached is not None
    assert cached.summary == "cached response"
