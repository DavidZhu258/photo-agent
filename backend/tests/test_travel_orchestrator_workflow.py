from __future__ import annotations

import asyncio
import re

import pytest

from app.schemas.travel import TravelPlanRequest
from app.services.travel_query_understanding import TravelModelCallError
from app.services.travel_recommendation_supervisor import (
    AgentModelRouter,
    TravelRecommendationSupervisor,
    _system_prompt_for_agent,
)


TRAVEL_ORCHESTRATOR_PROMPT = (
    "请像靠谱旅行顾问一样自然回答当前问题。问什么答什么，不套固定模板；需要推荐时给出真实、可执行、"
    "避开广告营销的理由；需要地点或路线时再调用工具，不编造价格、营业时间、库存、距离或坐标。"
)


class OrchestratorAgentClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append(
            {
                "agent_name": agent_name,
                "model": model,
                "prompt": prompt,
                "payload": payload,
            }
        )
        request = payload.get("request", {})
        query = str(request.get("query") or "")
        if agent_name == "complex_route_reasoner":
            return {
                "route_options": [
                    {
                        "id": "route-shinkansen",
                        "title": "新干线：东京站 -> 京都站",
                        "provider": "deepinfra",
                        "duration": "约2小时15分",
                        "distance": "约515公里",
                        "mode": "rail",
                        "display_reason": "最快、班次密集，适合第一次从东京到京都。",
                    }
                ],
                "summary": "新干线优先，其次夜巴。"
            }
        if agent_name == "visual_context_analyzer":
            return {
                "summary": "图片像福冈塔附近的海滨区域。",
                "places_hint": ["Fukuoka Tower", "Momochihama"],
            }
        if agent_name != "travel_orchestrator":
            return {"summary": f"{agent_name} should not own this workflow"}
        if payload.get("phase") == "final_answer":
            initial = payload.get("initial_contract", {}) if isinstance(payload.get("initial_contract"), dict) else {}
            observations = payload.get("api_observations", {}) if isinstance(payload.get("api_observations"), dict) else {}
            places = observations.get("local:美食") or observations.get("local:本地体验") or []
            first_place = places[0] if places and isinstance(places[0], dict) else {}
            answer_mode = str(initial.get("answer_mode") or "place_cards")
            if answer_mode == "route_map":
                return {
                    "answer_mode": "route_map",
                    "sections": [
                        {
                            "title": "怎么走",
                            "body": "最终合成：结合路线工具结果，优先新干线，其次夜巴。",
                        }
                    ],
                    "tool_calls_requested": [],
                    "route_options": payload.get("route_options", []),
                    "data_gaps": [],
                }
            if answer_mode == "place_cards":
                title = str(first_place.get("title") or "工具返回地点")
                request_query = str((payload.get("request") or {}).get("query") or "")
                preference_note = "；如果偏好步行，就把同一区域内的候选先串起来" if "步行" in request_query else ""
                return {
                    "answer_mode": "place_cards",
                    "sections": [
                        {
                            "title": "建议",
                            "body": f"可以优先看 {title}，因为它有可定位地址和评价信息{preference_note}。",
                        }
                    ],
                    "tool_calls_requested": [],
                    "data_gaps": payload.get("warnings", []),
                }
            return {
                "answer_mode": answer_mode,
                "sections": [{"title": "最终建议", "body": "最终合成：基于工具结果回答。"}],
                "tool_calls_requested": [],
                "data_gaps": payload.get("warnings", []),
            }
        if "是什么" in query:
            return {
                "answer_mode": "answer_only",
                "sections": [
                    {
                        "title": "是什么",
                        "body": "河豚是一类可食用但需要专业处理的鱼。",
                    },
                    {
                        "title": "为什么危险",
                        "body": "风险主要来自河豚毒素，错误处理会造成严重中毒。",
                    },
                ],
                "tool_calls_requested": [],
                "data_gaps": [],
            }
        if "天神屋台" in query:
            return {
                "answer_mode": "answer_only",
                "sections": [
                    {
                        "title": "直接判断",
                        "body": "天神屋台不是只有游客去；本地人也会去，但更常见的是下班后小范围喝一杯或带朋友体验，游客比例会因地点和时段变高。",
                    },
                    {
                        "title": "怎么理解",
                        "body": "如果你问的是“值不值得专门去”，重点应比较氛围、排队、价格和是否接受游客化，而不是先生成一堆地点卡。",
                    },
                ],
                "tool_calls_requested": [
                    {
                        "name": "serper_search",
                        "arguments": {"query": "天神 屋台 本地人 游客 评价 reddit"},
                        "required": False,
                    },
                    {
                        "name": "serper_places",
                        "arguments": {"query": "天神 屋台", "category": "美食"},
                        "required": True,
                    },
                ],
                "data_gaps": [],
            }
        if "多角度" in query:
            return {
                "answer_mode": "answer_only",
                "sections": [
                    {"title": "第一部分", "body": "先把问题说清楚。"},
                    {"title": "第二部分", "body": "再补本地语境。"},
                    {"title": "第三部分", "body": "然后给实际判断。"},
                    {"title": "第四部分", "body": "最后列下一步。"},
                ],
                "tool_calls_requested": [],
                "data_gaps": [],
            }
        if "酒店" in query:
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "怎么选", "body": "先看位置、预算和交通。"}],
                "tool_calls_requested": [
                    {
                        "name": "hotel_search",
                        "arguments": {"city": "Fukuoka", "query": "福冈酒店"},
                        "required": True,
                    }
                ],
                "data_gaps": [],
            }
        if "东京到京都" in query:
            return {
                "answer_mode": "route_map",
                "sections": [{"title": "怎么走", "body": "优先比较新干线、夜巴和飞机。"}],
                "tool_calls_requested": [
                    {
                        "name": "route_lookup",
                        "arguments": {"origin": "Tokyo", "destination": "Kyoto", "mode": "rail"},
                        "required": True,
                    },
                    {
                        "name": "complex_route_reasoner",
                        "arguments": {"origin": "Tokyo", "destination": "Kyoto"},
                        "required": True,
                    },
                ],
                "data_gaps": [],
            }
        if request.get("previous_context", {}).get("visual_session_id"):
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "附近怎么玩", "body": "先用视觉线索定位，再找附近地点。"}],
                "tool_calls_requested": [
                    {
                        "name": "visual_context_analyzer",
                        "arguments": {"visual_session_id": "snap-1"},
                        "required": True,
                    },
                    {
                        "name": "serper_places",
                        "arguments": {"query": "Fukuoka Tower nearby attractions", "category": "本地体验"},
                        "required": True,
                    },
                ],
                "data_gaps": [],
            }
        if "自然" in query or "户外" in query or "风光" in query:
            return {
                "answer_mode": "place_cards",
                "sections": [
                    {"title": "怎么选", "body": "先看自然风光、海边开阔感和活动强度。"},
                    {"title": "去哪儿", "body": "优先给地图可定位的自然与户外地点。"},
                    {"title": "怎么排/地图", "body": "按区域和交通拆开。"},
                ],
                "tool_calls_requested": [
                    {
                        "name": "serper_places",
                        "arguments": {"query": "福冈 自然 户外 风光", "category": "本地体验"},
                        "required": True,
                    },
                    {
                        "name": "serper_images",
                        "arguments": {"query": "福冈 自然 户外 风光"},
                        "required": False,
                    },
                ],
                "data_gaps": [],
            }
        return {
            "answer_mode": "place_cards",
            "sections": [
                {"title": "怎么选", "body": "先看是否真有河豚菜单。"},
                {"title": "去哪儿", "body": "优先选择河豚料理专门店。"},
                {"title": "怎么走/地图", "body": "选择地图上可定位的店。"},
            ],
            "tool_calls_requested": [
                {
                    "name": "serper_places",
                    "arguments": {"query": "福冈 河豚 料理", "category": "美食"},
                    "required": True,
                },
                {
                    "name": "serper_images",
                    "arguments": {"query": "博多 ふぐ料理 玄品"},
                    "required": False,
                },
            ],
            "data_gaps": [],
        }


class HotelPlacesToolAgentClient(OrchestratorAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        request = payload.get("request", {})
        query = str(request.get("query") or "")
        if agent_name == "travel_orchestrator" and not payload.get("phase") and "酒店" in query:
            self.calls.append(
                {
                    "agent_name": agent_name,
                    "model": model,
                    "prompt": prompt,
                    "payload": payload,
                }
            )
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "怎么选", "body": "先看位置、预算和交通。"}],
                "tool_calls_requested": [
                    {
                        "name": "serper_places",
                        "arguments": {"query": "福冈 酒店 推荐", "category": "酒店"},
                        "required": True,
                    }
                ],
                "data_gaps": [],
            }
        return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)


