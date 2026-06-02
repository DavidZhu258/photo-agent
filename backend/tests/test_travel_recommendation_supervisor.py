from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.schemas.travel import TravelDisplayCard, TravelPlanRequest, TravelPlanResponse, TravelSuggestionGroup
from app.services.travel_recommendation_supervisor import (
    AgentModelRouter,
    LiteLLMTravelAgentClient,
    TravelRecommendationSupervisor,
    _display_cards,
    _should_cache_travel_response,
)
from app.services.travel_query_understanding import (
    SearchPlan,
    TravelCapabilityPlan,
    TravelIntent,
    TravelModelCallError,
    TripPlanDraft,
)


TRAVEL_FAST_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
TRAVEL_SEMANTIC_MODEL = "google/gemini-3.1-pro"
TRAVEL_REASONING_MODEL = "openai/gpt-oss-120b"
TRAVEL_CRITIC_MODEL = "openai/gpt-oss-120b"
TRAVEL_REASONING_EFFORT = "high"


def test_display_cards_do_not_materialize_fallback_group_items_without_real_place_payloads():
    cards = _display_cards(
        TravelPlanRequest(city="Hiroshima", query="我喜欢户外风光，怎么排？", allow_web_search=True),
        api_payloads={},
        groups=[
            TravelSuggestionGroup(
                title="本地体验",
                intent="从真实地点里筛选户外体验。",
                items=["Hiroshima 本地体验 候选 1", "Hiroshima 本地体验 候选 2"],
                reason="占位候选不能伪装成地图卡片。",
            )
        ],
    )

    assert cards == []


class FakeSerpApiTravelClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def travel_explore(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "google_travel_explore",
            [{"name": "Fukuoka", "flight_price": "$180", "reason": "spring food trip"}],
        )

    async def search_flights(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "google_flights",
            [{"title": "HND -> FUK", "price": "$180", "duration": "2h"}],
        )

    async def search_hotels(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "google_hotels",
            [{"name": "Hotel Okura Fukuoka", "rate": "$140", "rating": 4.4}],
        )

    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"google_maps:{category}",
            [
                {
                    "title": f"{category} pick 1",
                    "rating": 4.5,
                    "reviews": 120,
                    "address": "Fukuoka",
                    "latitude": 33.5902,
                    "longitude": 130.4017,
                    "place_id": "ChIJFoodPick1",
                    "photo_attributions": ["Example Photographer"],
                    "thumbnailUrl": "https://example.com/pick-1-thumb.jpg",
                    "imageUrl": "https://example.com/pick-1-large.jpg",
                    "images": [
                        {"imageUrl": "https://example.com/pick-1-gallery-2.jpg"},
                        {"thumbnailUrl": "https://example.com/pick-1-gallery-3-thumb.jpg"},
                    ],
                },
                {
                    "title": f"{category} pick 2",
                    "rating": 4.3,
                    "reviews": 80,
                    "address": "Fukuoka",
                    "latitude": 33.5920,
                    "longitude": 130.4050,
                    "thumbnailUrl": "https://example.com/pick-2.jpg",
                },
                {
                    "title": f"{category} pick 3",
                    "rating": 4.1,
                    "reviews": 64,
                    "address": "Fukuoka",
                    "latitude": 33.5880,
                    "longitude": 130.3970,
                },
            ],
        )

    async def search_images(self, request: TravelPlanRequest, query: str) -> list[dict]:
        return await self._record(
            f"images:{query}",
            [
                {"imageUrl": f"https://example.com/{query.replace(' ', '-')}-wide-1.jpg"},
                {"imageUrl": f"https://example.com/{query.replace(' ', '-')}-wide-2.jpg"},
            ],
        )

    async def search_budget(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "budget",
            [{"title": "Fukuoka daily budget", "snippet": "$90-140/day plus transport"}],
        )

    async def search_transport(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "transport",
            [{"title": "Fukuoka subway and train", "snippet": "Subway, JR, buses, taxi"}],
        )

    async def search_visa(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "visa",
            [{"title": "Japan visa policy", "snippet": "Check entry requirements"}],
        )

    async def search_weather(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "weather",
            [{"title": "Fukuoka rainy season", "snippet": "June can be humid and rainy"}],
        )

    async def search_safety(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "safety",
            [{"title": "Solo travel safety", "snippet": "Generally safe, still check late-night transport"}],
        )

    async def search_raw_query(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "raw_query",
            [
                {
                    "title": "MY ONLY FRAGRANCE HAKATA",
                    "snippet": "Generic fragrance shop in Hakata.",
                    "query_variant": request.query,
                },
                {
                    "title": "Nicolai Bergmann Flowers & Design Fukuoka Store",
                    "snippet": "Flower and design store in Iwataya Annex.",
                    "query_variant": request.query,
                },
                {
                    "title": "NOSE SHOP 福岡",
                    "snippet": "Nicolai perfume appears in NOSE SHOP Fukuoka search evidence.",
                    "query_variant": request.query,
                }
            ],
        )

    async def _record(self, name: str, result: list[dict]) -> list[dict]:
        self.calls.append(name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return result


class NoImageSerpApiTravelClient(FakeSerpApiTravelClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"google_maps:{category}",
            [
                {
                    "title": f"{category} no image pick 1",
                    "rating": 4.5,
                    "reviews": 120,
                    "address": "Fukuoka",
                    "latitude": 33.5902,
                    "longitude": 130.4017,
                },
                {
                    "title": f"{category} no image pick 2",
                    "rating": 4.3,
                    "reviews": 80,
                    "address": "Fukuoka",
                    "latitude": 33.5920,
                    "longitude": 130.4050,
                },
                {
                    "title": f"{category} no image pick 3",
                    "rating": 4.1,
                    "reviews": 64,
                    "address": "Fukuoka",
                    "latitude": 33.5880,
                    "longitude": 130.3970,
                },
            ],
        )


class EmptyHotelSerpApiTravelClient(FakeSerpApiTravelClient):
    async def search_hotels(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record("google_hotels", [])


class MixedQualityLocalSerpApiTravelClient(FakeSerpApiTravelClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"google_maps:{category}",
            [
                {
                    "title": "THE 15 BEST Things to Do in Fukuoka",
                    "link": "https://example.com/listicle",
                },
                {
                    "title": "Momochihama Beach",
                    "address": "2 Chome-4-4 Momochihama",
                    "latitude": 33.594997,
                    "longitude": 130.35313,
                    "rating": 4.5,
                },
            ],
        )


class RatingReviewSerpApiTravelClient(FakeSerpApiTravelClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"google_maps:{category}",
            [
                {
                    "title": "Lower Rated Mega Review Spot",
                    "address": "Fukuoka",
                    "latitude": 33.58,
                    "longitude": 130.40,
                    "rating": 4.3,
                    "reviews": 9000,
                },
                {
                    "title": "Top Rated Popular Spot",
                    "address": "Fukuoka",
                    "latitude": 33.59,
                    "longitude": 130.41,
                    "rating": 4.8,
                    "reviews": 1800,
                },
                {
                    "title": "Top Rated Quiet Spot",
                    "address": "Fukuoka",
                    "latitude": 33.60,
                    "longitude": 130.42,
                    "rating": 4.8,
                    "reviews": 120,
                },
            ],
        )


class SpecificDishSerpApiTravelClient(FakeSerpApiTravelClient):
    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"google_maps:{category}",
            [
                {
                    "title": "Generic High Rated Izakaya",
                    "snippet": "Yakitori and drinks, no fugu menu evidence.",
                    "type": "Izakaya",
                    "rating": 4.9,
                    "reviews": 900,
                    "address": "Tenjin, Fukuoka",
                    "latitude": 33.5901,
                    "longitude": 130.4011,
                },
                {
                    "title": "博多 ふぐ料理 玄品",
                    "snippet": "福岡でとらふぐ、てっさ、ふぐ鍋を提供するふぐ料理店。",
                    "type": "ふぐ料理",
                    "rating": 4.4,
                    "reviews": 240,
                    "address": "Hakata, Fukuoka",
                    "latitude": 33.5895,
                    "longitude": 130.4201,
                    "place_id": "ChIJFuguGenpin",
                    "query_variant": category,
                },
                {
                    "title": "Hakata Seafood Kappo",
                    "snippet": "Seasonal sashimi and seafood course restaurant.",
                    "type": "Seafood",
                    "rating": 4.7,
                    "reviews": 510,
                    "address": "Nakasu, Fukuoka",
                    "latitude": 33.5911,
                    "longitude": 130.4072,
                },
            ],
        )

    async def search_raw_query(self, request: TravelPlanRequest) -> list[dict]:
        return await self._record(
            "raw_query",
            [
                {
                    "title": "博多 ふぐ料理 玄品",
                    "snippet": "ふぐ刺し、ふぐ鍋、とらふぐコースあり。福岡のふぐ料理店。",
                    "type": "ふぐ料理",
                    "rating": 4.4,
                    "reviews": 240,
                    "address": "Hakata, Fukuoka",
                    "latitude": 33.5895,
                    "longitude": 130.4201,
                    "place_id": "ChIJFuguGenpin",
                    "query_variant": "福岡 ふぐ料理",
                },
                {
                    "title": "Popular Ramen Shop",
                    "snippet": "Tonkotsu ramen near Hakata Station.",
                    "type": "Ramen",
                    "rating": 4.8,
                    "reviews": 1200,
                    "address": "Hakata, Fukuoka",
                    "latitude": 33.5904,
                    "longitude": 130.421,
                    "query_variant": request.query,
                },
            ],
        )


class GenericEntitySerpApiTravelClient(FakeSerpApiTravelClient):
    async def search_query_variants(self, request: TravelPlanRequest, queries: list[str]) -> list[dict]:
        self.calls.extend([f"query_variant:{query}" for query in queries])
        return [
            {
                "title": "博多うなぎ屋 山笠",
                "snippet": "福岡で鰻重、蒲焼き、うなぎ料理を提供する専門店。",
                "type": "うなぎ料理",
                "rating": 4.4,
                "reviews": 180,
                "address": "Hakata, Fukuoka",
                "latitude": 33.589,
                "longitude": 130.418,
                "query_variant": queries[0],
            },
            {
                "title": "Popular Tonkotsu Ramen",
                "snippet": "Tonkotsu ramen near Hakata Station.",
                "type": "Ramen",
                "rating": 4.9,
                "reviews": 3200,
                "address": "Hakata, Fukuoka",
                "latitude": 33.590,
                "longitude": 130.419,
                "query_variant": request.query,
            },
        ]

    async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
        return await self._record(
            f"google_maps:{category}",
            [
                {
                    "title": "Generic High Rated Ramen",
                    "snippet": "Popular ramen, no unagi menu evidence.",
                    "type": "Ramen",
                    "rating": 4.9,
                    "reviews": 2000,
                    "address": "Tenjin, Fukuoka",
                    "latitude": 33.591,
                    "longitude": 130.400,
                },
                {
                    "title": "柳川屋 博多店",
                    "snippet": "うなぎせいろ蒸し、鰻重を提供。",
                    "type": "うなぎ料理",
                    "rating": 4.3,
                    "reviews": 410,
                    "address": "Hakata, Fukuoka",
                    "latitude": 33.588,
                    "longitude": 130.421,
                    "query_variant": category,
                },
            ],
        )


class FakeGooglePlacesClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def resolve_place(
        self,
        *,
        request: TravelPlanRequest,
        title: str,
        address: str,
        lat: float | None,
        lng: float | None,
    ) -> dict | None:
        self.calls.append(
            {
                "city": request.city,
                "title": title,
                "address": address,
                "lat": lat,
                "lng": lng,
            }
        )
        if title == "food restaurants local specialties pick 1":
            return {
                "place_id": "ChIJGoogleFoodPick1",
                "title": title,
                "address": "Google verified Fukuoka address",
                "lat": 33.5904,
                "lng": 130.402,
                "rating": 4.7,
                "review_count": 980,
                "google_maps_uri": "https://maps.google.com/?cid=food-pick-1",
                "image_urls": [
                    "https://lh3.googleusercontent.com/food-pick-1-photo",
                    "https://lh3.googleusercontent.com/food-pick-1-photo-2",
                ],
                "photo_attributions": ["Google Place Photographer"],
            }
        return None


class QuotaGooglePlacesClient(FakeGooglePlacesClient):
    async def resolve_place(
        self,
        *,
        request: TravelPlanRequest,
        title: str,
        address: str,
        lat: float | None,
        lng: float | None,
    ) -> dict | None:
        self.calls.append({"title": title})
        req = httpx.Request("POST", "https://places.googleapis.com/v1/places:searchText")
        res = httpx.Response(
            429,
            text="Quota exceeded for quota metric 'SearchTextRequest'",
            request=req,
        )
        raise httpx.HTTPStatusError("quota exceeded", request=req, response=res)


def _fake_flatten_items(value):
    if isinstance(value, list):
        items = []
        for item in value:
            items.extend(_fake_flatten_items(item))
        return items
    if isinstance(value, dict):
        if "title" in value or "name" in value:
            return [value]
        items = []
        for item in value.values():
            items.extend(_fake_flatten_items(item))
        return items
    return []


def _fake_agent_role_for_capability(capability, intent):
    if capability == "flights":
        return "flight"
    if capability == "hotels":
        return "hotel"
    if capability in {"places", "maps", "activities", "food"}:
        return "activity_food"
    if capability in {"routes", "budget", "transport"} or intent.get("answer_mode") in {"itinerary", "route_map"}:
        return "itinerary"
    return "destination"


class FakeAgentClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.formats: list[dict] = []
        self.summaries: list[dict] = []

    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
        if agent_name == "candidate_verifier":
            return {
                "verdicts": [
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "is_relevant": True,
                        "relevance_score": 80,
                        "matched_requirements": [],
                        "missing_requirements": [],
                        "match_reason": "适合当前问题，可结合评分、位置和来源继续比较。",
                    }
                    for candidate in payload.get("candidates", [])
                ]
            }
        if agent_name == "narrative_composer":
            cards = payload.get("display_cards") or []
            card_names = "、".join(str(card.get("title") or "") for card in cards[:3] if card.get("title"))
            focus = payload.get("intent_summary") or "我按你的问题筛选了更合适的选择"
            if card_names:
                return {
                    "narrative_answer": f"{focus}。建议先看 {card_names}，再根据位置、评分和预算做取舍。",
                    "decision_notes": ["价格、营业时间和库存类信息仍需以跳转后的来源为准。"],
                }
            return {
                "narrative_answer": f"{focus}。当前回答会根据已收集到的结构化信息给出简短判断。",
                "decision_notes": ["补充日期、预算或同行人会让建议更精确。"],
            }
        if agent_name == "critic":
            return {
                "summary": "多 Agent 已检查航班、酒店、活动和时间冲突。",
                "not_recommended": [
                    {
                        "title": "太宰府 + 别府同日下午",
                        "reason": "抵达后时间不足，交通与游玩质量冲突。",
                    }
                ],
                "warnings": ["如果没有出发地，航班价格只能作为候选。"],
            }
        if agent_name == "query_understanding":
            request = payload.get("request", {})
            query = str(request.get("query") or "")
            requested_categories = request.get("requested_categories") or []
            interest_tags = request.get("interest_tags") or []
            if "酒店" in query or "住宿" in query:
                return {
                    "task_type": "hotel_search",
                    "answer_mode": "place_cards",
                    "requires_place": True,
                    "destination": request.get("city") or "Fukuoka",
                    "category": "住宿",
                    "target_type": "hotel",
                    "need_supplier_types": ["hotels", "maps", "knowledge"],
                    "requested_outputs": ["hotel_offers", "narrative"],
                    "confidence": 0.9,
                }
            if "航班" in query or "机票" in query or "飞" in query:
                return {
                    "task_type": "flight_search",
                    "answer_mode": "place_cards",
                    "requires_place": True,
                    "destination": request.get("city") or "Fukuoka",
                    "category": "交通",
                    "target_type": "flight",
                    "need_supplier_types": ["flights"],
                    "requested_outputs": ["flight_offers", "narrative"],
                    "confidence": 0.9,
                }
            if "怎么走" in query or "怎么去" in query:
                return {
                    "task_type": "route_planning",
                    "answer_mode": "route_map",
                    "requires_place": True,
                    "destination": request.get("city") or "Kyoto",
                    "category": "交通",
                    "target_type": "route",
                    "need_supplier_types": ["routes", "maps", "transport", "knowledge"],
                    "requested_outputs": ["route_options", "map", "narrative"],
                    "confidence": 0.9,
                }
            if "是什么" in query or "为什么" in query:
                return {
                    "task_type": "answer_question",
                    "answer_mode": "answer_only",
                    "requires_place": False,
                    "destination": "",
                    "target_entity": "河豚",
                    "target_type": "knowledge",
                    "need_supplier_types": ["knowledge"],
                    "requested_outputs": ["narrative"],
                    "confidence": 0.9,
                }
            if "香水" in query or "Nicolai" in query:
                return {
                    "task_type": "place_search",
                    "answer_mode": "place_cards",
                    "requires_place": True,
                    "destination": request.get("city") or "Fukuoka",
                    "category": "购物",
                    "target_entity": "Nicolai 香水" if "Nicolai" in query else "香水",
                    "target_type": "store",
                    "need_supplier_types": ["places", "maps", "knowledge"],
                    "requested_outputs": ["place_cards", "map", "narrative"],
                    "confidence": 0.9,
                }
            category = requested_categories[0] if requested_categories else "美食"
            if not requested_categories and any(tag in {"好玩", "本地体验"} for tag in interest_tags):
                category = "本地体验"
            if "好玩" in query or "玩什么" in query:
                category = "本地体验"
            if "好吃" in query or "吃" in query:
                category = "美食"
            itinerary = "自由行" in query or "三天" in query or "两晚" in query or "2天" in query
            include_inventory = "从东京出发" in query or "含机票" in query or "含机票酒店" in query
            capabilities = (
                ["places", "routes", "maps", "activities", "budget", "transport", "knowledge"]
                if itinerary
                else ["places", "maps", "knowledge"]
            )
            if include_inventory:
                capabilities = [*capabilities, "flights", "hotels"]
            return {
                "task_type": "itinerary_planning" if itinerary else "place_recommendation",
                "answer_mode": "itinerary" if itinerary else "place_cards",
                "requires_place": True,
                "destination": request.get("city") or "Fukuoka",
                "category": category,
                "target_entity": "",
                "target_type": "place",
                "need_supplier_types": capabilities,
                "requested_outputs": ["itinerary", "place_cards", "map", "narrative"],
                "confidence": 0.88,
            }
        if agent_name == "search_planner":
            request = payload.get("request", {})
            query = str(request.get("query") or request.get("question") or "Fukuoka travel")
            intent = payload.get("intent", {})
            target_entity = str(intent.get("target_entity") or "").strip()
            return {
                "should_search": True,
                "tools": ["serper_search"] if intent.get("answer_mode") == "answer_only" else ["serper_places", "serper_search"],
                "query_variants": [query, f"{request.get('city') or 'Fukuoka'} travel"],
                "locale": "auto",
                "must_satisfy": ["Nicolai"] if "Nicolai" in target_entity else ([target_entity] if target_entity else []),
                "exclude_types": [],
            }
        if agent_name == "trip_plan_drafter":
            intent = payload.get("intent", {})
            capabilities = intent.get("need_supplier_types") or intent.get("capability_plan", {}).get("required_capabilities") or ["knowledge"]
            tasks = [
                {
                    "task_id": f"{capability}_task",
                    "capability": capability,
                    "purpose": f"处理 {capability} 相关任务",
                    "agent_role": _fake_agent_role_for_capability(capability, intent),
                    "required": capability not in {"knowledge"},
                }
                for capability in capabilities
            ]
            if intent.get("answer_mode") in {"itinerary", "route_map"}:
                tasks.insert(
                    0,
                    {
                        "task_id": "destination_context",
                        "capability": "knowledge",
                        "purpose": "判断目的地、季节和整体旅行方向",
                        "agent_role": "destination",
                        "required": True,
                    },
                )
            return {
                "intent_summary": "按模型能力任务图规划 travel 回答。",
                "answer_strategy": "只执行用户问题需要的 capability，不扩展到未请求的机酒或行程。",
                "required_capabilities": capabilities,
                "skipped_capabilities": ["flights", "hotels"] if "flights" not in capabilities and "hotels" not in capabilities else [],
                "tasks": tasks,
                "followup_slots": ["日期", "预算"],
                "confidence": 0.85,
            }
        if agent_name == "candidate_verifier":
            return {
                "verdicts": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "is_relevant": True,
                        "relevance_score": 80,
                        "matched_requirements": [],
                        "missing_requirements": [],
                        "match_reason": "模型确认候选可进入下一步分析。",
                    }
                    for candidate in payload.get("candidates", [])
                ]
            }
        if agent_name == "narrative_composer":
            cards = payload.get("display_cards") or []
            card_names = "、".join(str(card.get("title") or "") for card in cards[:3] if card.get("title"))
            focus = payload.get("intent_summary") or "我按你的问题筛选了更合适的选择"
            return {
                "narrative_answer": (
                    f"{focus}。建议先看 {card_names}，再根据位置、评分和预算做取舍。"
                    if card_names
                    else f"{focus}。当前回答会根据已收集到的结构化信息给出简短判断。"
                ),
                "decision_notes": [],
            }
        api_items = _fake_flatten_items(payload.get("api_results"))
        normalized_items = [
            {
                "title": str(item.get("title") or item.get("name") or f"{agent_name} recommendation"),
                "reason": str(item.get("snippet") or item.get("description") or item.get("reason") or "API-backed"),
            }
            for item in api_items[:5]
        ]
        return {
            "summary": f"{agent_name} completed",
            "items": normalized_items or [{"title": f"{agent_name} recommendation", "reason": "API-backed"}],
        }

    async def format_markdown(self, *, model: str, payload: dict) -> str:
        self.formats.append({"model": model, "payload": payload})
        return (
            "## 总建议\n"
            "适合去，但要注意预算和交通。\n\n"
            "### 正面\n- 美食集中\n\n"
            "### 反面\n- 别府当天往返会累"
        )

    async def summarize_workflow(self, *, model: str, payload: dict) -> dict:
        self.summaries.append({"model": model, "payload": payload})
        return {
            "tool_summary": "调用了 10 个 Serper 工具，含原始查询、本地 POI、预算和交通。",
            "sources_used": ["serper:raw_query", "serper:local:美食"],
            "candidate_counts": {
                "tool_count": 10,
                "total_items": payload["candidate_counts"]["total_items"],
                "agent_count": 5,
            },
            "agent_findings": ["Destination/Itinerary/Activity-Food 已完成分工分析。"],
            "critic_notes": ["别府同日下午可能过赶。"],
            "confidence": "medium",
            "missing_but_non_blocking": ["日期和出发地会让价格更准。"],
        }


