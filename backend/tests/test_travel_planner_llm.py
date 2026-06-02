import httpx
import pytest

from app.config import Settings
from app.schemas.travel import TravelPlanRequest
from app.services.travel_planner import LightweightTravelPlanner, build_travel_planner
from app.services.travel_query_understanding import TravelModelCallError
from app.services.travel_reasoning import DeepInfraTravelDecisionClient
from app.services.travel_recommendation_supervisor import TravelRecommendationSupervisor


TRAVEL_FAST_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
TRAVEL_SEMANTIC_MODEL = "google/gemini-3.1-pro"
TRAVEL_REASONING_MODEL = "openai/gpt-oss-120b"
TRAVEL_REASONING_EFFORT = "high"
TRAVEL_ORCHESTRATOR_MODEL = "gpt-5.5"


class FakeDecisionClient:
    model = "fake-gemma"

    def __init__(self) -> None:
        self.calls = 0
        self.seen_recommendations = []

    async def decide(self, request, recommendations, suggestion_groups=None):
        self.calls += 1
        self.seen_recommendations = recommendations
        return {
            "summary": "模型决策：青蓮院更符合安静庭院和历史兴趣，清水寺只适合清晨备选。",
            "decision_notes": [
                "先按证据库评分，再由模型检查时间、兴趣、拥挤和广告风险。",
                "没有证据支撑的推荐会被降级。",
            ],
            "uncertainty": ["未接入实时营业时间，出发前仍需确认。"],
            "needs_user_confirmation": True,
            "recommendations": [
                {
                    "place_id": 1,
                    "decision": "recommended",
                    "decision_reason": "有官方与社区证据，且游客热度低，适合作为下午主选择。",
                    "pros": ["安静庭院", "历史感强", "广告风险低"],
                    "cons": ["种子证据数量仍少"],
                    "caution": "推荐去，但最好预留 60-90 分钟慢看。",
                },
                {
                    "place_id": 2,
                    "decision": "not_recommended",
                    "decision_reason": "与你避开游客的约束冲突，下午到达更容易遇到拥挤。",
                    "pros": ["经典地标"],
                    "cons": ["游客热度高", "不符合安静偏好"],
                    "caution": "这次不建议作为下午主目的地。",
                },
            ],
        }


class FailingDecisionClient:
    model = "fake-gemma"

    async def decide(self, request, recommendations):
        raise RuntimeError("model unavailable")


@pytest.mark.asyncio
async def test_travel_planner_uses_llm_to_make_decisions_after_ranking():
    decision_client = FakeDecisionClient()
    planner = LightweightTravelPlanner(decision_client=decision_client)

    response = await planner.plan(
        TravelPlanRequest(
            city="Kyoto",
            question="我下午到京都，想避开游客，有没有值得深入看的地方？",
            interest_tags=["quiet", "garden", "history"],
            constraints=["avoid crowds"],
        )
    )

    assert decision_client.calls == 1
    assert len(decision_client.seen_recommendations) == 2
    assert response.llm_used is True
    assert response.reasoning_mode == "deterministic_ranker+llm_decision"
    assert response.model_used == "fake-gemma"
    assert response.summary.startswith("模型决策")
    assert response.needs_user_confirmation is True
    assert response.uncertainty == ["未接入实时营业时间，出发前仍需确认。"]

    first = response.recommendations[0]
    assert first.place.place_id == 1
    assert first.decision == "recommended"
    assert first.pros == ["安静庭院", "历史感强", "广告风险低"]
    assert first.cons == ["种子证据数量仍少"]
    assert first.decision_reason == "有官方与社区证据，且游客热度低，适合作为下午主选择。"

    second = response.recommendations[1]
    assert second.place.place_id == 2
    assert second.decision == "not_recommended"
    assert "游客热度高" in second.cons


@pytest.mark.asyncio
async def test_travel_planner_raises_when_llm_decision_fails_without_deterministic_fallback():
    planner = LightweightTravelPlanner(decision_client=FailingDecisionClient())

    with pytest.raises(TravelModelCallError, match="travel_decision"):
        await planner.plan(
            TravelPlanRequest(
                city="Kyoto",
                question="我下午到京都，想避开游客，有没有值得深入看的地方？",
                interest_tags=["quiet", "garden", "history"],
            )
        )


def test_build_travel_planner_uses_multi_agent_supervisor_when_model_gateway_configured():
    planner = build_travel_planner(
        Settings(
            vlm_provider="deepinfra",
            deepinfra_api_key="test-token",
            litellm_base_url="http://127.0.0.1:4000/v1",
            litellm_api_key="test-litellm-key",
            deepinfra_narrative_model="google/gemma-4-26B-A4B-it",
        )
    )

    assert isinstance(planner, TravelRecommendationSupervisor)
    assert planner.agent_client is not None


def test_build_travel_planner_prefers_direct_deepinfra_for_travel_agents():
    planner = build_travel_planner(
        Settings(
            vlm_provider="deepinfra",
            deepinfra_api_key="deepinfra-token",
            deepinfra_base_url="https://deepinfra.test/v1/openai",
            litellm_base_url="http://127.0.0.1:4000/v1",
            litellm_api_key="litellm-token",
        )
    )

    assert isinstance(planner, TravelRecommendationSupervisor)
    assert planner.agent_client is not None
    assert planner.agent_client.api_key == "deepinfra-token"
    assert planner.agent_client.base_url == "https://deepinfra.test/v1/openai"
    assert planner.model_router.router == TRAVEL_SEMANTIC_MODEL
    assert planner.model_router.planner == TRAVEL_FAST_MODEL
    assert planner.model_router.formatter == TRAVEL_REASONING_MODEL
    assert planner.model_router.reasoning_effort == TRAVEL_REASONING_EFFORT