class MinimalSerperClient:
    provider_name = "serper"

    def __init__(self, fail_places: bool = False) -> None:
        self.fail_places = fail_places
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "博多 ふぐ料理 玄品",
                    "snippet": "ふぐ刺し、ふぐ鍋、とらふぐコースあり。",
                    "type": "ふぐ料理",
                    "rating": 4.4,
                    "reviews": 240,
                    "address": "Hakata, Fukuoka",
                    "latitude": 33.5895,
                    "longitude": 130.4201,
                    "place_id": "ChIJFuguGenpin",
                    "query_variant": category,
                }
            ],
            fail=self.fail_places,
        )

    async def search_query_variants(self, request: TravelPlanRequest, queries: list[str]) -> list[dict]:
        self.calls.extend([f"serper_search:{query}" for query in queries])
        return [
            {
                "title": queries[0] if queries else request.query,
                "snippet": "source-backed context",
                "query_variant": queries[0] if queries else request.query,
            }
        ]

    async def search_images(self, request: TravelPlanRequest, query: str) -> list[dict]:
        return await self._record(
            f"serper_images:{query}",
            [{"imageUrl": "https://example.com/fugu.jpg"}],
        )

    async def search_hotels(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "hotel_search",
            [
                {
                    "name": "Hotel Okura Fukuoka",
                    "rate": "¥22000",
                    "rating": 4.4,
                    "address": "Hakata, Fukuoka",
                    "image_url": "https://example.com/hotel.jpg",
                }
            ],
        )

    async def search_flights(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record("flight_search", [])

    async def search_transport(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "route_lookup",
            [{"title": "Tokyo to Kyoto rail", "snippet": "Shinkansen is the fastest common route."}],
        )

    async def search_budget(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record("budget", [{"title": "budget context"}])

    async def _record(self, name: str, result: list[dict], *, fail: bool = False) -> list[dict]:
        self.calls.append(name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if fail:
            raise RuntimeError("HTTP 502 /places")
        return result


class ExplodingResultCache:
    async def get(self, key: str):
        raise AssertionError("travel result cache should not be read in the simplified session-only flow")

    async def put(self, key: str, value):
        raise AssertionError("travel result cache should not be written in the simplified session-only flow")


def _supervisor(agent_client: OrchestratorAgentClient, serper: MinimalSerperClient) -> TravelRecommendationSupervisor:
    return TravelRecommendationSupervisor(
        serpapi_client=serper,
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
        orchestration_mode="orchestrator",
    )


@pytest.mark.asyncio
async def test_gpt_orchestrator_answer_only_skips_map_and_specialists():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="", query="河豚是什么，为什么危险？", allow_web_search=True)
    )

    assert response.answer_mode == "answer_only"
    assert response.display_cards == []
    assert response.map_view["status"] == "answer_only"
    assert response.formatted_markdown.count("## ") <= 3
    called_agents = [call["agent_name"] for call in agent_client.calls]
    assert called_agents == ["travel_orchestrator"]
    assert set(agent_client.calls[0]["payload"]["tool_contract"]) == {
        "route_lookup",
        "serper_images",
        "serper_places",
        "serper_search",
    }
    assert serper.calls == []
    assert response.raw_provider_refs["langgraph_orchestrator"]["graph_nodes"] == [
        "orchestrate",
        "execute_tools",
        "final_answer",
        "render_response",
    ]


@pytest.mark.asyncio
async def test_answer_only_followup_about_local_vs_tourist_does_not_inherit_previous_map_cards():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="天神屋台本地人会常去吗?还是说是游客去的?",
            question="天神屋台本地人会常去吗?还是说是游客去的?",
            previous_context={
                "city": "Fukuoka",
                "active_query": "福冈有哪些好玩的日本其他地方没有?",
                "last_answer_mode": "place_cards",
                "last_cards": [
                    {"id": "ohori", "title": "大濠公园", "category": "自然与摄影"},
                    {"id": "tower", "title": "福冈塔", "category": "本地体验"},
                ],
                "map_pins": [
                    {"id": "ohori", "title": "大濠公园", "lat": 33.586, "lng": 130.376},
                ],
            },
            allow_web_search=True,
        )
    )

    assert response.answer_mode == "answer_only"
    assert response.display_cards == []
    assert response.map_view["status"] == "answer_only"
    assert "天神屋台" in response.formatted_markdown
    assert "大濠公园" not in response.formatted_markdown
    assert not any(call.startswith("serper_places:") for call in serper.calls)
    assert any(call.startswith("serper_search:") for call in serper.calls)


def test_travel_orchestrator_prompt_is_minimal_classification_instruction():
    assert _system_prompt_for_agent("travel_orchestrator") == TRAVEL_ORCHESTRATOR_PROMPT


@pytest.mark.asyncio
async def test_travel_orchestrator_call_uses_minimal_task_prompt_only():
    agent_client = OrchestratorAgentClient()
    await _supervisor(agent_client, MinimalSerperClient()).plan(
        TravelPlanRequest(city="", query="河豚是什么，为什么危险？", allow_web_search=True)
    )

    initial_call = agent_client.calls[0]
    assert initial_call["agent_name"] == "travel_orchestrator"
    assert initial_call["prompt"] == TRAVEL_ORCHESTRATOR_PROMPT


@pytest.mark.asyncio
async def test_simplified_travel_flow_does_not_read_or_write_result_cache():
    response = await TravelRecommendationSupervisor(
        serpapi_client=MinimalSerperClient(),
        agent_client=OrchestratorAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
        result_cache=ExplodingResultCache(),
        orchestration_mode="orchestrator",
    ).plan(TravelPlanRequest(city="Fukuoka", query="河豚是什么，为什么危险？"))

    assert response.workflow_status == "completed"
    assert response.cache.hit is False
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "initial_contract_no_tools"


@pytest.mark.asyncio
async def test_simplified_orchestrator_exposes_only_lightweight_tools_and_session_context():
    agent_client = OrchestratorAgentClient()
    previous_context = {
        "active_query": "福冈有什么好玩的？",
        "last_query": "福冈有什么好玩的？",
        "interest_tags": ["户外风光"],
        "last_cards": [{"title": "大濠公园"}],
    }

    await _supervisor(agent_client, MinimalSerperClient()).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈酒店、航班、图片、签证、路线都帮我看一下",
            previous_context=previous_context,
            allow_web_search=True,
        )
    )

    initial_call = next(
        call
        for call in agent_client.calls
        if call["agent_name"] == "travel_orchestrator" and not call["payload"].get("phase")
    )
    assert set(initial_call["payload"]["tool_contract"]) <= {
        "serper_search",
        "serper_places",
        "serper_images",
        "route_lookup",
    }
    assert "hotel_search" not in initial_call["payload"]["tool_contract"]
    assert "flight_search" not in initial_call["payload"]["tool_contract"]
    assert "complex_route_reasoner" not in initial_call["payload"]["tool_contract"]
    assert "critic_verifier" not in initial_call["payload"]["tool_contract"]
    assert "visual_context_analyzer" not in initial_call["payload"]["tool_contract"]
    assert initial_call["payload"]["request"]["previous_context"] == previous_context


@pytest.mark.asyncio
async def test_simplified_orchestrator_uses_snake_case_session_context_for_followups():
    agent_client = OrchestratorAgentClient()
    previous_context = {
        "active_query": "广岛有什么好玩的？",
        "last_query": "广岛有什么好玩的？",
        "interest_tags": ["安静", "自然"],
        "last_cards": [{"title": "缩景园"}],
    }

    await _supervisor(agent_client, MinimalSerperClient()).plan(
        TravelPlanRequest(
            city="Hiroshima",
            query="我喜欢安静一点",
            previous_context=previous_context,
            allow_web_search=True,
        )
    )

    initial_call = next(
        call
        for call in agent_client.calls
        if call["agent_name"] == "travel_orchestrator" and not call["payload"].get("phase")
    )
    assert set(initial_call["payload"]["tool_contract"]) == {
        "route_lookup",
        "serper_images",
        "serper_places",
        "serper_search",
    }
    assert initial_call["payload"]["request"]["previous_context"] == previous_context


@pytest.mark.asyncio
async def test_gpt_orchestrator_place_query_uses_serper_places_and_images_without_specialist_fanout():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert response.display_cards
    assert response.display_cards[0].title == "博多 ふぐ料理 玄品"
    assert response.map_view["status"] == "ready"
    assert any(call.startswith("serper_places:") for call in serper.calls)
    assert any(call.startswith("serper_images:") for call in serper.calls)
    called_agents = {call["agent_name"] for call in agent_client.calls}
    assert called_agents == {"travel_orchestrator"}
    assert "activity_food" not in called_agents
    orchestrator_calls = [call for call in agent_client.calls if call["agent_name"] == "travel_orchestrator"]
    assert len(orchestrator_calls) == 1
    initial_call = next(call for call in orchestrator_calls if call["payload"].get("phase") != "final_answer")
    assert set(initial_call["payload"]["tool_contract"]) == {
        "route_lookup",
        "serper_images",
        "serper_places",
        "serper_search",
    }
    assert "博多 ふぐ料理 玄品" in response.formatted_markdown
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert (
        response.raw_provider_refs["travel_orchestrator"]["ownership"]
        == "single_manager_initial_answer_with_lightweight_tools"
    )
    assert (
        response.raw_provider_refs["langgraph_orchestrator"]["run_mode"]
        == "single_gpt_orchestrator_with_lightweight_tools"
    )
    assert "ふぐ料理" in response.formatted_markdown or "河豚" in response.formatted_markdown
    assert "自然和户外" not in response.formatted_markdown
    assert "海滨远眺" not in response.formatted_markdown
    assert "户外活动" not in response.formatted_markdown
    assert any(call.startswith("serper_search:") for call in serper.calls)
    assert "Reddit" not in response.formatted_markdown
    assert "reddit" not in response.formatted_markdown.lower()
    assert "当地评价" not in response.formatted_markdown
    assert "因为" in response.formatted_markdown


@pytest.mark.asyncio
async def test_shopping_place_recommendation_forces_places_and_map_tools():
    class TextOnlyShoppingAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append(
                {
                    "agent_name": agent_name,
                    "model": model,
                    "prompt": prompt,
                    "payload": payload,
                }
            )
            return {
                "answer_mode": "answer_only",
                "sections": [
                    {
                        "title": "先给结论",
                        "body": "柳桥连合市场、川端通商店街和西新商店街更适合找福冈的烟火气。",
                    }
                ],
                "tool_calls_requested": [],
                "cards": [
                    {"id": "yanagibashi-market", "title": "柳桥连合市场", "category": "购物"},
                    {"id": "kawabata-shotengai", "title": "川端通商店街", "category": "购物"},
                ],
                "data_gaps": [],
            }

    class ShoppingSerperClient(MinimalSerperClient):
        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            return await self._record(
                f"serper_places:{category}",
                [
                    {
                        "title": "柳桥连合市场",
                        "snippet": "本地市场，海鲜、熟食和小店密集，适合上午逛。",
                        "type": "市场",
                        "rating": 4.1,
                        "reviews": 1200,
                        "address": "Haruyoshi, Fukuoka",
                        "latitude": 33.586,
                        "longitude": 130.405,
                        "place_id": "yanagibashi-market",
                        "query_variant": category,
                    },
                    {
                        "title": "川端通商店街",
                        "snippet": "老商店街，靠近博多祇园，适合顺路看本地日常。",
                        "type": "商店街",
                        "rating": 4.0,
                        "reviews": 900,
                        "address": "Kamikawabatamachi, Fukuoka",
                        "latitude": 33.594,
                        "longitude": 130.410,
                        "place_id": "kawabata-shotengai",
                        "query_variant": category,
                    },
                ],
            )

    agent_client = TextOnlyShoppingAgentClient()
    serper = ShoppingSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈烟火气购物地", allow_web_search=True)
    )

    initial_call = next(call for call in agent_client.calls if call["agent_name"] == "travel_orchestrator")
    assert {"serper_places", "serper_images", "serper_search"}.issubset(
        set(initial_call["payload"]["tool_contract"])
    )
    requested_tools = response.raw_provider_refs["travel_orchestrator"]["tool_calls_requested"]
    places_call = next(call for call in requested_tools if call["name"] == "serper_places")
    assert places_call["arguments"]["category"] == "购物"
    assert response.answer_mode == "place_cards"
    assert response.display_cards
    assert response.display_cards[0].title == "柳桥连合市场"
    assert response.map_view["status"] == "ready"
    assert response.map_view["pins"]
    assert any(call.startswith("serper_places:") for call in serper.calls)
    assert any(call.startswith("serper_images:") for call in serper.calls)
    assert any(call.startswith("serper_search:") for call in serper.calls)