class StructuredIntentAgentClient(FakeAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
        query = payload.get("request", {}).get("query", "")
        if agent_name == "query_understanding" and "是什么" in query:
            return {
                "task_type": "answer_question",
                "answer_mode": "answer_only",
                "requires_place": False,
                "destination": "",
                "category": "",
                "target_entity": "河豚",
                "target_type": "knowledge",
                "constraints": [],
                "avoid": [],
                "confidence": 0.92,
                "clarifying_question": "",
            }
        if agent_name == "query_understanding" and "评价" in query:
            return {
                "task_type": "place_evaluation",
                "answer_mode": "answer_only",
                "requires_place": False,
                "destination": "Fukuoka",
                "category": "",
                "target_entity": "海滨公园",
                "target_type": "knowledge",
                "requested_outputs": ["narrative"],
                "need_supplier_types": ["knowledge"],
                "should_not_answer": ["generic_recommendations"],
                "constraints": [],
                "avoid": [],
                "confidence": 0.9,
                "clarifying_question": "",
            }
        if agent_name == "query_understanding":
            return {
                "task_type": "place_recommendation",
                "answer_mode": "place_cards",
                "requires_place": True,
                "destination": "Fukuoka",
                "category": "美食",
                "target_entity": "うなぎ",
                "target_type": "restaurant",
                "constraints": ["吃鳗鱼"],
                "avoid": [],
                "confidence": 0.91,
                "clarifying_question": "",
            }
        if agent_name == "search_planner":
            intent = payload.get("intent", {})
            if intent.get("answer_mode") == "answer_only":
                return {
                    "should_search": True,
                    "tools": ["serper_search", "exa_search"],
                    "query_variants": ["河豚 危险 原因", "fugu poison safety"],
                    "locale": "auto",
                    "must_satisfy": ["河豚"],
                    "exclude_types": ["restaurant", "hotel", "flight"],
                }
            return {
                "should_search": True,
                "tools": ["serper_places", "serper_search"],
                "query_variants": ["福岡 うなぎ料理", "Fukuoka unagi restaurant"],
                "locale": "ja-JP",
                "must_satisfy": ["うなぎ", "鰻", "unagi"],
                "exclude_types": ["ramen"],
            }
        if agent_name == "candidate_verifier":
            verdicts = []
            for candidate in payload.get("candidates", []):
                text = " ".join(
                    str(candidate.get(key) or "")
                    for key in ["title", "snippet", "type", "query_variant"]
                ).lower()
                matched = [term for term in ["うなぎ", "鰻", "unagi"] if term.lower() in text]
                verdicts.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "is_relevant": bool(matched),
                        "relevance_score": 94 if matched else 12,
                        "matched_requirements": matched,
                        "missing_requirements": [] if matched else ["うなぎ"],
                        "match_reason": "鳗鱼/うなぎ料理相关候选" if matched else "没有命中用户要吃的鳗鱼",
                    }
                )
            return {"verdicts": verdicts}
        if agent_name == "narrative_composer":
            cards = payload.get("display_cards") or []
            first_title = str(cards[0].get("title") or "博多 ふぐ料理 玄品") if cards else "博多 ふぐ料理 玄品"
            return {
                "narrative_answer": f"我会把重点放在福冈的河豚料理店，先看 {first_title}，不扩展到机酒或完整行程。",
                "decision_notes": ["未查询到实时座位和营业时间，出发前仍建议点进地图核对。"],
            }
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


class FuguStructuredIntentAgentClient(StructuredIntentAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
        if agent_name == "query_understanding":
            return {
                "task_type": "place_recommendation",
                "answer_mode": "place_cards",
                "requires_place": True,
                "destination": "Fukuoka",
                "category": "美食",
                "target_entity": "河豚料理",
                "target_type": "restaurant",
                "constraints": ["吃河豚"],
                "avoid": [],
                "confidence": 0.91,
                "clarifying_question": "",
            }
        if agent_name == "search_planner":
            return {
                "should_search": True,
                "tools": ["serper_places", "serper_search"],
                "query_variants": ["福岡 ふぐ料理", "Fukuoka fugu restaurant"],
                "locale": "ja-JP",
                "must_satisfy": ["ふぐ", "河豚", "fugu"],
                "exclude_types": ["ramen"],
            }
        if agent_name == "candidate_verifier":
            verdicts = []
            for candidate in payload.get("candidates", []):
                text = " ".join(
                    str(candidate.get(key) or "")
                    for key in ["title", "snippet", "type"]
                ).lower()
                matched = [term for term in ["ふぐ", "河豚", "fugu"] if term.lower() in text]
                verdicts.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "is_relevant": bool(matched),
                        "relevance_score": 94 if matched else 10,
                        "matched_requirements": matched,
                        "missing_requirements": [] if matched else ["ふぐ"],
                        "match_reason": "河豚/ふぐ料理相关候选" if matched else "没有命中河豚料理",
                    }
                )
            return {"verdicts": verdicts}
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


class EnglishFoodCategoryAgentClient(FuguStructuredIntentAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        result = await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )
        if agent_name == "query_understanding":
            result["category"] = "restaurant"
            result["target_entity"] = "河豚餐厅"
        return result


class ProductWorkflowAgentClient(FuguStructuredIntentAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        if agent_name == "query_understanding":
            self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
            return {
                "task_type": "place_search",
                "answer_mode": "place_cards",
                "requires_place": True,
                "destination": "Fukuoka",
                "domain": "travel",
                "trip_stage": "in_trip",
                "category": "美食",
                "target_entity": "河豚料理",
                "target_type": "restaurant",
                "requested_outputs": ["place_cards", "map", "narrative"],
                "need_supplier_types": ["places", "maps", "knowledge"],
                "must_answer": ["福冈哪里能吃到河豚料理"],
                "should_not_answer": ["hotels", "flights", "完整行程"],
                "constraints": ["吃河豚"],
                "avoid": [],
                "confidence": 0.94,
                "clarifying_question": "",
            }
        if agent_name == "trip_plan_drafter":
            self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
            return {
                "intent_summary": "用户要在福冈找河豚餐厅，只需要地点推荐、地图和简短解释。",
                "answer_strategy": "先筛河豚相关餐厅，再按相关性、评分、位置生成推荐卡。",
                "required_capabilities": ["places", "maps", "knowledge"],
                "skipped_capabilities": ["flights", "hotels", "payments"],
                "tasks": [
                    {
                        "task_id": "search_fugu_places",
                        "capability": "places",
                        "purpose": "查找福冈河豚料理餐厅候选",
                        "required": True,
                    },
                    {
                        "task_id": "map_candidates",
                        "capability": "maps",
                        "purpose": "为候选生成地图坐标和外跳链接",
                        "required": True,
                    },
                    {
                        "task_id": "context_check",
                        "capability": "knowledge",
                        "purpose": "补充河豚料理背景和需要核对项",
                        "required": False,
                    },
                ],
                "followup_slots": ["预算", "用餐日期", "同行人是否能接受河豚料理"],
                "confidence": 0.9,
            }
        if agent_name == "narrative_composer":
            self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
            return {
                "narrative_answer": (
                    "我会把重点放在福冈的河豚料理店，而不是泛泛推荐拉面或购物。"
                    "目前最值得优先看的是博多 ふぐ料理 玄品：候选信息里直接出现ふぐ/河豚，"
                    "也有评分、地址和地图坐标，适合先放进路线里比较。"
                ),
                "decision_notes": ["未查询到实时座位和营业时间，出发前仍建议点进地图核对。"],
            }
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


class CapabilityPlanAgentClient(FakeAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
        request = payload.get("request", {})
        query = str(request.get("query") or "")
        if agent_name == "query_understanding":
            return {
                "task_type": "place_recommendation",
                "answer_mode": "place_cards",
                "requires_place": True,
                "domain": "travel",
                "trip_stage": "in_trip",
                "traveler_stage": "on_trip_assistance",
                "destination": "Fukuoka",
                "category": "美食",
                "target_entity": "河豚料理",
                "target_type": "restaurant",
                "requested_outputs": ["place_cards", "map", "narrative"],
                "need_supplier_types": ["places", "maps", "food", "knowledge"],
                "must_answer": [query],
                "should_not_answer": ["hotels", "flights", "完整行程"],
                "confidence": 0.94,
                "capability_plan": {
                    "user_goal": "在福冈寻找河豚料理餐厅",
                    "intent_kind": "poi_food_search",
                    "required_capabilities": ["places", "maps", "food", "knowledge"],
                    "tool_tasks": [
                        {
                            "task_id": "find_fugu_places",
                            "capability": "places",
                            "query": "福岡 ふぐ料理",
                            "required": True,
                        },
                        {
                            "task_id": "map_fugu_places",
                            "capability": "maps",
                            "query": "福冈河豚料理地图",
                            "required": True,
                        },
                    ],
                    "agent_tasks": [
                        {
                            "task_id": "food_specialist",
                            "agent_role": "activity_food",
                            "objective": "分析河豚餐厅候选是否符合用户问题",
                            "input_keys": ["raw_query", "local:美食"],
                            "required": True,
                        }
                    ],
                    "answer_contract": {
                        "needs_map": True,
                        "needs_cards": True,
                        "needs_itinerary": False,
                        "needs_inventory": False,
                        "response_style": "place_recommendation",
                    },
                },
            }
        if agent_name == "search_planner":
            return {
                "should_search": True,
                "tools": ["serper_places", "serper_search"],
                "query_variants": ["福岡 ふぐ料理", "Fukuoka fugu restaurant"],
                "locale": "ja-JP",
                "must_satisfy": ["ふぐ", "河豚", "fugu"],
                "exclude_types": ["ramen"],
            }
        if agent_name == "trip_plan_drafter":
            return {
                "intent_summary": "用户要在福冈寻找河豚料理餐厅。",
                "answer_strategy": "使用 capability plan 中的 places/maps/food/knowledge 任务生成地点卡和地图。",
                "required_capabilities": ["places", "maps", "food", "knowledge"],
                "skipped_capabilities": ["hotels", "flights", "itinerary"],
                "tasks": payload["intent"]["capability_plan"]["agent_tasks"],
                "followup_slots": ["用餐日期", "预算"],
                "confidence": 0.9,
            }
        if agent_name == "candidate_verifier":
            return {
                "verdicts": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "is_relevant": True,
                        "relevance_score": 92,
                        "matched_requirements": ["ふぐ"],
                        "missing_requirements": [],
                        "match_reason": "候选命中河豚料理语义目标。",
                    }
                    for candidate in payload.get("candidates", [])
                ]
            }
        if agent_name == "narrative_composer":
            return {
                "narrative_answer": "我会只围绕福冈河豚料理给地点和地图建议，不扩展到机酒或完整行程。",
                "decision_notes": ["实时座位和营业时间仍需出发前确认。"],
            }
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


