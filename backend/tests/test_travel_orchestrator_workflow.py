from __future__ import annotations

import asyncio

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
    assert first_section.title == "先看这 3 个"
    assert first_section.card_ids == top_card_ids
    assert first_section.pin_ids == top_pin_ids
    assert len(response.answer_sections) <= 2
    assert all(len(section.bullets) <= 3 for section in response.answer_sections)
    assert len(response.formatted_markdown) < 900
    assert "地图" in response.answer_sections[-1].title or "地图" in response.answer_sections[-1].body


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