@pytest.mark.asyncio
async def test_result_contract_place_cards_trigger_places_without_query_markers():
    class ResultCardAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append(
                {
                    "agent_name": agent_name,
                    "model": model,
                    "prompt": prompt,
                    "payload": payload,
                }
            )
            return {
                "answer_mode": "answer_only",
                "sections": [
                    {
                        "id": "unique-local",
                        "title": "特别一点的选择",
                        "body": "我会优先核对这些地点是不是值得专门去。",
                        "bullets": ["Hakata Old Town Area", "Ohori Park"],
                        "card_ids": ["hakata-old-town", "ohori-park"],
                        "pin_ids": ["hakata-old-town", "ohori-park"],
                        "tables": [
                            {
                                "caption": "候选对比",
                                "columns": ["地点", "适合谁"],
                                "rows": [["Hakata Old Town Area", "想看城市历史街区的人"]],
                            }
                        ],
                        "images": [
                            {
                                "url": "https://example.com/hakata-old-town.jpg",
                                "caption": "街区入口",
                                "source": "model",
                            }
                        ],
                    }
                ],
                "cards": [
                    {
                        "id": "hakata-old-town",
                        "title": "Hakata Old Town Area",
                        "category": "本地体验",
                    },
                    {
                        "id": "ohori-park",
                        "title": "Ohori Park",
                        "category": "自然与摄影",
                    },
                ],
                "tool_calls_requested": [],
                "data_gaps": [],
            }

    class ResultCardSerperClient(MinimalSerperClient):
        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            return await self._record(
                f"serper_places:{category}",
                [
                    {
                        "title": "Hakata Old Town Area",
                        "snippet": "博多旧市街，寺社、町家和老街区集中。",
                        "type": "历史街区",
                        "rating": 4.3,
                        "reviews": 820,
                        "address": "Hakata Ward, Fukuoka",
                        "latitude": 33.595,
                        "longitude": 130.413,
                        "place_id": "hakata-old-town",
                        "query_variant": category,
                    },
                    {
                        "title": "Ohori Park",
                        "snippet": "城市湖景公园，适合慢走和放空。",
                        "type": "公园",
                        "rating": 4.5,
                        "reviews": 9400,
                        "address": "Chuo Ward, Fukuoka",
                        "latitude": 33.5869,
                        "longitude": 130.3796,
                        "place_id": "ohori-park",
                        "query_variant": category,
                    },
                ],
            )

    agent_client = ResultCardAgentClient()
    serper = ResultCardSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="这次旅行我想要特别一点", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert response.display_cards
    assert response.map_view["status"] == "ready"
    assert response.map_view["pins"]
    assert any(call.startswith("serper_places:") for call in serper.calls)
    assert any(call.startswith("serper_images:") for call in serper.calls)
    assert any(call.startswith("serper_search:") for call in serper.calls)
    assert response.answer_sections[0].tables[0].caption == "候选对比"
    assert response.answer_sections[0].images[0].url == "https://example.com/hakata-old-town.jpg"
    assert response.answer_sections[0].card_ids == ["hakata-old-town", "ohori-park"]


@pytest.mark.asyncio
async def test_places_tool_results_render_cards_when_tool_query_is_not_exact_entity():
    class BroadPlacesAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append(
                {
                    "agent_name": agent_name,
                    "model": model,
                    "prompt": prompt,
                    "payload": payload,
                }
            )
            return {
                "answer_mode": "place_cards",
                "sections": [
                    {
                        "title": "怎么选",
                        "body": "先看真实地点数据，再决定要不要展示地图。",
                    }
                ],
                "tool_calls_requested": [
                    {
                        "name": "serper_places",
                        "arguments": {
                            "query": "Fukuoka unique natural landscapes local reviews reddit",
                            "category": "自然景观",
                        },
                        "required": True,
                    }
                ],
                "data_gaps": [],
            }

    class BroadPlacesSerperClient(MinimalSerperClient):
        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            return await self._record(
                f"serper_places:{category}",
                [
                    {
                        "title": "海之中道海滨公园",
                        "snippet": "海滨、花田、骑行和亲子活动，面积很大。",
                        "type": "海滨公园",
                        "rating": 4.4,
                        "reviews": 7600,
                        "address": "Higashi Ward, Fukuoka",
                        "latitude": 33.663,
                        "longitude": 130.363,
                        "place_id": "uminonakamichi",
                        "query_variant": "Fukuoka unique natural landscapes local reviews reddit",
                    },
                    {
                        "title": "能古岛岛公园",
                        "snippet": "岛上花田和海湾视野，适合半日户外。",
                        "type": "岛屿公园",
                        "rating": 4.2,
                        "reviews": 2800,
                        "address": "Nokonoshima, Fukuoka",
                        "latitude": 33.628,
                        "longitude": 130.303,
                        "place_id": "nokonoshima",
                        "query_variant": "Fukuoka unique natural landscapes local reviews reddit",
                    },
                ],
            )

    response = await _supervisor(BroadPlacesAgentClient(), BroadPlacesSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有哪些自然景观日本其他地方没有?", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert response.resolved_intent["target_entity"] == ""
    assert response.display_cards
    assert response.display_cards[0].title == "海之中道海滨公园"
    assert response.map_view["status"] == "ready"
    assert response.map_view["pins"]


@pytest.mark.asyncio
async def test_places_answer_preserves_freeform_sections_and_multimodal_cards():
    class FreeformPlacesAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append(
                {
                    "agent_name": agent_name,
                    "model": model,
                    "prompt": prompt,
                    "payload": payload,
                }
            )
            return {
                "answer_mode": "place_cards",
                "sections": [
                    {
                        "id": "local-read",
                        "title": "先说我会怎么取舍",
                        "body": "这类问题不需要套固定栏目，先用真实地点结果筛掉广告感强的候选。",
                        "bullets": ["优先看评价、地址和旅行者反馈都能核到的地点。"],
                        "card_ids": ["ohori"],
                        "pin_ids": ["ohori"],
                    },
                    {
                        "id": "map-use",
                        "title": "放进地图后再决定",
                        "body": "地图只负责承载真实 places 工具返回的位置。",
                    },
                ],
                "tool_calls_requested": [
                    {
                        "name": "serper_places",
                        "arguments": {"query": "Fukuoka quiet parks local reviews", "category": "自然景观"},
                        "required": True,
                    }
                ],
                "data_gaps": [],
            }

    class FreeformSerperClient(MinimalSerperClient):
        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            return await self._record(
                f"serper_places:{category}",
                [
                    {
                        "title": "大濠公园",
                        "snippet": "湖边步道、城市绿地、低强度散步。",
                        "type": "公园",
                        "rating": 4.5,
                        "reviews": 9400,
                        "address": "Chuo Ward, Fukuoka",
                        "latitude": 33.5869,
                        "longitude": 130.3796,
                        "place_id": "ohori",
                    }
                ],
            )

    response = await _supervisor(FreeformPlacesAgentClient(), FreeformSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有什么安静自然景观?", allow_web_search=True)
    )

    assert response.display_cards
    assert response.map_view["status"] == "ready"
    assert [section.title for section in response.answer_sections[:2]] == [
        "先说我会怎么取舍",
        "放进地图后再决定",
    ]
    assert "## 怎么选" not in response.formatted_markdown
    assert "## 怎么排/地图" not in response.formatted_markdown
    assert "提示词" not in response.formatted_markdown
    assert response.raw_provider_refs["travel_orchestrator"]["answer_framework"] == "freeform_multimodal_travel_v1"


@pytest.mark.asyncio
async def test_places_cards_filter_sponsored_and_marketing_items():
    class MarketingSerperClient(MinimalSerperClient):
        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            return await self._record(
                f"serper_places:{category}",
                [
                    {
                        "title": "Sponsored Ocean View Deck",
                        "snippet": "Sponsored promoted listing with paid placement.",
                        "type": "景点",
                        "rating": 5.0,
                        "reviews": 99999,
                        "address": "Fukuoka",
                        "latitude": 33.6,
                        "longitude": 130.4,
                        "place_id": "sponsored-deck",
                        "sponsored": True,
                    },
                    {
                        "title": "大濠公园",
                        "snippet": "湖边步道、城市绿地、低强度散步。",
                        "type": "公园",
                        "rating": 4.5,
                        "reviews": 9400,
                        "address": "Chuo Ward, Fukuoka",
                        "latitude": 33.5869,
                        "longitude": 130.3796,
                        "place_id": "ohori",
                    },
                ],
            )

    response = await _supervisor(OrchestratorAgentClient(), MarketingSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有什么自然风光？", allow_web_search=True)
    )

    titles = [card.title for card in response.display_cards]
    pin_titles = [pin["title"] for pin in response.map_view["pins"]]
    assert "大濠公园" in titles
    assert "Sponsored Ocean View Deck" not in titles
    assert "Sponsored Ocean View Deck" not in pin_titles


@pytest.mark.asyncio
async def test_gpt_orchestrator_does_not_truncate_answer_sections_to_three():
    agent_client = OrchestratorAgentClient()
    response = await _supervisor(agent_client, MinimalSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="请多角度解释福冈旅行怎么判断", allow_web_search=True)
    )

    assert "## 第四部分" in response.formatted_markdown
    assert len(response.raw_provider_refs["travel_orchestrator"]["sections"]) == 4