class MatchingReasonAgentClient(FakeAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
        if agent_name == "activity_food":
            return {
                "summary": "按用户问题筛选本地体验。",
                "items": [
                    {
                        "title": "Top Rated Popular Spot",
                        "reason": "适合你的“好玩”需求：评分高、评论量足，路线安排上比纯购物点更稳。",
                    }
                ],
            }
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


class RankedCardReasonAgentClient(FakeAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        self.calls.append({"agent_name": agent_name, "model": model, "payload": payload})
        if agent_name == "card_reasoner":
            cards = payload["ranked_cards"]
            return {
                "summary": "已按排序后的推荐卡生成理由。",
                "items": [
                    {
                        "title": cards[0]["title"],
                        "reason": "排名后理由：它最符合你问的“好玩”，评分和评论量都靠前，适合作为优先选择。",
                    },
                    {
                        "title": cards[1]["title"],
                        "reason": "排名后理由：同样高分，但评论量较少，更适合想避开过热景点的人。",
                    },
                ],
            }
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


class TimeoutFormatterAgentClient(FakeAgentClient):
    async def format_markdown(self, *, model: str, payload: dict) -> str:
        self.formats.append({"model": model, "payload": payload})
        if model == "travel-formatter":
            raise TimeoutError("formatter timeout")
        return "## 总建议\n不应调用第二个 formatter 模型。"


class FailingSummarizerAgentClient(FakeAgentClient):
    async def summarize_workflow(self, *, model: str, payload: dict) -> dict:
        self.summaries.append({"model": model, "payload": payload})
        raise TimeoutError("summarizer timeout")


class HallucinatingFormatterAgentClient(FakeAgentClient):
    async def format_markdown(self, *, model: str, payload: dict) -> str:
        self.formats.append({"model": model, "payload": payload})
        return (
            "## 核心购买推荐\n"
            "- Nicolai Bergmann Flowers & Design 福冈店：岩田屋新馆 B2F，官方专柜。\n"
            "- 岩田屋本店：可在百货香水专区咨询。"
        )


class BudgetRiskAgentClient(FakeAgentClient):
    async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
        if agent_name == "critic":
            request = payload["request"]
            if "含机票酒店" in request.get("query", ""):
                return {
                    "summary": "预算包含机酒时需要明显收窄。",
                    "warnings": ["预算严重不匹配风险：1000人民币包含机票酒店明显不足。"],
                    "not_recommended": [
                        {
                            "title": "基于1000人民币含机酒的完整行程",
                            "reason": "预算包含机票酒店时不可行。",
                        }
                    ],
                }
            return {
                "summary": "按当地消费预算给出低成本选择。",
                "warnings": [
                    "缺少出发地，航班只能作为候选。",
                    "缺少日期，酒店价格需要之后确认。",
                    "预算单位未定义，价格敏感型建议需要按用户语言默认。",
                    "出发地缺失，航班推荐仅供参考。",
                    "季节性信息缺失，补充日期后会更准确。",
                    "严禁在用户未明确币种时，在不同 Agent 之间使用不同的货币假设进行逻辑推演。",
                    "Flight 和 Hotel Agent 在处理“只推荐美食”这类强目的性需求时，应仅提供辅助信息。",
                ],
                "not_recommended": [
                    {
                        "title": "基于假设的完整行程方案",
                        "reason": "未确认出发地和日期。",
                    },
                    {
                        "title": "高消费餐饮/购物建议",
                        "reason": "当用户设定了极低预算时应避免超预算项目。",
                    }
                ],
            }
        return await super().run_agent(
            agent_name=agent_name,
            model=model,
            prompt=prompt,
            payload=payload,
        )


def test_agent_model_router_prioritizes_quality_non_domestic_models_by_default():
    router = AgentModelRouter.deepinfra_defaults()

    assert router.router == TRAVEL_SEMANTIC_MODEL
    assert router.planner == TRAVEL_FAST_MODEL
    assert router.destination == TRAVEL_REASONING_MODEL
    assert router.hotel == TRAVEL_REASONING_MODEL
    assert router.activity_food == TRAVEL_REASONING_MODEL
    assert router.flight == TRAVEL_REASONING_MODEL
    assert router.itinerary == TRAVEL_REASONING_MODEL
    assert router.summarizer == TRAVEL_REASONING_MODEL
    assert router.formatter == TRAVEL_REASONING_MODEL
    assert router.critic == TRAVEL_CRITIC_MODEL
    assert router.reasoning_effort == TRAVEL_REASONING_EFFORT


@pytest.mark.asyncio
async def test_travel_agent_client_sends_reasoning_effort_only_for_reasoning_stages():
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"summary":"ok","items":[]}'}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = LiteLLMTravelAgentClient(
            api_key="test-token",
            base_url="https://deepinfra.test/v1/openai",
            http_client=http_client,
            reasoning_effort=TRAVEL_REASONING_EFFORT,
        )
        await client.run_agent(
            agent_name="trip_plan_drafter",
            model=TRAVEL_REASONING_MODEL,
            prompt="draft",
            payload={},
        )
        await client.run_agent(
            agent_name="activity_food",
            model=TRAVEL_FAST_MODEL,
            prompt="simple",
            payload={},
        )

    assert captured[0]["reasoning_effort"] == TRAVEL_REASONING_EFFORT
    assert "reasoning_effort" not in captured[1]


@pytest.mark.asyncio
async def test_travel_agent_client_sends_query_understanding_schema_for_router():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"task_type":"travel_question","answer_mode":"answer_only",'
                                '"requires_place":false,"needs_geo":false,'
                                '"capability_plan":{"required_capabilities":["knowledge"],'
                                '"answer_contract":{"needs_map":false,"needs_cards":false}}}'
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = LiteLLMTravelAgentClient(
            api_key="test-token",
            base_url="https://deepinfra.test/v1/openai",
            http_client=http_client,
            reasoning_effort=TRAVEL_REASONING_EFFORT,
        )
        await client.run_agent(
            agent_name="query_understanding",
            model=TRAVEL_SEMANTIC_MODEL,
            prompt="parse",
            payload={"request": {"query": "河豚是什么，为什么危险？"}},
        )

    user_payload = json.loads(captured["payload"]["messages"][1]["content"])
    schema = user_payload["required_schema"]
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "capability_plan" in schema
    assert "answer_mode" in schema
    assert "summary" not in schema
    assert "query_understanding" in captured["payload"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_travel_agent_client_gives_candidate_verifier_larger_json_budget():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"verdicts":[]}'}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = LiteLLMTravelAgentClient(
            api_key="test-token",
            base_url="https://deepinfra.test/v1/openai",
            http_client=http_client,
            reasoning_effort=TRAVEL_REASONING_EFFORT,
        )
        await client.run_agent(
            agent_name="candidate_verifier",
            model=TRAVEL_REASONING_MODEL,
            prompt="verify",
            payload={"candidates": [{"candidate_id": f"c{i}"} for i in range(12)]},
        )

    assert captured["payload"]["max_tokens"] >= 7000
    assert captured["payload"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_travel_agent_client_gives_quality_specialists_larger_json_budget():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"summary":"ok","items":[]}'}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = LiteLLMTravelAgentClient(
            api_key="test-token",
            base_url="https://deepinfra.test/v1/openai",
            http_client=http_client,
            reasoning_effort=TRAVEL_REASONING_EFFORT,
        )
        await client.run_agent(
            agent_name="activity_food",
            model=TRAVEL_REASONING_MODEL,
            prompt="recommend places",
            payload={"api_results": [{"title": f"place {i}"} for i in range(10)]},
        )

    assert captured["payload"]["max_tokens"] >= 5000
    assert captured["payload"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_supervisor_runs_specialized_agents_with_serpapi_inputs_concurrently():
    serpapi = FakeSerpApiTravelClient()
    agent_client = FakeAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="我从东京出发，三天两晚，预算中等，想吃饭和安排别府",
            date_range=["2026-06-10", "2026-06-12"],
            allow_web_search=True,
        )
    )

    assert serpapi.max_active >= 2
    assert "google_flights" in serpapi.calls
    assert "google_hotels" in serpapi.calls
    assert "raw_query" in serpapi.calls
    assert "budget" in serpapi.calls
    assert "transport" in serpapi.calls
    assert any(call.startswith("google_maps:") for call in serpapi.calls)
    assert {call["agent_name"] for call in agent_client.calls} >= {
        "destination",
        "flight",
        "hotel",
        "itinerary",
        "activity_food",
        "critic",
    }
    assert {call["model"] for call in agent_client.calls}.issubset(
        {
            TRAVEL_SEMANTIC_MODEL,
            TRAVEL_FAST_MODEL,
            TRAVEL_REASONING_MODEL,
            TRAVEL_CRITIC_MODEL,
        }
    )
    activity_call = next(call for call in agent_client.calls if call["agent_name"] == "activity_food")
    assert activity_call["model"] == TRAVEL_REASONING_MODEL
    assert response.llm_used is True
    assert response.reasoning_mode == "pydantic_ai_supervisor+parallel_agents"
    assert response.suggestion_source == "serpapi"
    assert response.search_used is True
    assert len(response.category_groups) == 6
    assert all(3 <= len(group.items) <= 5 for group in response.category_groups)
    assert response.not_recommended
    assert any("时间不足" in item.caution for item in response.not_recommended)
    assert "Flight" in response.raw_provider_refs["agent_results"]
    assert response.budget_summary["items"][0]["title"] == "Fukuoka daily budget"
    assert response.transport_summary["items"][0]["title"] == "Fukuoka subway and train"
    assert response.formatted_markdown.startswith("## 总建议")
    assert response.formatter_model_used == TRAVEL_REASONING_MODEL
    assert agent_client.summaries[0]["model"] == TRAVEL_FAST_MODEL
    assert agent_client.formats[0]["payload"]["workflow_summary"]["candidate_counts"]["agent_count"] == 5
    assert agent_client.formats[0]["payload"]["critic"]["not_recommended"]
    assert response.workflow_summary["candidate_counts"]["tool_count"] >= 1
    assert response.workflow_summary["candidate_counts"]["agent_count"] == 5
    assert response.workflow_summary["confidence"] == "medium"
    assert "chain-of-thought" not in str(response.workflow_summary).lower()
    agent_refs = response.raw_provider_refs["agent_results"]
    assert agent_refs["Itinerary"]["raw_api_count"] > 0
    assert agent_refs["Activity/Food"]["raw_api_count"] > 0
    phases = [step.phase for step in response.agentic_workflow]
    assert phases == ["plan", "act", "observe", "analyze", "critique", "summarize", "finalize"]
    assert response.agentic_workflow[1].tools
    assert response.agentic_workflow[2].observation["total_items"] > 0
    assert response.agentic_workflow[3].observation["agent_count"] == 5
    assert response.agentic_workflow[5].actor == "Summarizer"
    assert response.agentic_workflow[-1].actor == "Formatter"
    graph = response.raw_provider_refs["langgraph_compatible_workflow"]
    assert graph["runtime"] == "lightweight_react"
    assert "summarize_trace" in graph["nodes"]
    assert ["collect_tools", "observe_results"] in graph["edges"]
    assert ["critic_review", "summarize_trace"] in graph["edges"]
    assert ["summarize_trace", "final_formatter"] in graph["edges"]