def test_build_travel_planner_uses_serper_and_deepinfra_as_default_platforms():
    planner = build_travel_planner(
        Settings(
            vlm_provider="deepinfra",
            deepinfra_api_key="deepinfra-token",
            deepinfra_base_url="https://deepinfra.test/v1/openai",
            serper_api_key="serper-token",
            serpapi_api_key="legacy-serpapi-token",
            google_maps_api_key="legacy-google-token",
            litellm_base_url="http://127.0.0.1:4000/v1",
            litellm_api_key="legacy-litellm-token",
        )
    )

    assert isinstance(planner, TravelRecommendationSupervisor)
    assert getattr(planner.serpapi_client, "provider_name", "") == "serper"
    assert planner.google_places_client is None
    assert planner.agent_client is not None
    assert planner.agent_client.api_key == "deepinfra-token"
    assert planner.agent_client.base_url == "https://deepinfra.test/v1/openai"


def test_build_travel_planner_prefers_zzshu_main_api_for_travel_orchestrator():
    planner = build_travel_planner(
        Settings(
            vlm_provider="deepinfra",
            travel_main_api_key="zzshu-token",
            travel_main_base_url="https://zzshu.cc/v1",
            travel_model_orchestrator=TRAVEL_ORCHESTRATOR_MODEL,
            deepinfra_api_key="deepinfra-token",
            deepinfra_base_url="https://deepinfra.test/v1/openai",
        )
    )

    assert isinstance(planner, TravelRecommendationSupervisor)
    assert planner.agent_client is not None
    assert planner.agent_client.api_key == "zzshu-token"
    assert planner.agent_client.base_url == "https://zzshu.cc/v1"
    assert planner.model_router.orchestrator == TRAVEL_ORCHESTRATOR_MODEL


def test_build_travel_planner_does_not_use_litellm_without_explicit_legacy_flag():
    planner = build_travel_planner(
        Settings(
            vlm_provider="deepinfra",
            deepinfra_api_key=None,
            litellm_base_url="http://127.0.0.1:4000/v1",
            litellm_api_key="legacy-litellm-token",
        )
    )

    assert isinstance(planner, LightweightTravelPlanner)


@pytest.mark.asyncio
async def test_deepinfra_travel_decision_client_sends_ranked_evidence_and_parses_json():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"summary":"模型决策：去青蓮院",'
                                '"decision_notes":["透明排序后再判断"],'
                                '"uncertainty":["未接入实时交通"],'
                                '"needs_user_confirmation":true,'
                                '"recommendations":[{"place_id":1,'
                                '"decision":"recommended",'
                                '"decision_reason":"安静且证据好",'
                                '"pros":["安静"],"cons":["证据仍少"],'
                                '"caution":"慢看"}]}'
                                "\n```"
                            )
                        }
                    }
                ]
            },
        )

    planner = LightweightTravelPlanner()
    ranked = (
        await planner.plan(
            TravelPlanRequest(
                city="Kyoto",
                question="下午去哪？",
                interest_tags=["quiet", "garden"],
            )
        )
    ).recommendations
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = DeepInfraTravelDecisionClient(
            api_key="test-token",
            http_client=http_client,
        )
        result = await client.decide(
            TravelPlanRequest(city="Kyoto", question="下午去哪？"),
            ranked,
        )

    assert f'"model":"{TRAVEL_REASONING_MODEL}"' in captured["payload"]
    assert f'"reasoning_effort":"{TRAVEL_REASONING_EFFORT}"' in captured["payload"]
    assert "ranked_candidates" in captured["payload"]
    assert "Never invent sources" in captured["payload"]
    assert result["summary"] == "模型决策：去青蓮院"
    assert result["recommendations"][0]["decision"] == "recommended"


@pytest.mark.asyncio
async def test_deepinfra_travel_decision_client_sends_fixed_broad_framework():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"按基础分类回答",'
                                '"decision_notes":[],"uncertainty":[],'
                                '"needs_user_confirmation":true,'
                                '"recommendations":[]}'
                            )
                        }
                    }
                ]
            },
        )

    generic_response = await LightweightTravelPlanner().plan(
        TravelPlanRequest(city="Fukuoka", query="第一次去福冈，帮我安排一下")
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = DeepInfraTravelDecisionClient(
            api_key="test-token",
            model="google/gemma-4-26B-A4B-it",
            http_client=http_client,
        )
        await client.decide(
            TravelPlanRequest(city="Fukuoka", query="第一次去福冈，帮我安排一下"),
            generic_response.recommendations,
            suggestion_groups=generic_response.suggestion_groups,
        )

    assert "suggestion_groups" in captured["payload"]
    for title in ["美食", "购物", "历史文化", "本地体验", "购物与街区", "自然与摄影"]:
        assert title in captured["payload"]
    assert "Each group must stay inside 3-5 items" in captured["payload"]