@pytest.mark.asyncio
async def test_gpt_orchestrator_route_query_uses_only_route_lookup_tool():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Kyoto", query="东京到京都怎么走？", allow_web_search=True)
    )

    assert response.answer_mode == "route_map"
    assert "route_lookup" in serper.calls
    called_agents = [call["agent_name"] for call in agent_client.calls]
    assert called_agents == ["travel_orchestrator", "travel_orchestrator"]
    initial_call = next(call for call in agent_client.calls if not call["payload"].get("phase"))
    assert "route_lookup" in initial_call["payload"]["tool_contract"]
    assert all(call["agent_name"] != "complex_route_reasoner" for call in agent_client.calls)
    assert response.route_options
    assert response.route_options[0].title == "新干线：Tokyo -> Kyoto"
    assert "多 Agent" not in response.formatted_markdown
    assert "怎么走" in response.formatted_markdown


@pytest.mark.asyncio
async def test_gpt_orchestrator_hotel_query_stays_with_main_model_without_inventory_tools():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈酒店推荐", allow_web_search=True)
    )

    assert response.hotel_offers == []
    assert response.display_cards == []
    assert response.map_view["status"] in {"needs_coordinates", "answer_only"}
    assert "hotel_search" not in serper.calls
    assert not any(call.startswith("serper_places:") for call in serper.calls)
    assert all(call["agent_name"] == "travel_orchestrator" for call in agent_client.calls)


@pytest.mark.asyncio
async def test_gpt_orchestrator_blocks_unoffered_place_tools_for_hotel_queries():
    agent_client = HotelPlacesToolAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈酒店推荐", allow_web_search=True)
    )

    initial_call = next(call for call in agent_client.calls if not call["payload"].get("phase"))
    assert set(initial_call["payload"]["tool_contract"]) == {
        "route_lookup",
        "serper_images",
        "serper_places",
        "serper_search",
    }
    assert response.answer_mode == "answer_only"
    assert response.display_cards == []
    assert response.map_view["status"] == "answer_only"
    assert not serper.calls
    assert any("不使用通用地点工具" in gap for gap in response.data_gaps)


@pytest.mark.asyncio
async def test_gpt_orchestrator_visual_context_does_not_call_gemini_specialist_in_simplified_flow():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="这附近怎么玩？",
            previous_context={"visual_session_id": "snap-1"},
            allow_web_search=True,
        )
    )

    called_agents = [call["agent_name"] for call in agent_client.calls]
    assert called_agents == ["travel_orchestrator"]
    assert not any(call["payload"].get("phase") == "final_answer" for call in agent_client.calls)
    assert response.display_cards
    assert response.map_view["status"] == "ready"
    initial_call = next(call for call in agent_client.calls if not call["payload"].get("phase"))
    assert "visual_context_analyzer" not in initial_call["payload"]["tool_contract"]


class FlakyOnceSerperClient(MinimalSerperClient):
    def __init__(self) -> None:
        super().__init__()
        self.local_attempts = 0

    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        self.local_attempts += 1
        if self.local_attempts == 1:
            self.calls.append(f"serper_places:{category}")
            raise RuntimeError("HTTP 502 /places")
        return await super().search_local(request, category)


class OutdoorSerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "大濠公园",
                    "snippet": "湖边步道、城市绿地、低强度散步。",
                    "type": "公园",
                    "rating": 4.5,
                    "reviews": 9400,
                    "address": "Chuo Ward, Fukuoka",
                    "latitude": 33.5869,
                    "longitude": 130.3796,
                    "place_id": "ohori",
                    "query_variant": category,
                },
                {
                    "title": "海之中道海滨公园",
                    "snippet": "海滨、花田、骑行和亲子活动，面积很大。",
                    "type": "海滨公园",
                    "rating": 4.4,
                    "reviews": 7600,
                    "address": "Higashi Ward, Fukuoka",
                    "latitude": 33.663,
                    "longitude": 130.363,
                    "place_id": "uminonakamichi",
                    "query_variant": category,
                },
                {
                    "title": "Fukuoka Tower",
                    "snippet": "城市地标，适合看海岸线和城市夜景。",
                    "type": "地标",
                    "rating": 4.1,
                    "reviews": 12000,
                    "address": "Momochihama, Fukuoka",
                    "latitude": 33.5933,
                    "longitude": 130.3515,
                    "place_id": "fukuoka-tower",
                    "query_variant": category,
                },
                {
                    "title": "Forest Adventure Itoshima",
                    "snippet": "森林绳索和户外活动，强度高于普通散步。",
                    "type": "户外活动",
                    "rating": 4.7,
                    "reviews": 840,
                    "address": "Itoshima, Fukuoka",
                    "latitude": 33.557,
                    "longitude": 130.197,
                    "place_id": "forest-adventure-itoshima",
                    "query_variant": category,
                },
            ],
        )


class FukuokaFirstTimerSerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "大濠公园",
                    "type": "公园",
                    "rating": 4.5,
                    "reviews": 9400,
                    "address": "Ohorikoen, Chuo Ward, Fukuoka",
                    "latitude": 33.5869,
                    "longitude": 130.3796,
                    "place_id": "ohori",
                    "query_variant": category,
                },
                {
                    "title": "太宰府天满宫",
                    "type": "神社",
                    "rating": 4.5,
                    "reviews": 18000,
                    "address": "4 Chome-7-1 Saifu, Dazaifu",
                    "latitude": 33.5214,
                    "longitude": 130.5348,
                    "place_id": "dazaifu-tenmangu",
                    "query_variant": category,
                },
                {
                    "title": "Momochihama Beach",
                    "type": "海滨",
                    "rating": 4.5,
                    "reviews": 5200,
                    "address": "2 Chome-4-4 Momochihama, Sawara Ward, Fukuoka",
                    "latitude": 33.5934,
                    "longitude": 130.3515,
                    "place_id": "momochihama-beach",
                    "query_variant": category,
                },
                {
                    "title": "Ukimi-do Pavilion (Ohori Park)",
                    "type": "公园景点",
                    "rating": 4.4,
                    "reviews": 1300,
                    "address": "1-1 Ohorikoen, Chuo Ward, Fukuoka",
                    "latitude": 33.5878,
                    "longitude": 130.3799,
                    "place_id": "ukimido-ohori",
                    "query_variant": category,
                },
                {
                    "title": "栉田神社",
                    "type": "神社",
                    "rating": 4.3,
                    "reviews": 8400,
                    "address": "1-41 Kamikawabatamachi, Hakata Ward",
                    "latitude": 33.5931,
                    "longitude": 130.4107,
                    "place_id": "kushida-shrine",
                    "query_variant": "Fukuoka first-time parks shrines attractions",
                },
                {
                    "title": "Hakata Old Town Area",
                    "type": "历史街区",
                    "rating": 4.3,
                    "reviews": 2100,
                    "address": "1 Chome-7 Hakata Ekimae, Hakata Ward, Fukuoka",
                    "latitude": 33.5952,
                    "longitude": 130.4144,
                    "place_id": "hakata-old-town",
                    "query_variant": category,
                },
            ],
        )


class FukuokaThreeDaySerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "博多旧市街",
                    "snippet": "博多站和祇园一带容易抵达，适合第一天用低强度方式熟悉城市。",
                    "type": "历史街区",
                    "rating": 4.3,
                    "reviews": 2100,
                    "address": "Hakata Ward, Fukuoka",
                    "latitude": 33.5952,
                    "longitude": 130.4144,
                    "place_id": "hakata-old-town-3day",
                    "query_variant": category,
                },
                {
                    "title": "天神",
                    "snippet": "商场、餐饮和屋台集中，适合作为抵达日傍晚的轻松区域。",
                    "type": "商业街区",
                    "rating": 4.2,
                    "reviews": 8800,
                    "address": "Tenjin, Chuo Ward, Fukuoka",
                    "latitude": 33.5904,
                    "longitude": 130.3989,
                    "place_id": "tenjin-3day",
                    "query_variant": category,
                },
                {
                    "title": "太宰府天满宫",
                    "snippet": "福冈经典近郊点，适合单独安排半天，不要和海边硬塞在一起。",
                    "type": "神社",
                    "rating": 4.5,
                    "reviews": 18000,
                    "address": "4 Chome-7-1 Saifu, Dazaifu",
                    "latitude": 33.5214,
                    "longitude": 130.5348,
                    "place_id": "dazaifu-3day",
                    "query_variant": category,
                },
                {
                    "title": "大濠公园",
                    "snippet": "市内湖边公园，适合太宰府回城后散步，不必单独耗掉一整天。",
                    "type": "公园",
                    "rating": 4.5,
                    "reviews": 9400,
                    "address": "Ohorikoen, Chuo Ward, Fukuoka",
                    "latitude": 33.5869,
                    "longitude": 130.3796,
                    "place_id": "ohori-3day",
                    "query_variant": category,
                },
                {
                    "title": "百道海滨",
                    "snippet": "海边、福冈塔和开阔景观集中，适合第三天做轻松半日。",
                    "type": "海滨",
                    "rating": 4.4,
                    "reviews": 5200,
                    "address": "Momochihama, Sawara Ward, Fukuoka",
                    "latitude": 33.5934,
                    "longitude": 130.3515,
                    "place_id": "momochihama-3day",
                    "query_variant": category,
                },
            ],
        )


class FukuokaSparseItinerarySerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "九州福岡自由行推薦！福岡旅遊行程/景點交通整理 - KKday",
                    "snippet": "A travel blog/listing page, not a map-ready place.",
                    "type": "Search result",
                    "link": "https://example.com/fukuoka-itinerary",
                    "query_variant": category,
                    "serper_endpoint": "search",
                },
                {
                    "title": "3小時遊覽！福岡市內觀光初體驗天神地區推薦路線",
                    "snippet": "Another generic route article with no coordinates.",
                    "type": "Search result",
                    "link": "https://example.com/tenjin-route",
                    "query_variant": category,
                    "serper_endpoint": "search",
                },
                {
                    "title": "太宰府天满宫",
                    "snippet": "适合半日小旅行：参道小吃和神社氛围完整。",
                    "type": "神社",
                    "rating": 4.5,
                    "address": "4 Chome-7-1 Saifu, Dazaifu",
                    "latitude": 33.5214,
                    "longitude": 130.5348,
                    "place_id": "dazaifu-sparse",
                    "query_variant": category,
                    "serper_endpoint": "places",
                },
            ],
        )


class EmptyFukuokaItinerarySerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(f"serper_places:{category}", [])


class FukuokaMixedOrderItinerarySerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "Momochihama Beach",
                    "snippet": "适合海滨轻松半日，建议和福冈塔/百道海滨同区安排。",
                    "type": "海滨",
                    "rating": 4.8,
                    "reviews": 9000,
                    "address": "Momochihama, Sawara Ward, Fukuoka",
                    "latitude": 33.5934,
                    "longitude": 130.3515,
                    "place_id": "momochihama-online-order",
                    "query_variant": category,
                },
                {
                    "title": "大濠公园",
                    "snippet": "市内湖边公园，适合回城后散步。",
                    "type": "公园",
                    "rating": 4.7,
                    "reviews": 8000,
                    "address": "Ohorikoen, Chuo Ward, Fukuoka",
                    "latitude": 33.5869,
                    "longitude": 130.3796,
                    "place_id": "ohori-online-order",
                    "query_variant": category,
                },
                {
                    "title": "海之中道海滨公园",
                    "snippet": "海边公园，范围大，适合作为备选而不是初访三天主轴。",
                    "type": "海滨公园",
                    "rating": 4.6,
                    "reviews": 7200,
                    "address": "Saitozaki, Higashi Ward, Fukuoka",
                    "latitude": 33.6642,
                    "longitude": 130.3639,
                    "place_id": "uminonakamichi-online-order",
                    "query_variant": category,
                },
                {
                    "title": "太宰府天满宫",
                    "snippet": "适合半日小旅行：参道小吃和神社氛围完整，建议单独排半天。",
                    "type": "神社",
                    "rating": 4.5,
                    "reviews": 18000,
                    "address": "4 Chome-7-1 Saifu, Dazaifu",
                    "latitude": 33.5214,
                    "longitude": 130.5348,
                    "place_id": "dazaifu-online-order",
                    "query_variant": category,
                },
                {
                    "title": "Fukuoka Tower",
                    "snippet": "百道海滨同区，适合第三天轻松半日。",
                    "type": "展望塔",
                    "rating": 4.4,
                    "reviews": 12000,
                    "address": "2 Chome-3-26 Momochihama, Sawara Ward, Fukuoka",
                    "latitude": 33.5933,
                    "longitude": 130.3515,
                    "place_id": "fukuoka-tower-online-order",
                    "query_variant": category,
                },
                {
                    "title": "博多港塔",
                    "snippet": "适合作为城市方位感第一站，天气差时降级为备选。",
                    "type": "展望塔",
                    "rating": 4.1,
                    "reviews": 2800,
                    "address": "14-1 Chikkohonmachi, Hakata Ward, Fukuoka",
                    "latitude": 33.6072,
                    "longitude": 130.4022,
                    "place_id": "hakata-port-tower-online-order",
                    "query_variant": category,
                },
                {
                    "title": "博多运河城",
                    "snippet": "适合作为晚间或雨天补充，吃饭购物和回酒店都方便。",
                    "type": "商业设施",
                    "rating": 4.0,
                    "reviews": 15000,
                    "address": "1 Chome-2 Sumiyoshi, Hakata Ward, Fukuoka",
                    "latitude": 33.5898,
                    "longitude": 130.4112,
                    "place_id": "canal-city-online-order",
                    "query_variant": category,
                },
                {
                    "title": "Momochi Seaside Park",
                    "snippet": "百道海滨同区，适合留作离境前轻松缓冲。",
                    "type": "海滨",
                    "rating": 4.0,
                    "reviews": 4000,
                    "address": "Momochihama, Sawara Ward, Fukuoka",
                    "latitude": 33.5928,
                    "longitude": 130.3507,
                    "place_id": "momochi-seaside-online-order",
                    "query_variant": category,
                },
            ],
        )


@pytest.mark.asyncio
async def test_fukuoka_three_day_itinerary_uses_deterministic_day_by_day_plan():
    class FukuokaThreeDayAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "itinerary",
                    "sections": [{"title": "三天安排", "body": "福冈三天要轻松一点，按博多/天神、太宰府、市内海边拆。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "福冈 三天 轻松 行程 博多 天神 太宰府 百道", "category": "本地体验"},
                            "required": True,
                        }
                    ],
                    "data_gaps": [],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("3-day itinerary should be finalized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = FukuokaThreeDayAgentClient()
    response = await _supervisor(agent_client, FukuokaThreeDaySerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="第一次去福冈，三天怎么安排轻松一点？", pace="relaxed", allow_web_search=True)
    )

    markdown = response.formatted_markdown
    assert response.answer_mode == "itinerary"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert "第1天" in markdown and "第2天" in markdown and "第3天" in markdown
    assert "博多" in markdown and "天神" in markdown
    assert "太宰府" in markdown
    assert "百道" in markdown or "福冈塔" in markdown or "海滨" in markdown
    assert "轻松" in markdown or "低强度" in markdown or "缓冲" in markdown
    assert "同区" in markdown or "回城" in markdown or "西铁" in markdown or "地铁" in markdown
    assert "河豚" not in markdown
    assert "安全" not in markdown
    assert len(response.itinerary_plan.days) == 3
    assert not any(call["payload"].get("phase") == "final_answer" for call in agent_client.calls)


@pytest.mark.asyncio
async def test_obvious_itinerary_places_tool_passes_category_not_long_query_to_search_local():
    class RecordingSerperClient(FukuokaThreeDaySerperClient):
        def __init__(self) -> None:
            super().__init__()
            self.categories_seen: list[str] = []

        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            self.categories_seen.append(category)
            return await super().search_local(request, category)

    serper = RecordingSerperClient()
    await _supervisor(OrchestratorAgentClient(), serper).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="帮我做一个福冈 3 天 2 晚初访行程，节奏不要太赶。",
            pace="relaxed",
            allow_web_search=True,
        )
    )

    assert serper.categories_seen == ["本地体验"]


@pytest.mark.asyncio
async def test_obvious_three_day_itinerary_overrides_misclassified_food_contract():
    class MisclassifiedFoodAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and payload.get("phase") == "final_answer":
                raise AssertionError("obvious itinerary should be finalized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = MisclassifiedFoodAgentClient()
    serper = FukuokaThreeDaySerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="帮我做一个福冈 3 天 2 晚初访行程，节奏不要太赶。",
            pace="relaxed",
            allow_web_search=True,
        )
    )

    markdown = response.formatted_markdown
    assert response.answer_mode == "itinerary"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert all(f"第{day}天" in markdown for day in range(1, 4))
    assert "博多" in markdown and "天神" in markdown
    assert "太宰府" in markdown
    assert "百道" in markdown or "福冈塔" in markdown or "海滨" in markdown
    assert "河豚" not in markdown
    assert "餐厅" not in markdown
    assert len(response.itinerary_plan.days) == 3
    assert not any(
        call["agent_name"] == "travel_orchestrator" and not call["payload"].get("phase")
        for call in agent_client.calls
    )
    assert not any(call["payload"].get("phase") == "final_answer" for call in agent_client.calls)
    assert any(call.startswith("serper_places:") for call in serper.calls)
    requested_tools = response.raw_provider_refs["travel_orchestrator"]["tool_calls_requested"]
    places_call = next(call for call in requested_tools if call["name"] == "serper_places")
    assert places_call["arguments"]["category"] == "本地体验"
    assert "行程" in places_call["arguments"]["query"]


@pytest.mark.asyncio
async def test_empty_obvious_fukuoka_itinerary_uses_city_anchors_without_final_model():
    class NoModelFinalAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator":
                raise AssertionError("obvious city itinerary should not call GPT orchestrator or final synthesis")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = NoModelFinalAgentClient()
    serper = EmptyFukuokaItinerarySerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="帮我做一个福冈 3 天 2 晚初访行程，节奏不要太赶。",
            pace="relaxed",
            allow_web_search=True,
        )
    )

    titles = [card.title for card in response.display_cards]
    assert response.answer_mode == "itinerary"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert response.llm_used is False
    assert response.model_used == "deterministic"
    assert response.raw_provider_refs["travel_orchestrator"]["model"] == "deterministic"
    assert agent_client.calls == []
    assert any(call.startswith("serper_places:") for call in serper.calls)
    assert len(response.itinerary_plan.days) == 3
    assert len(response.display_cards) >= 5
    assert len(response.map_view["pins"]) >= 5
    assert titles[:5] == ["博多旧市街", "天神", "太宰府天满宫", "大濠公园", "百道海滨"]
    assert "第1天" in response.formatted_markdown and "第3天" in response.formatted_markdown
    assert "河豚" not in response.formatted_markdown and "KKday" not in response.formatted_markdown


@pytest.mark.asyncio
async def test_sparse_itinerary_places_are_completed_with_map_ready_city_anchors():
    class MisclassifiedFoodAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and payload.get("phase") == "final_answer":
                raise AssertionError("sparse obvious itinerary should be finalized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(MisclassifiedFoodAgentClient(), FukuokaSparseItinerarySerperClient()).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="帮我做一个福冈 3 天 2 晚初访行程，节奏不要太赶。",
            pace="relaxed",
            allow_web_search=True,
        )
    )

    titles = [card.title for card in response.display_cards]
    markdown = response.formatted_markdown
    assert response.answer_mode == "itinerary"
    assert response.map_view["status"] == "ready"
    assert len(response.map_view["pins"]) >= 3
    assert len(response.display_cards) >= 3
    assert "太宰府天满宫" in titles
    assert "博多旧市街" in titles or "博多" in markdown
    assert "天神" in titles or "天神" in markdown
    assert "百道海滨" in titles or "大濠公园" in titles or "福冈塔" in titles
    assert "KKday" not in markdown
    assert "搜尋的關鍵字" not in markdown
    assert len({block.title for day in response.itinerary_plan.days for block in day.time_blocks}) >= 3