@pytest.mark.asyncio
async def test_hotel_query_returns_typed_hotel_offers_without_generic_poi_cards():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈酒店推荐",
            date_range=["2026-06-10", "2026-06-12"],
            allow_web_search=True,
        )
    )

    assert "google_hotels" in serpapi.calls
    assert response.hotel_offers
    assert response.hotel_offers[0].title == "Hotel Okura Fukuoka"
    assert response.hotel_offers[0].price == "$140"
    assert response.display_cards == []
    assert response.raw_provider_refs["typed_offers"]["hotel_count"] == 1


@pytest.mark.asyncio
async def test_flight_query_returns_typed_flight_offers_without_map_cards():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            origin_city="Tokyo",
            query="从东京飞福冈，帮我选航班",
            date_range=["2026-06-10", "2026-06-12"],
            allow_web_search=True,
        )
    )

    assert "google_flights" in serpapi.calls
    assert response.flight_offers
    assert response.flight_offers[0].title == "HND -> FUK"
    assert response.flight_offers[0].price == "$180"
    assert response.display_cards == []
    assert response.map_view["status"] in {"answer_only", "needs_coordinates"}
    assert response.raw_provider_refs["typed_offers"]["flight_count"] == 1


@pytest.mark.asyncio
async def test_workflow_summary_failure_raises_without_deterministic_fallback():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=FailingSummarizerAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    with pytest.raises(TravelModelCallError, match="workflow_summarizer"):
        await supervisor.plan(
            TravelPlanRequest(city="Fukuoka", query="福冈三天两晚", allow_web_search=True)
        )


@pytest.mark.asyncio
async def test_supervisor_scopes_requested_category_and_keeps_minor_gaps_out_of_cons():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=BudgetRiskAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="预算1000，只推荐美食",
            budget="1000",
            requested_categories=["美食"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["美食"]
    assert 3 <= len(response.category_groups[0].items) <= 5
    assert {item.place.category for item in response.recommendations} == {"美食"}
    assert response.not_recommended == []
    assert not any("缺少出发地" in item for item in response.cons)
    assert not any("缺少日期" in item for item in response.cons)
    assert not any("预算单位" in item for item in response.cons)
    assert not any("出发地缺失" in item for item in response.cons)
    assert not any("季节性信息缺失" in item for item in response.cons)
    assert not any("货币假设" in item for item in response.cons)
    assert not any("Flight 和 Hotel" in item for item in response.cons)
    assert any("出发地" in item for item in response.optional_followups)
    assert any("日期" in item for item in response.optional_followups)
    assert any("预算单位" in item for item in response.optional_followups)
    assert response.budget_summary["assumption"]["scope"] == "local_spend_only"
    assert response.budget_summary["assumption"]["currency"] == "CNY"


@pytest.mark.asyncio
async def test_direct_food_query_builds_trip_board_and_skips_broad_travel_tools():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好吃的？",
            requested_categories=["美食"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["美食"]
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert "google_travel_explore" not in serpapi.calls
    assert "google_maps:food restaurants local specialties" in serpapi.calls
    assert response.display_cards
    first_card = response.display_cards[0]
    assert first_card.title == "food restaurants local specialties pick 1"
    assert first_card.subcategory == "本地特色"
    assert first_card.trip_state == "none"
    assert first_card.google_maps_uri.startswith("https://www.google.com/maps/search/")
    assert first_card.directions_uri.startswith("https://www.google.com/maps/dir/")
    assert first_card.place_id == "ChIJFoodPick1"
    assert first_card.photo_attributions == ["Example Photographer"]
    assert first_card.image_url == "https://example.com/pick-1-large.jpg"
    assert first_card.image_urls[:3] == [
        "https://example.com/pick-1-large.jpg",
        "https://example.com/pick-1-gallery-2.jpg",
        "https://example.com/pick-1-gallery-3-thumb.jpg",
    ]
    assert "https://example.com/pick-1-thumb.jpg" not in first_card.image_urls[:3]
    assert first_card.rating == 4.5
    assert first_card.lat == 33.5902
    assert first_card.lng == 130.4017
    assert response.resolved_intent["category"] == "美食"
    assert response.resolved_intent["subcategory"] == "local_specialties"
    assert response.map_view["pins"][0]["title"] == first_card.title
    assert response.map_view["pins"][0]["trip_state"] == "none"
    assert response.map_view["pins"][0]["place_id"] == "ChIJFoodPick1"
    assert response.map_view["provider"] == "photo_agent_map"
    assert response.map_view["mode"] == "dedicated_panel"


@pytest.mark.asyncio
async def test_strict_image_policy_uses_place_specific_image_search_only():
    serpapi = NoImageSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FuguStructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的？",
            requested_categories=["本地体验"],
            interest_tags=["好玩"],
            allow_web_search=True,
        )
    )

    image_calls = [call for call in serpapi.calls if call.startswith("images:")]
    assert image_calls
    assert response.display_cards[:3]
    first_card = response.display_cards[0]
    second_card = response.display_cards[1]
    first_image_call_index = next(index for index, call in enumerate(serpapi.calls) if first_card.title in call)
    first_raw_query_image_index = next(
        index for index, call in enumerate(serpapi.calls) if call.startswith("images:MY ONLY FRAGRANCE")
    )
    assert first_image_call_index < first_raw_query_image_index
    assert any(first_card.title in call for call in image_calls)
    assert any(second_card.title in call for call in image_calls)
    assert not any(call == "images:Fukuoka things to do attractions activities experiences" for call in image_calls)
    assert first_card.image_status == "source_item"
    assert len(first_card.image_urls) >= 2
    title_slug = first_card.title.replace(" ", "-")
    assert all(title_slug in url for url in first_card.image_urls[:2])


@pytest.mark.asyncio
async def test_google_places_enrichment_sets_place_identity_photos_and_map_pins():
    google_places = FakeGooglePlacesClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        google_places_client=google_places,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好吃的？",
            requested_categories=["美食"],
            allow_web_search=True,
        )
    )

    assert google_places.calls
    first_card = response.display_cards[0]
    assert first_card.place_id == "ChIJGoogleFoodPick1"
    assert first_card.address == "Google verified Fukuoka address"
    assert first_card.lat == 33.5904
    assert first_card.lng == 130.402
    assert first_card.rating == 4.7
    assert first_card.review_count == 980
    assert first_card.image_status == "place_photo"
    assert first_card.image_urls == [
        "https://lh3.googleusercontent.com/food-pick-1-photo",
        "https://lh3.googleusercontent.com/food-pick-1-photo-2",
    ]
    assert first_card.photo_attributions == ["Google Place Photographer"]
    assert first_card.google_maps_uri == "https://maps.google.com/?cid=food-pick-1"
    assert response.map_view["pins"][0]["place_id"] == "ChIJGoogleFoodPick1"