@pytest.mark.asyncio
async def test_fukuoka_three_day_itinerary_reorders_map_ready_cards_into_city_skeleton():
    class MisclassifiedFoodAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and payload.get("phase") == "final_answer":
                raise AssertionError("obvious itinerary should keep deterministic finalization even with many cards")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(MisclassifiedFoodAgentClient(), FukuokaMixedOrderItinerarySerperClient()).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="帮我做一个福冈 3 天 2 晚初访行程，节奏不要太赶。",
            pace="relaxed",
            allow_web_search=True,
        )
    )

    day_titles = [
        [re.sub(r"^(上午|下午|傍晚)：", "", block.title) for block in day.time_blocks]
        for day in response.itinerary_plan.days
    ]
    markdown = response.formatted_markdown
    assert response.answer_mode == "itinerary"
    assert len(response.map_view["pins"]) >= 5
    assert len(response.itinerary_plan.days) == 3
    assert any("博多" in title for title in day_titles[0])
    assert any("天神" in title for title in day_titles[0])
    assert any("太宰府" in title for title in day_titles[1])
    assert any("大濠" in title for title in day_titles[1])
    assert any(("百道" in title or "Fukuoka Tower" in title or "福冈塔" in title or "Momochi" in title) for title in day_titles[2])
    assert not any("太宰府" in title for title in day_titles[0] + day_titles[2])
    assert not any("海之中道" in title for day in day_titles for title in day)
    assert not any("海之中道" in card.title for card in response.display_cards)
    assert not any("海之中道" in str(pin.get("title") or "") for pin in response.map_view["pins"])
    assert "第1天" in markdown and "第2天" in markdown and "第3天" in markdown
    assert "河豚" not in markdown and "KKday" not in markdown
    assert "Haystack" not in markdown and "PydanticAI" not in markdown and "Langfuse" not in markdown


class KyotoOsakaFourDaySerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "京都站",
                    "snippet": "京都住宿和换乘的稳定锚点，适合前两晚住京都。",
                    "type": "交通枢纽",
                    "rating": 4.3,
                    "reviews": 20000,
                    "address": "Kyoto Station, Kyoto",
                    "latitude": 34.9858,
                    "longitude": 135.7588,
                    "place_id": "kyoto-station-4day",
                    "query_variant": category,
                },
                {
                    "title": "祇园",
                    "snippet": "京都东山夜间散步方便，适合京都段的一晚。",
                    "type": "历史街区",
                    "rating": 4.4,
                    "reviews": 15000,
                    "address": "Gion, Kyoto",
                    "latitude": 35.0037,
                    "longitude": 135.7751,
                    "place_id": "gion-4day",
                    "query_variant": category,
                },
                {
                    "title": "伏见稻荷大社",
                    "snippet": "适合京都段早去，之后再移动到大阪比较顺。",
                    "type": "神社",
                    "rating": 4.6,
                    "reviews": 71000,
                    "address": "Fushimi Ward, Kyoto",
                    "latitude": 34.9671,
                    "longitude": 135.7727,
                    "place_id": "fushimi-inari-4day",
                    "query_variant": category,
                },
                {
                    "title": "梅田",
                    "snippet": "大阪交通和住宿方便，适合最后一晚住大阪。",
                    "type": "商业交通区",
                    "rating": 4.3,
                    "reviews": 32000,
                    "address": "Umeda, Osaka",
                    "latitude": 34.7025,
                    "longitude": 135.4959,
                    "place_id": "umeda-4day",
                    "query_variant": category,
                },
                {
                    "title": "难波",
                    "snippet": "大阪餐饮和夜间活动集中，适合作为大阪段主区域。",
                    "type": "街区",
                    "rating": 4.4,
                    "reviews": 28000,
                    "address": "Namba, Osaka",
                    "latitude": 34.6658,
                    "longitude": 135.5011,
                    "place_id": "namba-4day",
                    "query_variant": category,
                },
            ],
        )


@pytest.mark.asyncio
async def test_kyoto_osaka_four_day_plan_includes_one_lodging_move_and_all_days():
    class KyotoOsakaFourDayAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "itinerary",
                    "sections": [{"title": "住宿策略", "body": "京都大阪四天只换一次酒店：京都前两晚，大阪最后一晚。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "京都 大阪 四天 一次换酒店 行程", "category": "本地体验"},
                            "required": True,
                        }
                    ],
                    "data_gaps": [],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("4-day Kyoto/Osaka itinerary should be finalized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(KyotoOsakaFourDayAgentClient(), KyotoOsakaFourDaySerperClient()).plan(
        TravelPlanRequest(city="Kyoto", query="京都大阪4天只想换一次酒店，怎么安排？", allow_web_search=True)
    )

    markdown = response.formatted_markdown
    assert response.answer_mode == "itinerary"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert all(f"第{day}天" in markdown for day in range(1, 5))
    assert "京都" in markdown and "大阪" in markdown
    assert "前两晚" in markdown or "2晚" in markdown
    assert "最后一晚" in markdown or "第3晚" in markdown
    assert "换酒店" in markdown or "移动到大阪" in markdown
    assert "Day 1-4" not in markdown
    assert len(response.itinerary_plan.days) == 4


@pytest.mark.asyncio
async def test_obvious_fukuoka_first_timer_recommendation_uses_fast_path_without_gpt():
    class NoModelFirstTimerAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator":
                raise AssertionError("obvious first-timer recommendation should not call GPT orchestrator or final synthesis")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = NoModelFirstTimerAgentClient()
    serper = FukuokaFirstTimerSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈第一次去，有哪些地方值得去？给我几个适合新手的点。", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert response.llm_used is False
    assert response.model_used == "deterministic"
    assert response.raw_provider_refs["travel_orchestrator"]["model"] == "deterministic"
    assert agent_client.calls == []
    assert serper.calls == ["serper_places:本地体验"]
    assert response.display_cards
    assert response.map_view["status"] == "ready"
    assert len(response.map_view["pins"]) >= 3
    assert "第一次" in response.formatted_markdown
    assert "交通" in response.formatted_markdown or "顺路" in response.formatted_markdown


@pytest.mark.asyncio
async def test_empty_obvious_fukuoka_first_timer_recommendation_uses_city_anchors_without_gpt():
    class NoModelFirstTimerAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator":
                raise AssertionError("obvious first-timer recommendation should use deterministic city anchors")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = NoModelFirstTimerAgentClient()
    serper = EmptyFukuokaItinerarySerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈第一次去，有哪些地方值得去？给我几个适合新手的点。", allow_web_search=True)
    )

    titles = [card.title for card in response.display_cards]
    assert response.answer_mode == "place_cards"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert agent_client.calls == []
    assert serper.calls == ["serper_places:本地体验"]
    assert len(response.display_cards) >= 5
    assert response.map_view["status"] == "ready"
    assert len(response.map_view["pins"]) >= 5
    assert titles[:5] == ["博多旧市街", "天神", "太宰府天满宫", "大濠公园", "百道海滨"]
    assert "第一次" in response.formatted_markdown
    assert "交通" in response.formatted_markdown or "顺路" in response.formatted_markdown
    assert "没有可核验地点" not in response.formatted_markdown


@pytest.mark.asyncio
async def test_obvious_fukuoka_first_timer_suppresses_raw_serper_failure_when_anchor_cards_cover_answer():
    class NoModelFirstTimerAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator":
                raise AssertionError("anchor-backed first-timer answer should not call GPT")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(NoModelFirstTimerAgentClient(), MinimalSerperClient(fail_places=True)).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈第一次去，有哪些地方值得去？给我几个适合新手的点。", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert len(response.display_cards) >= 5
    assert response.map_view["status"] == "ready"
    assert response.llm_used is False
    assert response.model_used == "deterministic"
    assert not response.data_gaps
    assert not response.optional_followups
    runtime_warnings = response.raw_provider_refs.get("model_runtime_warnings", [])
    assert not any("serper_places" in warning or "HTTP 502" in warning for warning in runtime_warnings)
    assert "HTTP 502" not in response.formatted_markdown
    assert "serper_places" not in response.formatted_markdown


@pytest.mark.asyncio
async def test_first_timer_cards_explain_practical_fit_not_rating_address_metadata():
    class FukuokaFirstTimerAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "place_cards",
                    "sections": [{"title": "怎么选", "body": "第一次去福冈要选交通简单、城市代表性强、停留弹性的点。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "福冈 第一次 新手 推荐 景点", "category": "本地体验"},
                            "required": True,
                        }
                    ],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("first-timer cards should be summarized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(FukuokaFirstTimerAgentClient(), FukuokaFirstTimerSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈第一次去，有哪些地方值得去？给我几个适合新手的点。", allow_web_search=True)
    )

    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert response.display_cards
    markdown = response.formatted_markdown
    assert "第一次" in markdown
    assert "半日" in markdown or "2天" in markdown or "Day" in markdown
    assert "交通" in markdown or "顺路" in markdown
    assert "停留" in markdown or "时段" in markdown
    assert "评分 4.5；位置" not in markdown
    assert not re.search(r"新手(?:主候选|备选)：[^：\n]+（评分", markdown)
    assert not any((card.display_reason or "").startswith("推荐理由：评分") for card in response.display_cards[:3])
    assert any("散步" in (card.display_reason or "") or "半日" in (card.display_reason or "") for card in response.display_cards[:3])
    top_titles = [card.title for card in response.display_cards[:3]]
    assert not ("大濠公园" in top_titles and "Ukimi-do Pavilion (Ohori Park)" in top_titles)
    assert len({card.display_reason for card in response.display_cards[:3]}) == len(response.display_cards[:3])
    momochihama = next(card for card in response.display_cards if card.title == "Momochihama Beach")
    assert "海" in momochihama.display_reason or "海滨" in momochihama.display_reason
    assert "湖边" not in momochihama.display_reason
    kushida = next(card for card in response.display_cards if card.title == "栉田神社")
    assert "老城区" in kushida.display_reason or "短停" in kushida.display_reason
    assert "湖边" not in kushida.display_reason


@pytest.mark.asyncio
async def test_gpt_orchestrator_retries_transient_serper_places_once_without_fallback():
    agent_client = OrchestratorAgentClient()
    serper = FlakyOnceSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    assert serper.local_attempts == 2
    assert response.display_cards
    assert not any("HTTP 502" in gap for gap in response.data_gaps)
    assert any(
        item.get("name") == "serper_places" and item.get("attempts") == 2
        for item in response.raw_provider_refs["tool_trace"]
    )


@pytest.mark.asyncio
async def test_gpt_orchestrator_uses_freeform_multimodal_guidance_for_outdoor_places():
    agent_client = OrchestratorAgentClient()
    response = await _supervisor(agent_client, OutdoorSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有什么自然风光？我喜欢步行", allow_web_search=True)
    )

    framework = response.raw_provider_refs["travel_orchestrator"]["answer_framework_spec"]
    assert framework["name"] == "freeform_multimodal_travel_v1"
    assert framework["structure_policy"] == "freeform"
    assert framework["section_titles"] == []
    assert any("自由组织答案" in str(rule) for rule in framework["public_rules"])
    assert any("广告" in str(rule) for rule in framework["public_rules"])
    assert not any("三个一级栏目" in str(rule) or "怎么选、去哪儿" in str(rule) for rule in framework["public_rules"])

    markdown = response.formatted_markdown
    assert "步行" in markdown
    assert "大濠公园" in markdown
    assert "我会先这样看" not in markdown
    assert "当地评价" not in markdown
    assert "Reddit" not in markdown
    assert "reddit" not in markdown.lower()
    assert response.raw_provider_refs["travel_orchestrator"]["answer_framework"] == "freeform_multimodal_travel_v1"
    public_payload = (
        response.formatted_markdown
        + "\n"
        + str(response.narrative_answer or "")
        + "\n"
        + str(response.raw_provider_refs.get("travel_orchestrator", {}))
    )
    for forbidden in [
        "Mind" + "trip",
        "mind" + "trip",
        "按 " + "Mind" + "trip",
        "竞品",
        "旅行规划产品",
    ]:
        assert forbidden not in public_payload


@pytest.mark.asyncio
async def test_gpt_orchestrator_skips_final_model_when_cards_can_be_deterministically_summarized():
    agent_client = OrchestratorAgentClient()
    response = await _supervisor(agent_client, OutdoorSerperClient()).plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么自然风光？我喜欢步行",
            previous_context={"city": "Fukuoka", "preferences": ["户外风光"]},
            allow_web_search=True,
        )
    )

    assert response.workflow_status == "completed"
    assert response.display_cards
    assert "大濠公园" in response.formatted_markdown
    assert "步行" in response.formatted_markdown
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert not any(call["payload"].get("phase") == "final_answer" for call in agent_client.calls)

    first_section = response.answer_sections[0]
    top_card_ids = [card.id for card in response.display_cards[:3]]
    top_pin_ids = [pin["id"] for pin in response.map_view["pins"][:3]]
    assert first_section.title == "怎么选"
    assert first_section.card_ids == top_card_ids
    assert first_section.pin_ids == top_pin_ids
    assert len(response.answer_sections) <= 3
    assert all(len(section.bullets) <= 4 for section in response.answer_sections)
    assert len(response.formatted_markdown) < 1600
    assert "兴趣匹配" in response.formatted_markdown
    assert "动线时间" in response.formatted_markdown
    assert "地图" in response.answer_sections[-1].title or "地图" in response.answer_sections[-1].body
    assert "先看这 3 个" not in response.formatted_markdown
    assert "先保存前 3 张卡片" not in response.formatted_markdown


class TwoCardFamilySerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "国立科学博物馆",
                    "snippet": "恐龙、自然科学展陈集中，适合 6 岁孩子低疲劳参观。",
                    "type": "科学博物馆",
                    "rating": 4.5,
                    "reviews": 13000,
                    "address": "7-20 Uenokoen, Tokyo",
                    "latitude": 35.7163,
                    "longitude": 139.7765,
                    "place_id": "science-museum",
                    "query_variant": category,
                },
                {
                    "title": "上野动物园",
                    "snippet": "同在上野公园内，适合和博物馆二选一或短时间补充。",
                    "type": "动物园",
                    "rating": 4.2,
                    "reviews": 21000,
                    "address": "9-83 Uenokoen, Tokyo",
                    "latitude": 35.7168,
                    "longitude": 139.7711,
                    "place_id": "ueno-zoo",
                    "query_variant": category,
                },
            ],
        )


@pytest.mark.asyncio
async def test_deterministic_card_summary_adapts_title_to_actual_card_count():
    class TokyoFamilyAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "place_cards",
                    "sections": [{"title": "怎么选", "body": "亲子半日要优先低疲劳、同区域和可休息。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "东京 6岁 亲子 半日 上野", "category": "亲子"},
                            "required": True,
                        }
                    ],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("card/map deterministic summary should not call final_answer")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(TokyoFamilyAgentClient(), TwoCardFamilySerperClient()).plan(
        TravelPlanRequest(city="Tokyo", query="东京带6岁孩子不太累的半日安排", allow_web_search=True)
    )

    assert len(response.display_cards) == 2
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert "先看这 3 个" not in response.formatted_markdown
    assert "前 3 张" not in response.formatted_markdown
    assert any("半日" in section.body or any("半日" in bullet for bullet in section.bullets) for section in response.answer_sections)
    assert "6 岁" in response.formatted_markdown or "6岁" in response.formatted_markdown
    assert "低疲劳" in response.formatted_markdown or "不太累" in response.formatted_markdown
    assert "自然和户外" not in response.formatted_markdown


class OsakaFoodAreaSerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "MJ Guesthouse Osaka",
                    "snippet": "Budget guesthouse near Osaka attractions.",
                    "type": "Guest house",
                    "rating": 5.0,
                    "reviews": 34,
                    "query_variant": category,
                },
                {
                    "title": "TAKUTO STAY SAKAISUJI-HOMMACHI - Maisonette",
                    "snippet": "Apartment hotel stay in Osaka.",
                    "type": "Hotel",
                    "rating": 4.9,
                    "reviews": 88,
                    "query_variant": category,
                },
                {
                    "title": "新世界",
                    "snippet": "串カツ、通天阁周边和老派小吃集中，适合避开只逛道顿堀。",
                    "type": "Food neighborhood",
                    "rating": 4.3,
                    "reviews": 6200,
                    "address": "Ebisuhigashi, Naniwa Ward, Osaka",
                    "latitude": 34.6525,
                    "longitude": 135.5063,
                    "place_id": "shinsekai",
                    "query_variant": category,
                },
                {
                    "title": "天满",
                    "snippet": "天神桥筋商店街和立饮小店多，适合本地小吃和晚间随走随吃。",
                    "type": "Food area",
                    "rating": 4.2,
                    "reviews": 2100,
                    "address": "Tenma, Kita Ward, Osaka",
                    "latitude": 34.704,
                    "longitude": 135.512,
                    "place_id": "tenma",
                    "query_variant": category,
                },
            ],
        )


@pytest.mark.asyncio
async def test_food_area_query_filters_lodging_candidates_from_primary_cards():
    class OsakaFoodAreaAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "place_cards",
                    "sections": [{"title": "怎么选", "body": "要找道顿堀之外的小吃区域，而不是住宿。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "大阪 道顿堀 之外 本地 小吃 区域", "category": "本地小吃区域"},
                            "required": True,
                        }
                    ],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("food-area cards should be summarized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(OsakaFoodAreaAgentClient(), OsakaFoodAreaSerperClient()).plan(
        TravelPlanRequest(city="Osaka", query="大阪除了道顿堀，还有哪些本地小吃区域？", allow_web_search=True)
    )

    titles = [card.title for card in response.display_cards]
    assert "新世界" in titles
    assert "天满" in titles
    assert not any("Guesthouse" in title or "Hotel" in title or "STAY" in title for title in titles)
    assert "MJ Guesthouse" not in response.formatted_markdown
    assert "TAKUTO STAY" not in response.formatted_markdown
    assert "道顿堀之外" in response.formatted_markdown or "只去道顿堀" in response.formatted_markdown
    assert "河豚" not in response.formatted_markdown


class GenericReviewPageSerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "Reviews for Local Tastes of Dotonbori: Osaka Night Food Adventure",
                    "snippet": "Read 261 reviews for a paid night food adventure.",
                    "type": "Review page",
                    "rating": 5.0,
                    "link": "https://example.com/reviews/dotonbori-food-tour",
                    "query_variant": category,
                },
                {
                    "title": "道頓堀 - Updated June 2026 - 1892 Photos & 158 Reviews - Yelp",
                    "snippet": "Yelp review listing for Dotonbori.",
                    "type": "Review site",
                    "rating": 4.5,
                    "link": "https://www.yelp.com/biz/dotonbori-osaka",
                    "query_variant": category,
                },
                {
                    "title": "大阪城公园",
                    "snippet": "免费散步空间，适合低预算两天行程中安排半天。",
                    "type": "公园",
                    "rating": 4.3,
                    "reviews": 72000,
                    "address": "Osakajo, Chuo Ward, Osaka",
                    "latitude": 34.6873,
                    "longitude": 135.5262,
                    "place_id": "osaka-castle-park",
                    "query_variant": category,
                },
            ],
        )


@pytest.mark.asyncio
async def test_generic_review_pages_do_not_become_primary_trip_cards():
    class BudgetOsakaAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "place_cards",
                    "sections": [{"title": "怎么选", "body": "低预算两天要优先免费街区、公园和便宜小吃。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "大阪 两天 低预算 免费 景点 小吃", "category": "本地体验"},
                            "required": True,
                        }
                    ],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("budget cards should be summarized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(BudgetOsakaAgentClient(), GenericReviewPageSerperClient()).plan(
        TravelPlanRequest(city="Osaka", query="大阪低预算两天怎么玩，但不要太无聊", budget="低预算", allow_web_search=True)
    )

    titles = [card.title for card in response.display_cards]
    assert "大阪城公园" in titles
    assert not any("Reviews for" in title or "Yelp" in title for title in titles)
    assert "Yelp" not in response.formatted_markdown
    assert "review listing" not in response.formatted_markdown.lower()
    assert "低预算" in response.formatted_markdown
    assert "两天" in response.formatted_markdown
    assert "自然和户外" not in response.formatted_markdown