@pytest.mark.asyncio
async def test_japanese_food_query_uses_japanese_food_scope_only():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好吃的日料？",
            requested_categories=["美食"],
            interest_tags=["日料"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["美食"]
    assert "google_maps:japanese food restaurants sushi kaiseki izakaya tempura" in serpapi.calls
    assert "google_maps:food restaurants local specialties" not in serpapi.calls
    assert "google_flights" not in serpapi.calls
    assert response.resolved_intent["subcategory"] == "japanese_cuisine"
    assert {card.subcategory for card in response.display_cards} == {"日料"}


@pytest.mark.asyncio
async def test_specific_dish_query_uses_exact_entity_scope_and_filters_unmatched_places():
    serpapi = SpecificDishSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FuguStructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈去哪吃河豚？",
            requested_categories=["美食"],
            interest_tags=["河豚"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["美食"]
    assert response.resolved_intent["subcategory"] == "specific_dish"
    assert response.resolved_intent["strictness"] == "semantic_match"
    assert response.resolved_intent["target_entity"] == "河豚料理"
    assert response.resolved_intent["entity_terms"] == ["ふぐ", "河豚", "fugu"]
    assert any("fugu" in call.lower() or "ふぐ" in call or "河豚" in call for call in serpapi.calls)
    assert any("福岡 ふぐ料理" in query for query in response.search_queries)
    assert response.display_cards
    assert response.display_cards[0].title == "博多 ふぐ料理 玄品"
    assert response.display_cards[0].subcategory == "河豚料理"
    assert response.display_cards[0].match_score > 0
    assert "ふぐ" in response.display_cards[0].matched_terms
    assert "河豚" in response.display_cards[0].match_reason
    assert response.display_cards[0].display_reason
    assert "命中用户核心目标" not in response.display_cards[0].display_reason
    assert "没有命中" not in response.display_cards[0].display_reason
    assert "API候选" not in response.display_cards[0].display_reason
    assert "需要用户确认" not in response.display_cards[0].display_reason
    assert all("Ramen" not in card.title for card in response.display_cards[:3])


@pytest.mark.asyncio
async def test_food_poi_router_accepts_english_restaurant_category_from_model():
    serpapi = SpecificDishSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=EnglishFoodCategoryAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    assert response.resolved_intent["category"] == "美食"
    assert any("google_maps:" in call for call in serpapi.calls)
    assert response.display_cards
    assert response.display_cards[0].title == "博多 ふぐ料理 玄品"
    assert response.map_view["status"] == "ready"


def test_supervisor_does_not_cache_empty_place_card_response():
    empty_place_response = TravelPlanResponse(
        summary="没有可用地点卡。",
        needs_user_confirmation=False,
        answer_mode="place_cards",
        resolved_intent={"answer_mode": "place_cards"},
    )
    answer_response = TravelPlanResponse(
        summary="河豚危险是因为河豚毒素。",
        needs_user_confirmation=False,
        answer_mode="answer_only",
        resolved_intent={"answer_mode": "answer_only"},
    )
    useful_place_response = TravelPlanResponse(
        summary="推荐 Bote。",
        needs_user_confirmation=False,
        answer_mode="place_cards",
        resolved_intent={"answer_mode": "place_cards"},
        display_cards=[
            TravelDisplayCard(
                id="card-1",
                title="Bote",
                category="美食",
                lat=33.59,
                lng=130.4,
            )
        ],
    )

    assert not _should_cache_travel_response(empty_place_response)
    assert _should_cache_travel_response(answer_response)
    assert _should_cache_travel_response(useful_place_response)


@pytest.mark.asyncio
async def test_product_workflow_builds_plan_draft_decision_cards_and_narrative():
    serpapi = SpecificDishSerpApiTravelClient()
    agent_client = ProductWorkflowAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈去哪吃河豚？",
            allow_web_search=True,
        )
    )

    assert response.resolved_intent["domain"] == "travel"
    assert response.resolved_intent["trip_stage"] == "in_trip"
    assert response.resolved_intent["need_supplier_types"] == ["places", "maps", "knowledge"]
    assert "flights" in response.resolved_intent["should_not_answer"]
    assert response.intent_summary == "用户要在福冈找河豚餐厅，只需要地点推荐、地图和简短解释。"
    assert response.plan_draft["required_capabilities"] == ["places", "maps", "knowledge"]
    assert "flights" in response.plan_draft["skipped_capabilities"]
    assert [task["capability"] for task in response.plan_draft["tasks"]] == [
        "places",
        "maps",
        "knowledge",
    ]
    assert response.raw_provider_refs["api_bus"]["required_capabilities"] == [
        "places",
        "maps",
        "knowledge",
    ]
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert response.decision_cards
    assert response.decision_cards[0].title == "博多 ふぐ料理 玄品"
    assert response.decision_cards[0].supplier_capability == "places"
    assert "河豚" in response.narrative_answer
    assert "营业时间" not in response.narrative_answer
    assert response.followup_slots == ["预算", "用餐日期", "同行人是否能接受河豚料理"]
    assert any(call["agent_name"] == "trip_plan_drafter" for call in agent_client.calls)
    assert any(call["agent_name"] == "narrative_composer" for call in agent_client.calls)


@pytest.mark.asyncio
async def test_semantic_router_flags_answer_only_and_skips_map_agents():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=GenericEntitySerpApiTravelClient(),
        agent_client=StructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="", query="河豚是什么，为什么危险？", allow_web_search=True)
    )

    router = response.resolved_intent
    assert router["traveler_stage"] == "inspiration"
    assert router["needs_geo"] is False
    assert router["needs_knowledge"] is True
    assert router["needs_explanation"] is True
    assert router["needs_realtime_inventory"] is False
    assert router["needs_transaction"] is False
    assert router["delivery_strategy"] == "single_agent"
    assert response.raw_provider_refs["langgraph_orchestrator"]["run_mode"] == "bypass"
    assert response.raw_provider_refs["langgraph_orchestrator"]["max_parallel_agents"] == 1
    assert response.map_view["status"] == "answer_only"


@pytest.mark.asyncio
async def test_query_understanding_uses_dedicated_travel_router_model():
    agent_client = StructuredIntentAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=GenericEntitySerpApiTravelClient(),
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    await supervisor.plan(
        TravelPlanRequest(city="", query="河豚是什么，为什么危险？", allow_web_search=True)
    )

    query_call = next(call for call in agent_client.calls if call["agent_name"] == "query_understanding")
    search_call = next(call for call in agent_client.calls if call["agent_name"] == "search_planner")
    draft_call = next(call for call in agent_client.calls if call["agent_name"] == "trip_plan_drafter")
    assert query_call["model"] == TRAVEL_SEMANTIC_MODEL
    assert search_call["model"] == TRAVEL_FAST_MODEL
    assert draft_call["model"] == TRAVEL_REASONING_MODEL


@pytest.mark.asyncio
async def test_router_capability_plan_drives_tool_and_agent_contracts():
    agent_client = CapabilityPlanAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=SpecificDishSerpApiTravelClient(),
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    capability_plan = response.capability_plan
    assert capability_plan["intent_kind"] == "poi_food_search"
    assert capability_plan["required_capabilities"] == ["places", "maps", "food", "knowledge"]
    assert capability_plan["answer_contract"]["needs_map"] is True
    assert capability_plan["answer_contract"]["needs_inventory"] is False
    assert response.resolved_intent["capability_plan"]["tool_tasks"][0]["task_id"] == "find_fugu_places"
    assert response.raw_provider_refs["capability_plan"]["agent_tasks"][0]["agent_role"] == "activity_food"
    assert response.plan_draft["tasks"][0]["agent_role"] == "activity_food"
    called_agents = {call["agent_name"] for call in agent_client.calls}
    assert "activity_food" in called_agents
    assert "hotel" not in called_agents
    assert "flight" not in called_agents


@pytest.mark.asyncio
async def test_router_without_model_client_fails_strictly_instead_of_regex_fallback():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=None,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    with pytest.raises(TravelModelCallError, match="query_understanding"):
        await supervisor.plan(
            TravelPlanRequest(
                city="Fukuoka",
                query="福冈的海滨公园评价怎样?",
                allow_web_search=False,
            )
        )


@pytest.mark.asyncio
async def test_place_evaluation_query_does_not_become_generic_nature_recommendations():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=StructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈的海滨公园评价怎样?",
            allow_web_search=False,
        )
    )

    assert response.resolved_intent["task_type"] == "place_evaluation"
    assert response.resolved_intent["answer_mode"] == "answer_only"
    assert response.resolved_intent["requires_place"] is False
    assert response.resolved_intent["needs_geo"] is False
    assert response.resolved_intent["should_not_answer"] == ["generic_recommendations"]
    assert response.plan_draft["required_capabilities"] == ["knowledge"]
    assert response.display_cards == []
    assert response.map_view["status"] == "answer_only"
    assert "自然与摄影推荐" not in response.narrative_answer


@pytest.mark.asyncio
async def test_semantic_router_fanout_for_itinerary_without_forcing_flight_or_hotel():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈2天自由行，预算1000",
            budget="1000",
            allow_web_search=True,
        )
    )

    router = response.resolved_intent
    assert router["traveler_stage"] == "build_itinerary"
    assert router["needs_geo"] is True
    assert router["needs_realtime_inventory"] is False
    assert router["delivery_strategy"] == "fanout"
    assert response.plan_draft["required_capabilities"] == [
        "places",
        "routes",
        "maps",
        "activities",
        "budget",
        "transport",
        "knowledge",
    ]
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert "budget" in serpapi.calls
    assert "transport" in serpapi.calls
    orchestrator = response.raw_provider_refs["langgraph_orchestrator"]
    assert orchestrator["run_mode"] == "embedded_graph"
    assert orchestrator["max_parallel_agents"] == 4
    assert orchestrator["global_active_run_limit"] == 2
    assert orchestrator["degrade_when_busy"] is False


@pytest.mark.asyncio
async def test_itinerary_graph_uses_real_langgraph_and_skips_unrequested_inventory_agents():
    serpapi = FakeSerpApiTravelClient()
    agent_client = FakeAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈2天自由行，预算1000",
            budget="1000",
            allow_web_search=True,
        )
    )

    orchestrator = response.raw_provider_refs["langgraph_orchestrator"]
    assert orchestrator["runtime"] == "langgraph_stategraph"
    assert orchestrator["actual_graph_run"] is True
    assert orchestrator["graph_nodes"] == [
        "route",
        "plan_tasks",
        "collect_tools",
        "validate_candidates",
        "run_agents",
        "compose_decision",
        "narrative",
        "render_contract",
    ]
    called_agents = {call["agent_name"] for call in agent_client.calls}
    assert "flight" not in called_agents
    assert "hotel" not in called_agents
    assert {"itinerary", "activity_food", "critic"}.issubset(called_agents)
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert response.itinerary_plan["days"]
    assert len(response.itinerary_plan["days"]) == 2
    assert all(day["time_blocks"] for day in response.itinerary_plan["days"])
    assert response.itinerary_plan["days"][0]["time_blocks"][0]["place_ids"]
    assert "第1天" in response.narrative_answer
    assert response.raw_provider_refs["agent_results"].get("Flight") is None
    assert response.raw_provider_refs["agent_results"].get("Hotel") is None


@pytest.mark.asyncio
async def test_place_card_graph_path_skips_inventory_and_itinerary_contract():
    serpapi = SpecificDishSerpApiTravelClient()
    agent_client = FuguStructuredIntentAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
    )

    called_agents = {call["agent_name"] for call in agent_client.calls}
    assert "flight" not in called_agents
    assert "hotel" not in called_agents
    assert "itinerary" not in called_agents
    assert "activity_food" in called_agents
    assert response.itinerary_plan["days"] == []
    assert response.raw_provider_refs["langgraph_orchestrator"]["runtime"] == "langgraph_stategraph"
    assert response.raw_provider_refs["langgraph_orchestrator"]["route"] == "place_cards"


@pytest.mark.asyncio
async def test_route_question_uses_route_map_transport_without_inventory_agents():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Kyoto", query="东京到京都怎么走？", allow_web_search=True)
    )

    router = response.resolved_intent
    assert router["task_type"] == "route_planning"
    assert router["answer_mode"] == "route_map"
    assert router["needs_geo"] is True
    assert response.raw_provider_refs["langgraph_orchestrator"]["route"] == "route_map"
    assert "transport" in serpapi.calls
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls


@pytest.mark.asyncio
async def test_graph_node_failure_raises_without_partial_response_fallback():
    class ExplodingAgentSupervisor(TravelRecommendationSupervisor):
        async def _run_agents(self, request, api_payloads, *, intent, plan_draft):
            raise RuntimeError("agent node exploded")

    supervisor = ExplodingAgentSupervisor(
        serpapi_client=SpecificDishSerpApiTravelClient(),
        agent_client=FuguStructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    with pytest.raises(RuntimeError, match="agent node exploded"):
        await supervisor.plan(
            TravelPlanRequest(city="Fukuoka", query="福冈去哪吃河豚？", allow_web_search=True)
        )


@pytest.mark.asyncio
async def test_hotel_query_routes_to_hotel_placeholder_without_fake_places():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈酒店推荐", allow_web_search=True)
    )

    router = response.resolved_intent
    assert router["category"] == "住宿"
    assert router["needs_realtime_inventory"] is True
    assert router["delivery_strategy"] == "single_agent"
    assert response.plan_draft["required_capabilities"] == ["hotels", "maps", "knowledge"]
    assert "hotel" in response.raw_provider_refs["api_bus"]["providers_used"]
    assert response.hotel_offers
    assert response.hotel_offers[0].data_gaps == ["缺少入住/退房日期，价格和可订状态只能作为参考。"]
    assert response.display_cards == []
    assert "google_flights" not in serpapi.calls
    assert not any(call.startswith("google_maps:") for call in serpapi.calls)


@pytest.mark.asyncio
async def test_hotel_query_surfaces_supplier_placeholder_as_typed_offer_when_inventory_empty():
    serpapi = EmptyHotelSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈酒店推荐", allow_web_search=True)
    )

    assert "google_hotels" in serpapi.calls
    assert response.display_cards == []
    assert response.hotel_offers
    assert response.hotel_offers[0].title == "酒店供应商未接入"
    assert any("缺少可结构化酒店库存" in gap for gap in response.hotel_offers[0].data_gaps)


@pytest.mark.asyncio
async def test_narrative_fallback_uses_plan_and_cards_when_model_returns_generic_text():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=SpecificDishSerpApiTravelClient(),
        agent_client=FuguStructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈去哪吃河豚？",
            allow_web_search=True,
        )
    )

    assert "多 Agent 推荐" not in response.narrative_answer
    assert "narrative_composer completed" not in response.narrative_answer
    assert "河豚" in response.narrative_answer
    assert response.display_cards[0].title in response.narrative_answer


@pytest.mark.asyncio
async def test_answer_only_query_does_not_require_destination_or_map_cards():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=GenericEntitySerpApiTravelClient(),
        agent_client=StructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="",
            query="河豚是什么，为什么危险？",
            allow_web_search=True,
        )
    )

    assert response.resolved_intent["answer_mode"] == "answer_only"
    assert response.resolved_intent["requires_place"] is False
    assert response.raw_provider_refs["search_plan"]["tools"] == ["serper_search", "exa_search"]
    assert response.display_cards == []
    assert response.map_view.get("pins", []) == []
    assert "需要先知道目的地" not in response.summary


@pytest.mark.asyncio
async def test_answer_only_product_workflow_uses_knowledge_capability_without_map_tasks():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=GenericEntitySerpApiTravelClient(),
        agent_client=StructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="",
            query="河豚是什么，为什么危险？",
            allow_web_search=True,
        )
    )

    assert response.plan_draft["required_capabilities"] == ["knowledge"]
    assert response.plan_draft["tasks"][0]["capability"] == "knowledge"
    assert response.decision_cards == []
    assert response.intent_summary
    assert response.narrative_answer
    assert response.raw_provider_refs["api_bus"]["required_capabilities"] == ["knowledge"]
    assert response.answer_mode == "answer_only"


@pytest.mark.asyncio
async def test_generic_structured_entity_query_filters_by_verifier_not_wordlist():
    serpapi = GenericEntitySerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=StructuredIntentAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈去哪吃鳗鱼？",
            allow_web_search=True,
        )
    )

    assert response.resolved_intent["answer_mode"] == "place_cards"
    assert response.resolved_intent["target_entity"] == "うなぎ"
    assert response.raw_provider_refs["search_plan"]["query_variants"] == [
        "福岡 うなぎ料理",
        "Fukuoka unagi restaurant",
    ]
    assert any(call == "query_variant:福岡 うなぎ料理" for call in serpapi.calls)
    assert response.display_cards
    assert response.display_cards[0].title in {"博多うなぎ屋 山笠", "柳川屋 博多店"}
    assert response.display_cards[0].match_score >= 90
    assert "鳗鱼" in response.display_cards[0].match_reason or "うなぎ" in response.display_cards[0].match_reason
    assert all("Ramen" not in card.title for card in response.display_cards[:3])


@pytest.mark.asyncio
async def test_fragrance_shopping_query_uses_store_scope_and_skips_itinerary_tools():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈买香水",
            requested_categories=["购物"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["购物"]
    assert any(
        call.startswith("google_maps:") and ("香水" in call or "fragrance" in call)
        for call in serpapi.calls
    )
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert response.resolved_intent["category"] == "购物"
    assert response.resolved_intent["subcategory"] == "fragrance"
    assert {card.subcategory for card in response.display_cards} == {"香水"}


@pytest.mark.asyncio
async def test_things_to_do_query_uses_activity_scope_and_skips_food():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的？",
            requested_categories=["本地体验"],
            interest_tags=["好玩"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["本地体验"]
    assert "google_maps:things to do attractions activities experiences" in serpapi.calls
    assert not any(call.startswith("google_maps:food") for call in serpapi.calls)
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert response.resolved_intent["category"] == "本地体验"
    assert response.resolved_intent["subcategory"] == "things_to_do"
    assert {card.category for card in response.display_cards} == {"本地体验"}
    assert {card.subcategory for card in response.display_cards} == {"景点活动"}


@pytest.mark.asyncio
async def test_onsen_query_uses_hot_spring_scope_and_skips_food():
    serpapi = FakeSerpApiTravelClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=serpapi,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Beppu",
            query="别府哪里泡温泉比较好？",
            requested_categories=["本地体验"],
            interest_tags=["温泉"],
            allow_web_search=True,
        )
    )

    assert [group.title for group in response.category_groups] == ["本地体验"]
    assert "google_maps:onsen hot springs public bath rotenburo" in serpapi.calls
    assert not any(call.startswith("google_maps:food") for call in serpapi.calls)
    assert "google_flights" not in serpapi.calls
    assert "google_hotels" not in serpapi.calls
    assert response.resolved_intent["category"] == "本地体验"
    assert response.resolved_intent["subcategory"] == "hot_spring"
    assert {card.category for card in response.display_cards} == {"本地体验"}
    assert {card.subcategory for card in response.display_cards} == {"温泉"}


@pytest.mark.asyncio
async def test_supervisor_only_uses_strong_budget_warning_when_budget_includes_flight_and_hotel():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=BudgetRiskAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="预算1000人民币含机票酒店，去福冈",
            budget="1000人民币",
            allow_web_search=True,
        )
    )

    assert response.not_recommended
    assert any("预算包含机票酒店" in item.caution for item in response.not_recommended)
    assert any("预算严重不匹配" in item for item in response.cons)


@pytest.mark.asyncio
async def test_formatter_failure_raises_without_model_fallback():
    agent_client = TimeoutFormatterAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=agent_client,
        model_router=AgentModelRouter(
            destination="travel-fast",
            flight="travel-reasoning",
            hotel="travel-fast",
            itinerary="travel-reasoning",
            activity_food="travel-fast",
            critic="travel-critic",
            summarizer="travel-fast",
            formatter="travel-formatter",
        ),
    )

    with pytest.raises(TravelModelCallError, match="formatter"):
        await supervisor.plan(
            TravelPlanRequest(
                city="Fukuoka",
                query="福冈三天两晚，预算和交通都要考虑",
                date_range=["2026-06-10", "2026-06-12"],
                allow_web_search=True,
            )
        )

    assert [call["model"] for call in agent_client.formats] == ["travel-formatter"]


@pytest.mark.asyncio
async def test_formatter_payload_keeps_original_source_material_and_freeform_contract():
    agent_client = FakeAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈自由行，帮我多推荐一些选择", allow_web_search=True)
    )

    payload = agent_client.formats[0]["payload"]
    assert "source_material" in payload
    assert len(payload["source_material"]["local:美食"]) == 3
    assert payload["source_material"]["local:美食"][2]["title"].endswith("pick 3")
    assert "不强制使用固定栏目" in payload["instructions"]
    assert "自由组织旅行建议" in payload["instructions"]
    assert "广告、赞助、推广" in payload["instructions"]
    assert "尽量保留原始候选" in payload["instructions"]
    assert "内部规则" in payload["instructions"]
    assert "提示词" not in payload["instructions"]
    assert "只使用 workflow_summary 与 structured_response" not in payload["instructions"]


@pytest.mark.asyncio
async def test_litellm_formatter_prompt_preserves_sources_and_allows_longer_output():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "## 推荐\n保留原始候选。"}}]},
            request=request,
        )

    client = LiteLLMTravelAgentClient(
        api_key="test",
        base_url="http://litellm.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.format_markdown(
        model="travel-formatter",
        payload={"instructions": "只规定主题，保留原文。", "source_material": {"local:美食": []}},
    )

    llm_payload = captured["payload"]
    assert result.startswith("## 推荐")
    assert llm_payload["max_tokens"] >= 5000
    system_prompt = llm_payload["messages"][0]["content"]
    assert "保留原始候选名称" in system_prompt
    assert "不要过度压缩" in system_prompt
    assert "不强制使用固定栏目" in system_prompt
    assert "三个一级栏目" not in system_prompt


@pytest.mark.asyncio
async def test_supervisor_calls_optional_serper_context_only_when_intent_matches():
    plain_serper = FakeSerpApiTravelClient()
    plain_supervisor = TravelRecommendationSupervisor(
        serpapi_client=plain_serper,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )
    await plain_supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="三天两晚吃饭泡温泉", allow_web_search=True)
    )

    assert "visa" not in plain_serper.calls
    assert "weather" not in plain_serper.calls
    assert "safety" not in plain_serper.calls

    contextual_serper = FakeSerpApiTravelClient()
    contextual_supervisor = TravelRecommendationSupervisor(
        serpapi_client=contextual_serper,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )
    response = await contextual_supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="女生 solo 旅行，担心签证入境、天气和安全保险",
            allow_web_search=True,
        )
    )

    assert "visa" in contextual_serper.calls
    assert "weather" in contextual_serper.calls
    assert "safety" in contextual_serper.calls
    assert set(response.optional_context) == {"visa", "weather", "safety"}


@pytest.mark.asyncio
async def test_supervisor_does_not_invent_realtime_results_without_serpapi():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=None,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="帮我查航班和酒店并给推荐",
            allow_web_search=True,
        )
    )

    assert response.search_used is False
    assert response.suggestion_source == "model_only"
    assert any("SERPER_API_KEY" in gap for gap in response.data_gaps)
    assert any("无法查询实时航班" in note for note in response.uncertainty)
    assert response.recommendations