class SapporoWinterSerperClient(MinimalSerperClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"serper_places:{category}",
            [
                {
                    "title": "藻岩山纜車",
                    "snippet": "夜景缆车，天气差时体验会明显受影响。",
                    "type": "山缆车",
                    "rating": 4.6,
                    "place_id": "moiwa-ropeway",
                    "query_variant": category,
                },
                {
                    "title": "藻岩山 山顶展望台",
                    "snippet": "藻岩山同一夜景系统的山顶观景点。",
                    "type": "展望台",
                    "rating": 4.5,
                    "address": "Moiwa Sancho Station, Sapporo",
                    "latitude": 43.022,
                    "longitude": 141.322,
                    "place_id": "moiwa-observatory",
                    "query_variant": category,
                },
                {
                    "title": "藻岩山",
                    "snippet": "同属藻岩山夜景区域。",
                    "type": "山",
                    "rating": 4.5,
                    "place_id": "moiwa-mountain",
                    "query_variant": category,
                },
                {
                    "title": "札幌啤酒博物馆",
                    "snippet": "冬天室内友好，适合第一次到札幌了解城市和啤酒文化。",
                    "type": "博物馆",
                    "rating": 4.2,
                    "address": "Kita 7 Johigashi, Sapporo",
                    "latitude": 43.0715,
                    "longitude": 141.3697,
                    "place_id": "sapporo-beer-museum",
                    "query_variant": category,
                },
                {
                    "title": "小樽运河",
                    "snippet": "冬季雪景和灯光氛围好，适合做札幌近郊半日或一日。",
                    "type": "景点",
                    "rating": 4.2,
                    "address": "Otaru, Hokkaido",
                    "latitude": 43.1986,
                    "longitude": 141.0012,
                    "place_id": "otaru-canal",
                    "query_variant": category,
                },
            ],
        )


@pytest.mark.asyncio
async def test_duplicate_landmark_variants_do_not_fill_top_structured_cards():
    class SapporoWinterAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and not payload.get("phase"):
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "place_cards",
                    "sections": [{"title": "怎么选", "body": "第一次冬天去札幌要兼顾雪景、室内备选和交通风险。"}],
                    "tool_calls_requested": [
                        {
                            "name": "serper_places",
                            "arguments": {"query": "札幌 冬天 第一次 推荐 雪景 室内", "category": "本地体验"},
                            "required": True,
                        }
                    ],
                }
            if payload.get("phase") == "final_answer":
                raise AssertionError("winter recommendation cards should be summarized deterministically")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(SapporoWinterAgentClient(), SapporoWinterSerperClient()).plan(
        TravelPlanRequest(city="Sapporo", query="第一次冬天去札幌，除了雪祭还能玩什么？", allow_web_search=True)
    )

    top_titles = [card.title for card in response.display_cards[:3]]
    assert sum(1 for title in top_titles if "藻岩" in title) <= 1
    assert any(title in top_titles for title in ["札幌啤酒博物馆", "小樽运河"])
    assert "冬" in response.formatted_markdown
    assert "雪祭" in response.formatted_markdown or "天气" in response.formatted_markdown


@pytest.mark.asyncio
async def test_gpt_orchestrator_retries_truncated_final_answer_stage_once():
    class TruncatedOnceFinalAnswerAgentClient(OrchestratorAgentClient):
        def __init__(self) -> None:
            super().__init__()
            self.final_attempts = 0

        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and payload.get("phase") == "final_answer":
                self.final_attempts += 1
                if self.final_attempts == 1:
                    raise ValueError("Unterminated string starting at: line 19 column 9 (char 1081)")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = TruncatedOnceFinalAnswerAgentClient()
    response = await _supervisor(agent_client, MinimalSerperClient()).plan(
        TravelPlanRequest(city="Kyoto", query="东京到京都怎么走？", allow_web_search=True)
    )

    assert response.workflow_status == "completed"
    assert agent_client.final_attempts == 2
    assert response.answer_mode == "route_map"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "final_model_with_tools"
    assert not any("Unterminated string" in gap for gap in response.data_gaps)


@pytest.mark.asyncio
async def test_gpt_orchestrator_enforces_places_tool_for_broad_place_discovery():
    class AnswerOnlyPlaceDiscoveryAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and payload.get("phase") != "final_answer":
                self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
                return {
                    "answer_mode": "answer_only",
                    "sections": [
                        {
                            "title": "怎么选",
                            "body": "福冈自然风光适合步行，可以按兴趣匹配、口碑确认、动线时间和可执行性来筛。",
                        }
                    ],
                    "tool_calls_requested": [],
                    "cards": [
                        {"id": "ohori", "title": "大濠公园", "category": "本地体验"},
                    ],
                }
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(AnswerOnlyPlaceDiscoveryAgentClient(), OutdoorSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有什么自然风光？我喜欢步行", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert response.display_cards
    assert response.map_view["status"] == "ready"
    assert response.raw_provider_refs["travel_orchestrator"]["tool_calls_requested"][0]["name"] == "serper_places"


@pytest.mark.asyncio
async def test_gpt_orchestrator_does_not_force_legacy_topic_dimensions():
    class LegacyDimensionAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator" and payload.get("phase") == "final_answer":
                raise AssertionError("simplified travel flow must not call the final_answer model stage")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    response = await _supervisor(LegacyDimensionAgentClient(), OutdoorSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有什么自然风光？我喜欢步行", allow_web_search=True)
    )

    assert response.display_cards
    assert "大濠公园" in response.formatted_markdown
    assert response.raw_provider_refs["travel_orchestrator"]["answer_framework"] == "freeform_multimodal_travel_v1"


@pytest.mark.asyncio
async def test_gpt_orchestrator_places_failure_reports_gap_without_fake_cards():
    agent_client = OrchestratorAgentClient()
    serper = MinimalSerperClient(fail_places=True)
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    assert response.display_cards == []
    assert response.map_view["status"] in {"needs_coordinates", "answer_only"}
    assert any("serper_places" in gap or "HTTP 502" in gap for gap in response.data_gaps)


@pytest.mark.asyncio
async def test_gpt_orchestrator_images_tool_can_use_current_query_when_arguments_are_empty():
    class EmptyImageArgsAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "去哪儿", "body": "按当前问题找地点和图片。"}],
                "tool_calls_requested": [
                    {
                        "name": "serper_places",
                        "arguments": {"query": "广岛 户外风光", "category": "本地体验"},
                        "required": True,
                    },
                    {"name": "serper_images", "arguments": {}, "required": True},
                ],
            }

    serper = MinimalSerperClient()
    response = await _supervisor(EmptyImageArgsAgentClient(), serper).plan(
        TravelPlanRequest(city="Hiroshima", query="广岛有什么好玩的？；用户补充偏好或约束：我喜欢户外风光", allow_web_search=True)
    )

    assert response.workflow_status == "completed"
    assert any(call.startswith("serper_images:广岛有什么好玩的？") for call in serper.calls)


@pytest.mark.asyncio
async def test_gpt_orchestrator_rejects_tool_call_with_missing_required_arguments():
    class BadToolAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "去哪儿", "body": "需要地点工具。"}],
                "tool_calls_requested": [
                    {"name": "serper_places", "arguments": {}, "required": True},
                ],
            }

    with pytest.raises(TravelModelCallError, match="tool_validation"):
        await _supervisor(BadToolAgentClient(), MinimalSerperClient()).plan(
            TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
        )


@pytest.mark.asyncio
async def test_gpt_orchestrator_deduplicates_repeated_tool_calls():
    class DuplicateToolAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "去哪儿", "body": "用真实地点和评论回答。"}],
                "tool_calls_requested": [
                    {
                        "name": "serper_search",
                        "arguments": {"query": "福冈 河豚 口コミ reddit"},
                        "required": False,
                    },
                    {
                        "name": "serper_search",
                        "arguments": {"query": "福冈 河豚 reddit local reviews"},
                        "required": False,
                    },
                    {
                        "name": "serper_places",
                        "arguments": {"query": "福冈 博多 河豚 料理", "category": "美食"},
                        "required": True,
                    },
                    {
                        "name": "serper_places",
                        "arguments": {"query": "福冈 河豚 料理", "category": "美食"},
                        "required": True,
                    },
                ],
            }

    serper = MinimalSerperClient()
    response = await _supervisor(DuplicateToolAgentClient(), serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    assert response.workflow_status == "completed"
    assert sum(1 for call in serper.calls if call.startswith("serper_search:")) == 1
    assert sum(1 for call in serper.calls if call.startswith("serper_places:")) == 1


@pytest.mark.asyncio
async def test_gpt_orchestrator_normalizes_known_serper_tool_name_typo():
    class TypoToolAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            self.calls.append({"agent_name": agent_name, "model": model, "prompt": prompt, "payload": payload})
            if agent_name == "travel_orchestrator" and payload.get("phase") == "final_answer":
                return {
                    "answer_mode": "place_cards",
                    "sections": [{"title": "去哪儿", "body": "工具名已规范化，使用真实地点回答。"}],
                    "tool_calls_requested": [],
                }
            return {
                "answer_mode": "place_cards",
                "sections": [{"title": "去哪儿", "body": "需要 Serper Places。"}],
                "tool_calls_requested": [
                    {
                        "name": "serser_places",
                        "arguments": {"query": "福冈 自然 户外 风光", "category": "本地体验"},
                        "required": True,
                    }
                ],
            }

    response = await _supervisor(TypoToolAgentClient(), OutdoorSerperClient()).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈有什么自然风光？我喜欢步行", allow_web_search=True)
    )

    assert response.workflow_status == "completed"
    assert any(call.startswith("serper_places:") for call in response.search_queries) or response.display_cards
    assert response.raw_provider_refs["travel_orchestrator"]["tool_calls_requested"][0]["name"] == "serper_places"