@pytest.mark.asyncio
async def test_supervisor_raises_critic_http_status_details_without_fallback():
    class FailingCriticClient(FakeAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "critic":
                request = httpx.Request("POST", "http://litellm.test/v1/chat/completions")
                response = httpx.Response(
                    400,
                    json={"error": {"message": f"Invalid model name {model}"}},
                    request=request,
                )
                raise httpx.HTTPStatusError("bad request", request=request, response=response)
            return await super().run_agent(
                agent_name=agent_name,
                model=model,
                prompt=prompt,
                payload=payload,
            )


    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=FailingCriticClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    with pytest.raises(TravelModelCallError, match=f"Invalid model name {TRAVEL_CRITIC_MODEL}"):
        await supervisor.plan(
            TravelPlanRequest(city="Fukuoka", query="三天两晚", allow_web_search=True)
        )


@pytest.mark.asyncio
async def test_supervisor_raises_critic_gateway_error_without_user_facing_fallback():
    class FailingCriticClient(FakeAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "critic":
                request = httpx.Request("POST", "http://litellm.test/v1/chat/completions")
                response = httpx.Response(502, text="Bad gateway", request=request)
                raise httpx.HTTPStatusError("bad gateway", request=request, response=response)
            return await super().run_agent(
                agent_name=agent_name,
                model=model,
                prompt=prompt,
                payload=payload,
            )

    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=FailingCriticClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    with pytest.raises(TravelModelCallError, match="HTTP 502"):
        await supervisor.plan(
            TravelPlanRequest(city="Fukuoka", query="福冈三天两晚", allow_web_search=True)
        )


@pytest.mark.asyncio
async def test_display_cards_prefer_mappable_places_over_generic_web_results():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=MixedQualityLocalSerpApiTravelClient(),
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的?",
            requested_categories=["本地体验"],
            allow_web_search=True,
        )
    )

    assert response.display_cards[0].title == "Momochihama Beach"
    assert response.display_cards[0].lat == 33.594997
    assert response.display_cards[0].lng == 130.35313
    assert response.map_view["pins"][0]["title"] == "Momochihama Beach"


@pytest.mark.asyncio
async def test_google_places_quota_errors_stay_out_of_user_decision_sections():
    google_client = QuotaGooglePlacesClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        google_places_client=google_client,
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的?",
            requested_categories=["本地体验"],
            allow_web_search=True,
        )
    )

    visible_text = "\n".join([*response.data_gaps, *response.cons, response.formatted_markdown])
    assert "Google Places 解析" not in visible_text
    assert "Quota exceeded" not in visible_text
    assert response.map_view["status"] == "ready"
    assert response.map_view["pins"]
    assert response.map_view["pins"][0]["lat"] == response.display_cards[0].lat
    assert response.display_cards[0].source_provider == "places"
    assert any(
        "Google Places 解析" in warning
        and "Serper Places" in warning
        for warning in response.raw_provider_refs.get("model_runtime_warnings", [])
    )


@pytest.mark.asyncio
async def test_google_places_quota_keeps_source_item_images_as_fallback():
    google_client = QuotaGooglePlacesClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
        google_places_client=google_client,
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好吃的？",
            requested_categories=["美食"],
            interest_tags=["美食"],
            allow_web_search=True,
        )
    )

    first_card = response.display_cards[0]
    assert first_card.image_status == "source_item"
    assert first_card.image_urls[:2] == [
        "https://example.com/pick-1-large.jpg",
        "https://example.com/pick-1-gallery-2.jpg",
    ]
    assert not any("wide" in url for url in first_card.image_urls)
    assert google_client.calls


@pytest.mark.asyncio
async def test_serper_api_http_errors_include_status_endpoint_and_message_in_runtime_warnings():
    class ExhaustedSerperClient:
        provider_name = "serper"

        async def search_query_variants(self, request: TravelPlanRequest, queries: list[str]) -> list[dict]:
            http_request = httpx.Request("POST", "https://google.serper.dev/places?apiKey=secret")
            response = httpx.Response(
                400,
                json={"message": "Not enough credits", "statusCode": 400},
                request=http_request,
            )
            raise httpx.HTTPStatusError("bad request", request=http_request, response=response)

        async def search_local(self, request: TravelPlanRequest, category: str) -> list[dict]:
            http_request = httpx.Request("POST", "https://google.serper.dev/places?apiKey=secret")
            response = httpx.Response(
                400,
                json={"message": "Not enough credits", "statusCode": 400},
                request=http_request,
            )
            raise httpx.HTTPStatusError("bad request", request=http_request, response=response)

    supervisor = TravelRecommendationSupervisor(
        serpapi_client=ExhaustedSerperClient(),
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )
    intent = TravelIntent(
        answer_mode="place_cards",
        needs_geo=True,
        category="本地体验",
        capability_plan=TravelCapabilityPlan(required_capabilities=["places"]),
    )
    search_plan = SearchPlan(
        should_search=True,
        tools=["serper_search"],
        query_variants=["福冈有什么好玩的？"],
    )
    plan_draft = TripPlanDraft(
        intent_summary="福冈本地体验",
        required_capabilities=["places"],
    )

    payloads, warnings = await supervisor._collect_api_payloads(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的？",
            requested_categories=["本地体验"],
            allow_web_search=True,
        ),
        intent=intent,
        search_plan=search_plan,
        plan_draft=plan_draft,
    )

    assert payloads["raw_query"] == []
    assert payloads["local:本地体验"] == []
    joined = "\n".join(warnings)
    assert "raw_query API 调用失败：HTTP 400 /places - Not enough credits" in joined
    assert "local:本地体验 API 调用失败：HTTP 400 /places - Not enough credits" in joined
    assert "secret" not in joined


@pytest.mark.asyncio
async def test_display_cards_use_concrete_recommendation_reason_not_api_placeholder():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好吃的？",
            requested_categories=["美食"],
            interest_tags=["美食"],
            allow_web_search=True,
        )
    )

    first_card = response.display_cards[0]
    assert "API 候选" not in first_card.description
    assert "需要用户确认" not in first_card.description
    assert "推荐理由" in first_card.description
    assert "4.5" in first_card.description
    assert "Fukuoka" in first_card.description


@pytest.mark.asyncio
async def test_display_cards_rank_by_rating_then_review_count_after_relevance():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=RatingReviewSerpApiTravelClient(),
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的？",
            requested_categories=["本地体验"],
            interest_tags=["好玩"],
            allow_web_search=True,
        )
    )

    assert [card.title for card in response.display_cards[:3]] == [
        "Top Rated Popular Spot",
        "Top Rated Quiet Spot",
        "Lower Rated Mega Review Spot",
    ]


@pytest.mark.asyncio
async def test_display_cards_use_matching_agent_reason_after_ranked_recommendations():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=RatingReviewSerpApiTravelClient(),
        agent_client=MatchingReasonAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的？",
            requested_categories=["本地体验"],
            interest_tags=["好玩"],
            allow_web_search=True,
        )
    )

    first_card = response.display_cards[0]
    assert first_card.title == "Top Rated Popular Spot"
    assert "适合你的“好玩”需求" in first_card.description
    assert "评分高、评论量足" in first_card.description


@pytest.mark.asyncio
async def test_ranked_display_cards_get_llm_reasons_after_sorting():
    agent_client = RankedCardReasonAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=RatingReviewSerpApiTravelClient(),
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(
            city="Fukuoka",
            query="福冈有什么好玩的？",
            requested_categories=["本地体验"],
            interest_tags=["好玩"],
            allow_web_search=True,
        )
    )

    reasoner_call = next(call for call in agent_client.calls if call["agent_name"] == "card_reasoner")
    ranked_titles = [card["title"] for card in reasoner_call["payload"]["ranked_cards"][:3]]
    assert ranked_titles == [
        "Top Rated Popular Spot",
        "Top Rated Quiet Spot",
        "Lower Rated Mega Review Spot",
    ]
    first_card = response.display_cards[0]
    assert first_card.title == "Top Rated Popular Spot"
    assert "排名后理由" in first_card.reason
    assert "排名后理由" in first_card.display_reason
    assert "评分和评论量都靠前" in first_card.description
    assert response.raw_provider_refs["ranked_card_reasoner"]["status"] == "completed"


@pytest.mark.asyncio
async def test_raw_query_specific_poi_is_promoted_into_matching_category_group():
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=FakeAgentClient(),
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈 Nicolai 香水", allow_web_search=True)
    )

    shopping = next(group for group in response.category_groups if group.title == "购物")
    assert shopping.items[0] == "NOSE SHOP 福岡"
    assert response.raw_provider_refs["query_variants"]
    assert any("Nicolai" in query or "香水" in query for query in response.search_queries)
    assert not any("Nicolai Bergmann" in query for query in response.search_queries)


@pytest.mark.asyncio
async def test_specific_store_query_preserves_source_table_instead_of_model_rewrite():
    agent_client = HallucinatingFormatterAgentClient()
    supervisor = TravelRecommendationSupervisor(
        serpapi_client=FakeSerpApiTravelClient(),
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(),
    )

    response = await supervisor.plan(
        TravelPlanRequest(city="Fukuoka", query="福冈 Nicolai 香水", allow_web_search=True)
    )

    assert "Nicolai Bergmann Flowers & Design 福冈店" not in response.formatted_markdown
    assert "岩田屋新馆 B2F" not in response.formatted_markdown
    assert "| 候选 | 匹配等级 | 类型 | 地址/摘要 | 来源 |" in response.formatted_markdown
    assert "NOSE SHOP 福岡" in response.formatted_markdown
    assert "名称匹配但品类未确认：可能不是香水售卖点" in response.formatted_markdown
    assert "## 查询变体" not in response.formatted_markdown
    candidates = response.raw_provider_refs["source_preserving_candidates"]
    assert candidates[0]["name"] == "NOSE SHOP 福岡"
    assert candidates[0]["match_label"] == "likely_match"
    assert candidates[0]["evidence_type"] == "fragrance_store"
    assert response.raw_provider_refs["grounded_answer_pipeline"]["framework"] == "pydantic"
    assert response.raw_provider_refs["grounded_answer_pipeline"]["components"] == [
        "SerperSearchResultAdapter",
        "CandidateExtractor",
        "CandidateVerifier",
        "GroundedSynthesizer",
    ]
    assert any(
        item["name"] == "Nicolai Bergmann Flowers & Design Fukuoka Store"
        and item["match_label"] == "category_unconfirmed"
        for item in candidates
    )
    assert response.formatter_model_used == "source-preserving-table"
    assert agent_client.formats == []
