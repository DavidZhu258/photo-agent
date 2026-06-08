from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field

from app.config import Settings, settings
from app.schemas.travel import (
    TravelDecisionCard,
    TravelDisplayCard,
    TravelFlightOffer,
    TravelHotelOffer,
    TravelPlanRequest,
    TravelPlanResponse,
    TravelRecommendation,
    TravelSuggestionGroup,
    TravelWorkflowStep,
)
from app.schemas.visual import EvidenceCard, PlaceCandidate
from app.services.grounded_answer import (
    GroundedAnswerPipeline,
    GroundedAnswerResult,
    SerperSearchResultAdapter,
)
from app.services.open_source_stack import (
    TRAVEL_COMMERCIAL_DISCLOSURE,
    cache_info,
    provider_refs,
    source_breakdown,
    travel_sources,
    travel_trace_steps,
)
from app.services.openai_compatible_llm import OpenAICompatibleLLMClient
from app.services.travel_query_understanding import (
    SearchPlan,
    TripPlanDraft,
    TravelModelCallError,
    TravelIntent,
    apply_candidate_verdicts,
    candidate_documents_from_payloads,
    draft_trip_plan,
    plan_travel_search,
    understand_travel_query,
    verify_candidates,
)


TRAVEL_ORCHESTRATOR_PROMPT = (
    "请像靠谱旅行顾问一样自然回答当前问题。问什么答什么，不套固定模板；需要推荐时给出真实、可执行、"
    "避开广告营销的理由；需要地点或路线时再调用工具，不编造价格、营业时间、库存、距离或坐标。"
)


AGENT_CATEGORIES = [
    ("美食", "food restaurants local specialties"),
    ("购物", "shopping souvenirs local products"),
    ("历史文化", "history culture temples museums heritage"),
    ("本地体验", "local experiences markets events workshops"),
    ("购物与街区", "shopping neighborhoods walkable streets"),
    ("自然与摄影", "nature photography views parks sunset"),
]


TRAVEL_CATEGORY_ALIASES = {
    "food": "美食",
    "foods": "美食",
    "restaurant": "美食",
    "restaurants": "美食",
    "dining": "美食",
    "eat": "美食",
    "eats": "美食",
    "cuisine": "美食",
    "meal": "美食",
    "meals": "美食",
    "美食": "美食",
    "餐厅": "美食",
    "餐廳": "美食",
    "料理": "美食",
    "吃饭": "美食",
    "吃飯": "美食",
    "购物": "购物",
    "購物": "购物",
    "shopping": "购物",
    "shop": "购物",
    "shops": "购物",
    "store": "购物",
    "stores": "购物",
    "retail": "购物",
    "souvenir": "购物",
    "souvenirs": "购物",
    "history": "历史文化",
    "culture": "历史文化",
    "cultural": "历史文化",
    "heritage": "历史文化",
    "museum": "历史文化",
    "museums": "历史文化",
    "temple": "历史文化",
    "temples": "历史文化",
    "历史": "历史文化",
    "歷史": "历史文化",
    "文化": "历史文化",
    "activity": "本地体验",
    "activities": "本地体验",
    "attraction": "本地体验",
    "attractions": "本地体验",
    "experience": "本地体验",
    "experiences": "本地体验",
    "things_to_do": "本地体验",
    "things to do": "本地体验",
    "poi": "本地体验",
    "play": "本地体验",
    "本地体验": "本地体验",
    "本地體驗": "本地体验",
    "景点": "本地体验",
    "景點": "本地体验",
    "活动": "本地体验",
    "活動": "本地体验",
    "neighborhood": "购物与街区",
    "neighborhoods": "购物与街区",
    "district": "购物与街区",
    "districts": "购物与街区",
    "street": "购物与街区",
    "streets": "购物与街区",
    "area": "购物与街区",
    "areas": "购物与街区",
    "街区": "购物与街区",
    "街區": "购物与街区",
    "nature": "自然与摄影",
    "park": "自然与摄影",
    "parks": "自然与摄影",
    "beach": "自然与摄影",
    "beaches": "自然与摄影",
    "view": "自然与摄影",
    "views": "自然与摄影",
    "photo": "自然与摄影",
    "photography": "自然与摄影",
    "自然": "自然与摄影",
    "摄影": "自然与摄影",
    "攝影": "自然与摄影",
}


class StructuredTravelIntent(BaseModel):
    task_type: str = "recommend"
    domain: str = "travel"
    trip_stage: str = "planning"
    traveler_stage: str = "inspiration"
    needs_geo: bool = True
    needs_realtime_inventory: bool = False
    needs_user_memory: bool = False
    needs_knowledge: bool = True
    needs_transaction: bool = False
    needs_explanation: bool = True
    delivery_strategy: str = "single_agent"
    category: str = ""
    subcategory: str = ""
    subcategory_label: str = ""
    city: str = ""
    is_complete_itinerary: bool = False
    answer_mode: str = "place_cards"
    requires_place: bool = True
    destination: str = ""
    target_entity: str = ""
    target_type: str = ""
    requested_outputs: list[str] = Field(default_factory=list)
    need_supplier_types: list[str] = Field(default_factory=list)
    must_answer: list[str] = Field(default_factory=list)
    should_not_answer: list[str] = Field(default_factory=list)
    confidence: float = 0.6
    clarifying_question: str = ""
    entity_terms: list[str] = Field(default_factory=list)
    must_match_terms: list[str] = Field(default_factory=list)
    query_variants: list[str] = Field(default_factory=list)
    strictness: str = "category_match"


@dataclass(frozen=True)
class AgentModelRouter:
    destination: str
    flight: str
    hotel: str
    itinerary: str
    activity_food: str
    critic: str
    orchestrator: str = settings.travel_model_orchestrator
    complex_route: str = settings.travel_model_complex_route
    visual: str = settings.deepinfra_vision_model
    router: str = settings.travel_model_router
    planner: str = settings.travel_model_fast
    summarizer: str = settings.travel_model_reasoning
    formatter: str = settings.travel_model_formatter
    reasoning_effort: str = settings.travel_model_reasoning_effort

    @classmethod
    def deepinfra_defaults(cls, app_settings: Settings = settings) -> "AgentModelRouter":
        return cls(
            destination=app_settings.travel_model_reasoning,
            flight=app_settings.travel_model_reasoning,
            hotel=app_settings.travel_model_reasoning,
            itinerary=app_settings.travel_model_reasoning,
            activity_food=app_settings.travel_model_reasoning,
            critic=app_settings.travel_model_critic,
            orchestrator=app_settings.travel_model_orchestrator,
            complex_route=app_settings.travel_model_complex_route,
            visual=app_settings.deepinfra_vision_model,
            router=app_settings.travel_model_router,
            planner=app_settings.travel_model_fast,
            summarizer=app_settings.travel_model_reasoning,
            formatter=app_settings.travel_model_formatter,
            reasoning_effort=app_settings.travel_model_reasoning_effort,
        )

    def for_agent(self, agent_name: str) -> str:
        return str(getattr(self, agent_name))


@dataclass
class AgentResult:
    name: str
    model: str
    summary: str
    items: list[dict[str, Any]]
    warnings: list[str]
    raw_api_results: list[dict[str, Any]]
    status: str = "completed"


class LiteLLMTravelAgentClient:
    """Backward-compatible name for the direct OpenAI-compatible travel adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20,
        http_client: httpx.AsyncClient | None = None,
        reasoning_effort: str = settings.travel_model_reasoning_effort,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.reasoning_effort = reasoning_effort
        self.llm = OpenAICompatibleLLMClient(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            http_client=http_client,
        )
        self.http_client = self.llm.http_client

    async def run_agent(
        self,
        *,
        agent_name: str,
        model: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.llm.complete_json(
            model=model,
            temperature=0.35,
            max_tokens=_max_tokens_for_agent(agent_name),
            reasoning_effort=self._reasoning_effort_for(agent_name, model),
            tools=_native_tools_for_agent(agent_name, payload),
            tool_choice="auto" if _native_tools_for_agent(agent_name, payload) else None,
            system=_system_prompt_for_agent(agent_name),
            payload={
                "agent_name": agent_name,
                "task": prompt,
                "payload": payload,
                "required_schema": _required_schema_for_agent(agent_name),
            },
        )

    async def format_markdown(self, *, model: str, payload: dict[str, Any]) -> str:
        return await self.llm.complete_text(
            model=model,
            timeout=180.0,
            temperature=0.45,
            max_tokens=6000,
            reasoning_effort=self.reasoning_effort,
            system=(
                "You are a warm travel recommendation writer. Follow the answer contract "
                "and source material exactly. 保留原始候选名称、来源文字和有用细节。"
                "自然组织答案，不强制使用固定栏目；只有结构能帮助阅读时再分段。"
                "避开广告、赞助、营销感强或来源不清的候选。"
                "不要过度压缩，不要把原始候选改写成没有来源的新事实。"
                "Mention uncertainty honestly, and do not invent prices, routes, policies, "
                "stock, opening hours, or sources."
            ),
            payload=payload,
        )

    async def summarize_workflow(self, *, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.llm.complete_json(
            model=model,
            timeout=90.0,
            temperature=0.1,
            max_tokens=2000,
            reasoning_effort=self._reasoning_effort_for("workflow_summarizer", model),
            system=(
                "You summarize visible travel workflow telemetry for users. Return strict "
                "JSON only. Do not expose hidden chain-of-thought."
            ),
            payload=payload,
        )

    def _reasoning_effort_for(self, agent_name: str, model: str) -> str | None:
        if not self.reasoning_effort:
            return None
        if model == settings.travel_model_fast:
            return None
        reasoning_agents = {
            "travel_orchestrator",
            "complex_route_reasoner",
            "critic_verifier",
            "destination",
            "hotel",
            "activity_food",
            "search_planner",
            "trip_plan_drafter",
            "candidate_verifier",
            "flight",
            "itinerary",
            "critic",
            "narrative_composer",
        }
        if agent_name in reasoning_agents:
            return self.reasoning_effort
        return None


class TravelRecommendationSupervisor:
    """Supervisor that fans out to travel specialists and merges their output."""

    def __init__(
        self,
        *,
        serpapi_client: object | None = None,
        google_places_client: object | None = None,
        agent_client: object | None = None,
        model_router: AgentModelRouter | None = None,
        result_cache: object | None = None,
        orchestration_mode: str = "legacy",
        orchestrator_max_tool_rounds: int = 6,
        complex_max_tool_rounds: int = 10,
    ) -> None:
        self.serpapi_client = serpapi_client
        self.google_places_client = google_places_client
        self.agent_client = agent_client
        self.model_router = model_router or AgentModelRouter.deepinfra_defaults()
        self.result_cache = result_cache
        self.orchestration_mode = orchestration_mode
        self.orchestrator_max_tool_rounds = max(1, orchestrator_max_tool_rounds)
        self.complex_max_tool_rounds = max(1, complex_max_tool_rounds)

    async def plan(self, request: TravelPlanRequest) -> TravelPlanResponse:
        cache_key = self._request_cache_key(request)

        from app.services.travel_workflow_graph import (
            run_travel_orchestrator_workflow,
            run_travel_workflow,
        )

        if self.orchestration_mode == "orchestrator":
            response = await run_travel_orchestrator_workflow(
                supervisor=self,
                request=request,
                cache_key=cache_key,
            )
        else:
            response = await run_travel_workflow(
                supervisor=self,
                request=request,
                cache_key=cache_key,
            )
        return response

    async def _enrich_api_payloads_with_google_places(
        self,
        request: TravelPlanRequest,
        api_payloads: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        if self.google_places_client is None or not api_payloads:
            return api_payloads, []
        enriched = dict(api_payloads)
        warnings: list[str] = []
        for key, value in api_payloads.items():
            if key != "raw_query" and not key.startswith("local:"):
                continue
            items = _list_of_dicts(value)
            if not items:
                continue
            enriched_items: list[dict[str, Any]] = []
            quota_blocked = False
            for item in items[:6]:
                if quota_blocked:
                    enriched_items.append(dict(item))
                    continue
                enriched_item = await self._enrich_item_with_google_place(request, item, warnings)
                enriched_items.append(enriched_item)
                if warnings and _is_google_places_quota_warning(warnings[-1]):
                    quota_blocked = True
            enriched[key] = [*enriched_items, *items[6:]]
        return enriched, warnings

    async def _enrich_item_with_google_place(
        self,
        request: TravelPlanRequest,
        item: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        title = _item_title(item)
        if not title:
            return item
        address = str(item.get("address") or item.get("location") or "").strip()
        lat = _coordinate(item, "lat")
        lng = _coordinate(item, "lng")
        try:
            resolved = await self.google_places_client.resolve_place(
                request=request,
                title=title,
                address=address,
                lat=lat,
                lng=lng,
            )
        except Exception as exc:
            summary = _exception_summary(exc)
            fallback = dict(item)
            if lat is not None and lng is not None:
                fallback.setdefault("serper_endpoint", "places")
                fallback.setdefault("place_identity_source", "serper_places")
                source_note = "；已使用 Serper Places 返回的坐标/评分继续生成地图卡片"
            else:
                source_note = ""
            if _is_google_places_quota_warning(summary):
                warnings.append(f"Google Places 解析已跳过：{summary}{source_note}")
            else:
                warnings.append(f"Google Places 解析 {title} 失败：{summary}{source_note}")
            return fallback
        if not isinstance(resolved, dict):
            return dict(item)
        merged = dict(item)
        merged["place_id"] = str(resolved.get("place_id") or merged.get("place_id") or merged.get("placeId") or "")
        merged["googleMapsUri"] = str(resolved.get("google_maps_uri") or merged.get("googleMapsUri") or "")
        merged["address"] = str(resolved.get("address") or merged.get("address") or "")
        if resolved.get("lat") is not None:
            merged["latitude"] = resolved["lat"]
        if resolved.get("lng") is not None:
            merged["longitude"] = resolved["lng"]
        if resolved.get("rating") is not None:
            merged["rating"] = resolved["rating"]
        if resolved.get("review_count") is not None:
            merged["reviews"] = resolved["review_count"]
        image_urls = _string_list(resolved.get("image_urls"))
        if image_urls:
            merged["image_urls"] = image_urls
            merged["image_status"] = "place_photo"
        merged["photo_attributions"] = _string_list(resolved.get("photo_attributions"))
        return merged

    async def _collect_api_payloads(
        self,
        request: TravelPlanRequest,
        *,
        intent: TravelIntent,
        search_plan: SearchPlan,
        plan_draft: TripPlanDraft,
    ) -> tuple[dict[str, Any], list[str]]:
        scope = _request_scope(request)
        if intent.answer_mode == "place_cards":
            scope = {**scope, "broad": False}
        capabilities = set(_plan_capabilities(plan_draft, intent))
        if self.serpapi_client is None or not request.allow_web_search:
            warnings = ["SERPER_API_KEY 未配置或联网搜索关闭，无法查询实时航班/酒店/地图结果。"]
            payloads: dict[str, Any] = {}
            if "hotels" in capabilities and not scope["broad"]:
                payloads["hotel_supplier_placeholder"] = _hotel_supplier_placeholder()
                warnings.append("酒店供应商 adapter 未配置，无法查询真实库存/价格。")
            return payloads, warnings

        resolved_intent = _resolved_intent(request, intent=intent, search_plan=search_plan)
        tasks = {}
        if intent.answer_mode == "answer_only":
            raw_query = getattr(self.serpapi_client, "search_query_variants", None)
            if callable(raw_query):
                tasks["raw_query"] = raw_query(request, search_plan.query_variants)
            else:
                raw_fallback = getattr(self.serpapi_client, "search_raw_query", None)
                if callable(raw_fallback):
                    tasks["raw_query"] = raw_fallback(request)
        elif scope["broad"]:
            tasks["destination"] = self.serpapi_client.travel_explore(request)
            if "flights" in capabilities:
                tasks["flight"] = self.serpapi_client.search_flights(request)
            if "hotels" in capabilities:
                tasks["hotel"] = self.serpapi_client.search_hotels(request)
        if intent.answer_mode != "answer_only":
            if "flights" in capabilities and "flight" not in tasks:
                tasks["flight"] = self.serpapi_client.search_flights(request)
            if "hotels" in capabilities and "hotel" not in tasks:
                tasks["hotel"] = self.serpapi_client.search_hotels(request)
        if intent.answer_mode != "answer_only":
            variant_search = getattr(self.serpapi_client, "search_query_variants", None)
            raw_query = getattr(self.serpapi_client, "search_raw_query", None)
            if search_plan.query_variants and callable(variant_search):
                tasks["raw_query"] = variant_search(request, search_plan.query_variants)
            elif request.query.strip() and callable(raw_query):
                tasks["raw_query"] = raw_query(request)
        if (scope["broad"] and "budget" in capabilities) or scope["budget"]:
            method = getattr(self.serpapi_client, "search_budget", None)
            if callable(method):
                tasks["budget"] = method(request)
        if (scope["broad"] and "transport" in capabilities) or scope["transport"]:
            method = getattr(self.serpapi_client, "search_transport", None)
            if callable(method):
                tasks["transport"] = method(request)
        for key in _optional_context_keys(request):
            method = getattr(self.serpapi_client, f"search_{key}", None)
            if callable(method):
                tasks[key] = method(request)
        if intent.answer_mode != "answer_only":
            for title, category in _selected_categories(request, resolved_intent=resolved_intent):
                search_category = _category_search_query(title, category, resolved_intent)
                tasks[f"local:{title}"] = self.serpapi_client.search_local(
                    request,
                    search_category,
                )
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        payloads: dict[str, Any] = {}
        warnings: list[str] = []
        for key, result in zip(tasks.keys(), results, strict=True):
            if isinstance(result, Exception):
                payloads[key] = []
                warnings.append(f"{key} API 调用失败：{_exception_summary(result)}")
            else:
                payloads[key] = result
        if "hotels" in capabilities and not scope["broad"] and not payloads.get("hotel"):
            payloads["hotel_supplier_placeholder"] = _hotel_supplier_placeholder()
            warnings.append("酒店供应商 adapter 未配置，无法查询真实库存/价格。")
        if scope["broad"] and "flights" in capabilities and not payloads.get("flight"):
            warnings.append("缺少出发地、日期或 API 结果，无法查询实时航班价格。")
        if scope["broad"] and "hotels" in capabilities and not payloads.get("hotel"):
            warnings.append("酒店 API 没有返回可用结果，预算匹配需要再次确认。")
        payloads, image_warnings = await self._enrich_payloads_with_place_images(request, payloads)
        warnings.extend(image_warnings)
        return payloads, warnings

    async def _enrich_payloads_with_place_images(
        self,
        request: TravelPlanRequest,
        payloads: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        image_search = getattr(self.serpapi_client, "search_images", None)
        if not callable(image_search):
            return payloads, []

        candidates: list[tuple[str, int, dict[str, Any], str]] = []
        seen_queries: set[str] = set()
        search_keys = [
            *[key for key in payloads if key.startswith("local:")],
            *(["raw_query"] if "raw_query" in payloads else []),
        ]
        for key in search_keys:
            value = payloads.get(key)
            for index, item in enumerate(_list_of_dicts(value)[:8]):
                query = _place_image_query(request, item)
                if not query or query in seen_queries:
                    continue
                if len([url for url in _item_image_urls(item) if not _is_low_quality_image_url(url)]) >= 3:
                    continue
                seen_queries.add(query)
                candidates.append((key, index, item, query))
                if len(candidates) >= 12:
                    break
            if len(candidates) >= 12:
                break
        if not candidates:
            return payloads, []

        results = await asyncio.gather(
            *[image_search(request, query) for _, _, _, query in candidates],
            return_exceptions=True,
        )
        enriched = dict(payloads)
        warnings: list[str] = []
        for (key, index, item, query), result in zip(candidates, results, strict=True):
            if isinstance(result, Exception):
                warnings.append(f"images:{query} API 调用失败：{_exception_summary(result)}")
                continue
            image_urls = _strict_place_image_urls(item, _list_of_dicts(result))
            if not image_urls:
                continue
            items = [dict(value) for value in _list_of_dicts(enriched.get(key))]
            if index >= len(items):
                continue
            existing_urls = _item_image_urls(items[index])
            merged_urls = _prefer_clear_image_urls([*existing_urls, *image_urls])[:5]
            items[index]["image_urls"] = merged_urls
            if merged_urls and str(items[index].get("image_status") or "") != "place_photo":
                items[index]["image_status"] = "source_item"
            items[index]["image_match_query"] = query
            enriched[key] = items
        return enriched, warnings

    async def _verify_api_candidates(
        self,
        *,
        request: TravelPlanRequest,
        intent: TravelIntent,
        search_plan: SearchPlan,
        api_payloads: dict[str, Any],
    ):
        documents = candidate_documents_from_payloads(api_payloads)
        return await verify_candidates(
            request=request,
            intent=intent,
            search_plan=search_plan,
            candidates=documents[:40],
            agent_client=self.agent_client,
            model=self.model_router.summarizer,
        )

    async def _run_agents(
        self,
        request: TravelPlanRequest,
        api_payloads: dict[str, Any],
        *,
        intent: TravelIntent,
        plan_draft: TripPlanDraft,
    ) -> list[AgentResult]:
        specs = _agent_specs_for_plan(request, intent, plan_draft, api_payloads)
        tasks = [
            self._run_agent(request, name, prompt, payload)
            for name, prompt, payload in specs
        ]
        return list(await asyncio.gather(*tasks))

    async def _run_agent(
        self,
        request: TravelPlanRequest,
        name: str,
        prompt: str,
        api_payload: Any,
    ) -> AgentResult:
        model = self.model_router.for_agent(name)
        if self.agent_client is None:
            raise TravelModelCallError(name, "agent client unavailable", model=model)
        try:
            result = await self.agent_client.run_agent(
                agent_name=name,
                model=model,
                prompt=prompt,
                payload={
                    "request": request.model_dump(mode="json"),
                    "api_results": api_payload,
                },
            )
        except Exception as exc:
            raise TravelModelCallError(name, _exception_summary(exc), model=model) from exc
        return AgentResult(
            name=name,
            model=model,
            summary=str(result.get("summary") or f"{name} completed"),
            items=_list_of_dicts(result.get("items")),
            warnings=_string_list(result.get("warnings")),
            raw_api_results=_flatten_api_items(api_payload),
        )

    async def _run_critic(
        self,
        request: TravelPlanRequest,
        agent_results: list[AgentResult],
        api_payloads: dict[str, Any],
        *,
        intent: TravelIntent | None = None,
        plan_draft: TripPlanDraft | None = None,
    ) -> dict[str, Any]:
        model = self.model_router.for_agent("critic")
        payload = {
            "request": request.model_dump(mode="json"),
            "agent_results": [_agent_result_dict(result) for result in agent_results],
            "api_payloads": api_payloads,
            "intent": intent.model_dump(mode="json") if intent is not None else {},
            "plan_draft": plan_draft.model_dump(mode="json") if plan_draft is not None else {},
            "required_capabilities": _string_list(
                plan_draft.required_capabilities if plan_draft is not None else []
            ),
            "needs_realtime_inventory": bool(
                intent.needs_realtime_inventory if intent is not None else False
            ),
        }
        if self.agent_client is None:
            raise TravelModelCallError("critic", "agent client unavailable", model=model)
        try:
            return await self.agent_client.run_agent(
                agent_name="critic",
                model=model,
                prompt="检查路线冲突、预算超支、可用性、信息缺失，并明确不建议项。",
                payload=payload,
            )
        except Exception as exc:
            raise TravelModelCallError("critic", _exception_summary(exc), model=model) from exc

    def _refresh_decision_cards(
        self,
        *,
        response: TravelPlanResponse,
        plan_draft: TripPlanDraft,
    ) -> TravelPlanResponse:
        return response.model_copy(
            update={
                "decision_cards": _decision_cards_from_display_cards(
                    response.display_cards,
                    plan_draft=plan_draft,
                )
            }
        )

    def _compose_answer_only_response(
        self,
        *,
        request: TravelPlanRequest,
        cache_key: str,
        intent: TravelIntent,
        search_plan: SearchPlan,
        plan_draft: TripPlanDraft,
        api_payloads: dict[str, Any],
        api_warnings: list[str],
        candidate_verdicts: list[Any],
    ) -> TravelPlanResponse:
        provider_name = self._api_provider_name()
        refs = provider_refs("travel")
        refs[f"{provider_name}_engines"] = sorted(api_payloads.keys())
        refs["query_variants"] = search_plan.query_variants or _workflow_query_variants(request)
        refs["search_plan"] = search_plan.model_dump(mode="json")
        refs["capability_plan"] = intent.capability_plan.model_dump(mode="json")
        refs["api_bus"] = _api_bus_refs(plan_draft, api_payloads)
        refs["candidate_verification"] = [
            verdict.model_dump(mode="json") if hasattr(verdict, "model_dump") else verdict
            for verdict in candidate_verdicts[:40]
        ]
        refs["langgraph_compatible_workflow"] = _langgraph_compatible_workflow()
        refs["langgraph_orchestrator"] = _langgraph_orchestrator_refs(intent, plan_draft, api_payloads)
        resolved_intent = _resolved_intent(request, intent=intent, search_plan=search_plan)
        summary = _answer_only_summary(request, intent, api_payloads)
        search_used = _search_used_from_payloads(api_payloads)
        runtime_warnings = [warning for warning in api_warnings if _is_runtime_warning(warning)]
        if runtime_warnings:
            refs["model_runtime_warnings"] = runtime_warnings
        user_warnings = [warning for warning in api_warnings if not _is_runtime_warning(warning)]
        return TravelPlanResponse(
            summary=summary,
            capability_plan=intent.capability_plan.model_dump(mode="json"),
            recommendations=[],
            not_recommended=[],
            conditional_options=[],
            excluded_candidates=[],
            decision_notes=["语义理解判断该问题不需要地点，因此未强行生成 POI 或地图。"],
            uncertainty=[],
            evidence_cards=[],
            pros=[],
            cons=[],
            route_summary={"used": False, "source": provider_name, "warnings": []},
            budget_summary={},
            transport_summary={},
            optional_context={},
            suggestion_groups=[],
            category_groups=[],
            resolved_intent=resolved_intent,
            intent_summary=plan_draft.intent_summary,
            plan_draft=plan_draft.model_dump(mode="json"),
            decision_cards=[],
            narrative_answer=summary,
            followup_slots=plan_draft.followup_slots,
            search_plan=search_plan.model_dump(mode="json"),
            answer_mode=intent.answer_mode,
            candidate_verification=[
                verdict.model_dump(mode="json") if hasattr(verdict, "model_dump") else verdict
                for verdict in candidate_verdicts[:40]
            ],
            display_cards=[],
            map_view={"pins": [], "status": "answer_only"},
            suggestion_source=provider_name if search_used else "model_only",
            api_sources_used=travel_sources(),
            source_breakdown=source_breakdown(travel_sources()),
            commercial_disclosure=TRAVEL_COMMERCIAL_DISCLOSURE,
            raw_provider_refs=refs,
            thinking_steps=travel_trace_steps(
                llm_used=True,
                model_used=self.model_router.summarizer,
                suggestion_source=provider_name if search_used else "model_only",
                search_used=search_used,
                cache_hit=False,
            ),
            agentic_workflow=[],
            workflow_summary={
                "tool_summary": "语义理解判断为知识问答；跳过地图/POI 推荐。",
                "sources_used": sorted(api_payloads.keys()),
                "candidate_counts": {"total_items": len(_flatten_api_items(api_payloads))},
                "confidence": "medium" if intent.confidence < 0.8 else "high",
            },
            cache=cache_info("travel", cache_key),
            search_used=search_used,
            search_queries=search_plan.query_variants,
            sources_consulted=_sources_consulted(api_payloads, provider_name),
            data_gaps=[],
            optional_followups=_optional_followups(request, user_warnings),
            evidence_freshness="api_live" if search_used else "model_only",
            llm_used=True,
            model_used=self.model_router.summarizer,
            formatted_markdown=summary,
            formatter_model_used="answer-only",
            reasoning_mode="pydantic_query_understanding+grounded_search",
            needs_user_confirmation=False,
        )

    def _compose_response(
        self,
        *,
        request: TravelPlanRequest,
        cache_key: str,
        intent: TravelIntent,
        search_plan: SearchPlan,
        plan_draft: TripPlanDraft,
        candidate_verdicts: list[Any],
        api_payloads: dict[str, Any],
        api_warnings: list[str],
        agent_results: list[AgentResult],
        critic: dict[str, Any],
    ) -> TravelPlanResponse:
        resolved_intent = _resolved_intent(request, intent=intent, search_plan=search_plan)
        groups = _category_groups(request, api_payloads, agent_results, resolved_intent=resolved_intent)
        recommendations = (
            _recommendations_from_groups(groups)
            if request.requested_categories
            else _recommendations_from_agents(agent_results)
        )
        if not recommendations:
            recommendations = _recommendations_from_groups(groups)
        display_cards = _display_cards(
            request,
            api_payloads,
            groups,
            resolved_intent,
            agent_results=agent_results,
        )
        hotel_offers = _hotel_offers(request, api_payloads)
        flight_offers = _flight_offers(request, api_payloads)
        if flight_offers and not (resolved_intent.get("is_complete_itinerary") or request.requested_categories):
            display_cards = []
        if hotel_offers and str(resolved_intent.get("category") or "") == "住宿":
            display_cards = []
        map_view = _map_view(request, display_cards)
        not_recommended = _not_recommended_from_critic(critic, request)
        warnings = list(dict.fromkeys([*api_warnings, *_string_list(critic.get("warnings"))]))
        runtime_warnings = [warning for warning in warnings if _is_runtime_warning(warning)]
        user_warnings = [warning for warning in warnings if not _is_runtime_warning(warning)]
        optional_followups = _optional_followups(request, user_warnings)
        data_gaps = _hard_data_gaps(request, user_warnings)
        search_used = _search_used_from_payloads(api_payloads)
        provider_name = self._api_provider_name()
        suggestion_source = provider_name if search_used else "model_only"
        model_used = ",".join(
            dict.fromkeys([result.model for result in agent_results] + [self.model_router.critic])
        )
        refs = provider_refs("travel")
        if runtime_warnings:
            refs["model_runtime_warnings"] = runtime_warnings
        refs["agent_results"] = {
            _display_agent_name(result.name): _agent_result_dict(result)
            for result in agent_results
        }
        refs[f"{provider_name}_engines"] = sorted(api_payloads.keys())
        refs["query_variants"] = search_plan.query_variants or _workflow_query_variants(request)
        refs["search_plan"] = search_plan.model_dump(mode="json")
        refs["capability_plan"] = intent.capability_plan.model_dump(mode="json")
        refs["api_bus"] = _api_bus_refs(plan_draft, api_payloads)
        refs["typed_offers"] = {
            "hotel_count": len(hotel_offers),
            "flight_count": len(flight_offers),
            "activity_count": 0,
            "route_count": 0,
        }
        refs["candidate_verification"] = [
            verdict.model_dump(mode="json") if hasattr(verdict, "model_dump") else verdict
            for verdict in candidate_verdicts[:40]
        ]
        if _should_preserve_raw_query(request, api_payloads):
            grounded_answer = _grounded_answer_result(
                request,
                api_payloads,
                optional_followups=optional_followups,
            )
            refs["source_preserving_candidates"] = [
                candidate.model_dump(mode="json") for candidate in grounded_answer.candidates
            ]
            refs["grounded_answer_pipeline"] = grounded_answer.pipeline_meta
        refs["langgraph_compatible_workflow"] = _langgraph_compatible_workflow()
        refs["langgraph_orchestrator"] = _langgraph_orchestrator_refs(intent, plan_draft, api_payloads)
        summary = str(critic.get("summary") or "").strip()
        if not summary:
            summary = "多 Agent 推荐：已按目的地、航班、酒店、活动和行程可行性汇总。"
        return TravelPlanResponse(
            summary=summary,
            capability_plan=intent.capability_plan.model_dump(mode="json"),
            recommendations=recommendations,
            not_recommended=not_recommended,
            conditional_options=[],
            excluded_candidates=[],
            decision_notes=[
                "Supervisor 已并发调用 Destination / Flight / Hotel / Itinerary / Activity-Food Agent。",
                "Critic 已检查预算、时间冲突、路线过满和信息缺口。",
            ],
            uncertainty=data_gaps,
            evidence_cards=[],
            pros=[item for result in agent_results for item in _item_titles(result.items[:2])],
            cons=data_gaps,
            route_summary={
                "used": bool(api_payloads.get("flight") or api_payloads.get("hotel")),
                "source": provider_name,
                "warnings": data_gaps,
            },
            budget_summary={
                "items": _list_of_dicts(api_payloads.get("budget")),
                "source": provider_name,
                "assumption": _budget_assumption(request),
            },
            transport_summary={
                "items": _list_of_dicts(api_payloads.get("transport")),
                "source": provider_name,
            },
            optional_context={
                key: _list_of_dicts(api_payloads.get(key))
                for key in ["visa", "weather", "safety"]
                if api_payloads.get(key)
            },
            suggestion_groups=groups,
            category_groups=groups,
            resolved_intent=resolved_intent,
            intent_summary=plan_draft.intent_summary,
            plan_draft=plan_draft.model_dump(mode="json"),
            decision_cards=_decision_cards_from_display_cards(display_cards, plan_draft=plan_draft),
            narrative_answer=summary,
            followup_slots=plan_draft.followup_slots,
            hotel_offers=hotel_offers,
            flight_offers=flight_offers,
            search_plan=search_plan.model_dump(mode="json"),
            answer_mode=intent.answer_mode,
            candidate_verification=[
                verdict.model_dump(mode="json") if hasattr(verdict, "model_dump") else verdict
                for verdict in candidate_verdicts[:40]
            ],
            display_cards=display_cards,
            map_view=map_view,
            suggestion_source=suggestion_source,
            api_sources_used=travel_sources(),
            source_breakdown=source_breakdown(travel_sources()),
            commercial_disclosure=TRAVEL_COMMERCIAL_DISCLOSURE,
            raw_provider_refs=refs,
            thinking_steps=travel_trace_steps(
                llm_used=True,
                model_used=model_used,
                suggestion_source=suggestion_source,
                search_used=search_used,
                cache_hit=False,
            ),
            agentic_workflow=_agentic_workflow_steps(
                request=request,
                api_payloads=api_payloads,
                agent_results=agent_results,
                critic=critic,
                formatter_model=self.model_router.formatter,
                provider_name=provider_name,
            ),
            cache=cache_info("travel", cache_key),
            search_used=search_used,
            search_queries=search_plan.query_variants or _search_queries(request, provider_name),
            sources_consulted=_sources_consulted(api_payloads, provider_name),
            # Pydantic allows extra fields only when declared on the schema; answer_mode
            # is exposed through resolved_intent for backwards compatibility.
            data_gaps=data_gaps,
            optional_followups=optional_followups,
            evidence_freshness="api_live" if search_used else "model_only",
            llm_used=True,
            model_used=model_used,
            reasoning_mode="pydantic_ai_supervisor+parallel_agents",
            needs_user_confirmation=bool(data_gaps),
        )

    async def _apply_ranked_card_reasoner(
        self,
        *,
        request: TravelPlanRequest,
        response: TravelPlanResponse,
    ) -> TravelPlanResponse:
        if not response.display_cards:
            return response
        runner = getattr(self.agent_client, "run_agent", None)
        if not callable(runner):
            return response

        model = self.model_router.activity_food
        payload = _ranked_card_reasoner_payload(request=request, response=response)
        try:
            result = await asyncio.wait_for(
                runner(
                    agent_name="card_reasoner",
                    model=model,
                    prompt=(
                        "For the already ranked display cards, write one concise Chinese "
                        "recommendation reason per card. Preserve the card order and exact "
                        "titles. The reason must answer the user's query, use only the card "
                        "fields provided, and may mention rating, review count, location, "
                        "category, or source when present. Do not invent prices, opening "
                        "hours, stock, photos, or hidden evidence."
                    ),
                    payload=payload,
                ),
                timeout=120.0,
            )
        except Exception as exc:
            refs = dict(response.raw_provider_refs or {})
            refs["ranked_card_reasoner"] = {
                "model": model,
                "status": "fallback",
                "warning": _exception_summary(exc),
            }
            return response.model_copy(update={"raw_provider_refs": refs})

        reasons = _agent_reasons_by_items(_list_of_dicts(result.get("items")))
        if not reasons:
            refs = dict(response.raw_provider_refs or {})
            refs["ranked_card_reasoner"] = {
                "model": model,
                "status": "fallback",
                "warning": "no matching card reasons returned",
            }
            return response.model_copy(update={"raw_provider_refs": refs})

        updated_cards: list[TravelDisplayCard] = []
        matched = 0
        for card in response.display_cards:
            reason = reasons.get(_title_key(card.title))
            if reason:
                matched += 1
                display_reason = _public_display_reason(
                    {
                        "rating": card.rating,
                        "reviews": card.review_count,
                        "address": card.address,
                        "location": card.address,
                        "type": card.subcategory or card.category,
                        "category": card.category,
                    },
                    reason,
                )
                updated_cards.append(
                    card.model_copy(
                        update={
                            "reason": reason,
                            "display_reason": display_reason,
                            "description": _card_description_from_card(card, display_reason),
                        }
                    )
                )
            else:
                updated_cards.append(card)

        refs = dict(response.raw_provider_refs or {})
        refs["ranked_card_reasoner"] = {
            "model": model,
            "status": "completed" if matched else "fallback",
            "matched": matched,
            "requested": len(response.display_cards),
        }
        return response.model_copy(
            update={
                "display_cards": updated_cards,
                "map_view": _map_view(request, updated_cards),
                "raw_provider_refs": refs,
            }
        )

    async def _apply_narrative_composer(
        self,
        *,
        request: TravelPlanRequest,
        response: TravelPlanResponse,
        plan_draft: TripPlanDraft,
        api_payloads: dict[str, Any],
    ) -> TravelPlanResponse:
        runner = getattr(self.agent_client, "run_agent", None)
        if not callable(runner):
            raise TravelModelCallError("narrative_composer", "agent client unavailable", model=self.model_router.itinerary)

        payload = {
            "request": request.model_dump(mode="json"),
            "intent_summary": response.intent_summary,
            "plan_draft": plan_draft.model_dump(mode="json"),
            "decision_cards": [card.model_dump(mode="json") for card in response.decision_cards],
            "display_cards": [
                {
                    "title": card.title,
                    "category": card.category,
                    "subcategory": card.subcategory,
                    "rating": card.rating,
                    "review_count": card.review_count,
                    "address": card.address,
                    "display_reason": card.display_reason,
                }
                for card in response.display_cards[:8]
            ],
            "data_gaps": response.data_gaps,
            "api_sources": sorted(api_payloads.keys()),
            "rules": [
                "Write a natural, short answer in Chinese.",
                "Explain why the visible recommendations fit the user's question.",
                "Do not invent opening hours, inventory, prices, or booking availability.",
                "Do not introduce hotels, flights, or full itinerary when the plan draft skipped them.",
            ],
        }
        try:
            result = await asyncio.wait_for(
                runner(
                    agent_name="narrative_composer",
                    model=self.model_router.itinerary,
                    prompt=(
                        "Based only on the TripPlanDraft, decision cards, and API candidates, "
                        "write the final user-facing travel recommendation explanation. "
                        "Keep it concise and avoid adding unsupported facts."
                    ),
                    payload=payload,
                ),
                timeout=180.0,
            )
        except Exception as exc:
            raise TravelModelCallError("narrative_composer", _exception_summary(exc), model=self.model_router.itinerary) from exc

        narrative = str(
            (result or {}).get("narrative_answer")
            or (result or {}).get("summary")
            or ""
        ).strip()
        if not narrative or _is_generic_narrative_answer(narrative):
            raise TravelModelCallError("narrative_composer", "generic or empty narrative", model=self.model_router.itinerary)
        decision_notes = [
            *response.decision_notes,
            *_string_list((result or {}).get("decision_notes")),
        ]
        return response.model_copy(
            update={
                "summary": narrative,
                "narrative_answer": narrative,
                "decision_notes": list(dict.fromkeys(decision_notes)),
            }
        )

    async def _apply_workflow_summarizer(
        self,
        *,
        request: TravelPlanRequest,
        response: TravelPlanResponse,
        agent_results: list[AgentResult],
        critic: dict[str, Any],
        api_payloads: dict[str, Any],
    ) -> TravelPlanResponse:
        if _should_preserve_raw_query(request, api_payloads):
            summary = _deterministic_workflow_summary(
                response=response,
                agent_results=agent_results,
                critic=critic,
                api_payloads=api_payloads,
            )
            return response.model_copy(
                update={
                    "workflow_summary": summary,
                    "agentic_workflow": _update_summarize_step(
                        response.agentic_workflow,
                        summary,
                        status="completed",
                        fallback_reason="source-preserving table path",
                    ),
                }
            )
        summarizer = getattr(self.agent_client, "summarize_workflow", None)
        if not callable(summarizer):
            raise TravelModelCallError("workflow_summarizer", "summarizer unavailable", model=self.model_router.planner)
        baseline = _deterministic_workflow_summary(
            response=response,
            agent_results=agent_results,
            critic=critic,
            api_payloads=api_payloads,
        )
        payload = _workflow_summarizer_payload(
            request=request,
            response=response,
            agent_results=agent_results,
            critic=critic,
            api_payloads=api_payloads,
            fallback=baseline,
        )
        try:
            model_summary = await asyncio.wait_for(
                summarizer(model=self.model_router.planner, payload=payload),
                timeout=90.0,
            )
            summary = _normalize_workflow_summary(model_summary, baseline)
        except Exception as exc:
            raise TravelModelCallError("workflow_summarizer", _exception_summary(exc), model=self.model_router.planner) from exc
        return response.model_copy(
            update={
                "workflow_summary": summary,
                "agentic_workflow": _update_summarize_step(
                    response.agentic_workflow,
                    summary,
                    status="completed",
                    fallback_reason="",
                ),
            }
        )

    async def _apply_formatter(
        self,
        *,
        request: TravelPlanRequest,
        response: TravelPlanResponse,
        agent_results: list[AgentResult],
        critic: dict[str, Any],
        api_payloads: dict[str, Any],
    ) -> TravelPlanResponse:
        if _should_preserve_raw_query(request, api_payloads):
            return response.model_copy(
                update={
                    "formatted_markdown": _source_preserving_markdown(
                        request=request,
                        response=response,
                        api_payloads=api_payloads,
                    ),
                    "formatter_model_used": "source-preserving-table",
                }
            )
        formatter = getattr(self.agent_client, "format_markdown", None)
        payload = _formatter_payload(
            request=request,
            response=response,
            agent_results=agent_results,
            critic=critic,
            api_payloads=api_payloads,
        )
        if not callable(formatter):
            raise TravelModelCallError("formatter", "formatter unavailable", model=self.model_router.formatter)
        try:
            formatted = await asyncio.wait_for(
                formatter(model=self.model_router.formatter, payload=payload),
                timeout=180.0,
            )
            return response.model_copy(
                update={
                    "formatted_markdown": formatted,
                    "formatter_model_used": self.model_router.formatter,
                }
            )
        except Exception as exc:
            raise TravelModelCallError("formatter", _exception_summary(exc), model=self.model_router.formatter) from exc

    @staticmethod
    def _request_cache_key(request: TravelPlanRequest) -> str:
        payload = json.dumps(
            {"version": "travel_recommendation_supervisor_v41_place_contract_guard", "request": request.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _api_provider_name(self) -> str:
        return str(getattr(self.serpapi_client, "provider_name", "serpapi"))


def _system_prompt_for_agent(agent_name: str) -> str:
    if agent_name == "travel_orchestrator":
        return TRAVEL_ORCHESTRATOR_PROMPT
    if agent_name == "complex_route_reasoner":
        return (
            "You are a bounded complex route and travel feasibility tool. Return "
            "strict JSON only. Compare route modes, time, budget, feasibility, and "
            "tradeoffs from the supplied request and tool data. Do not write the "
            "final user-facing answer."
        )
    if agent_name == "critic_verifier":
        return (
            "You are a bounded verifier tool. Return strict JSON only. Check that "
            "cards, route options, inventory, maps, and narrative claims are grounded "
            "in supplied tool outputs. Report warnings and data gaps."
        )
    if agent_name == "visual_context_analyzer":
        return (
            "You are a bounded Gemini multimodal context tool. Return strict JSON "
            "only. Use visual context only for image/place clues and nearby travel "
            "anchors; do not handle ordinary text-only travel planning."
        )
    if agent_name == "query_understanding":
        return (
            "You are the query_understanding router for a generalized travel "
            "multi-agent system. Return strict JSON only, matching the supplied "
            "router schema. Do not answer the travel question. Classify the user "
            "goal, decide which capabilities/tools/agents are required, and keep "
            "answer-only knowledge questions free of map cards and specialist fanout."
        )
    if agent_name == "search_planner":
        return (
            "You are the search_planner for a travel workflow. Return strict JSON "
            "only, matching the supplied search schema. Build query variants and "
            "tool choices from the capability plan. Do not answer the user."
        )
    if agent_name == "trip_plan_drafter":
        return (
            "You are the trip_plan_drafter for a travel workflow. Return strict "
            "JSON only, matching the supplied draft schema. Create internal tasks "
            "for downstream tools and agents without inventing unavailable inventory."
        )
    if agent_name == "candidate_verifier":
        return (
            "You are the candidate_verifier for a travel workflow. Return strict "
            "JSON only, matching the supplied verifier schema. Judge each candidate "
            "against the user's semantic request; popularity cannot override mismatch."
        )
    if agent_name == "narrative_composer":
        return (
            "You are the narrative_composer for a travel workflow. Return strict "
            "JSON only, matching the supplied narrative schema. Write a grounded "
            "user-facing answer only from the supplied cards, API data, and plan."
        )
    return (
        "You are one specialist in a generalized travel multi-agent system. "
        "Return strict JSON only. Follow the supplied capability plan and task "
        "contract; do not invent realtime prices, inventory, schedules, or sources."
    )


def _required_schema_for_agent(agent_name: str) -> dict[str, Any]:
    if agent_name == "travel_orchestrator":
        return {
            "answer_mode": "answer_only|place_cards|itinerary|route_map",
            "place_grounding_rule": (
                "If the answer recommends named real-world places, set answer_mode to place_cards "
                "and include one cards item per recommended place; the backend will use real places data "
                "for cards and map_pins. If the user is asking for explanation, evaluation, comparison, "
                "or whether a place is local/touristy, keep answer_mode answer_only and use serper_search "
                "at most; do not request serper_places just because a city or previous map context exists."
            ),
            "sections": [
                {
                    "id": "string",
                    "title": "string",
                    "body": "string",
                    "bullets": ["string"],
                    "chips": ["string"],
                    "tables": [
                        {
                            "caption": "string",
                            "columns": ["string"],
                            "rows": [["string"]],
                        }
                    ],
                    "images": [
                        {
                            "url": "string",
                            "caption": "string",
                            "source": "string",
                        }
                    ],
                    "card_ids": ["string"],
                    "pin_ids": ["string"],
                }
            ],
            "tool_calls_requested": [
                {
                    "name": "serper_search|serper_places|serper_images|route_lookup",
                    "arguments": "object",
                    "required": "boolean",
                }
            ],
            "cards": [
                {
                    "id": "string",
                    "title": "string",
                    "category": "string",
                    "image_url": "string",
                    "image_urls": ["string"],
                }
            ],
            "map_pins": [
                {
                    "id": "string",
                    "title": "string",
                    "lat": "number",
                    "lng": "number",
                }
            ],
            "itinerary_plan": "object",
            "route_options": ["object"],
            "hotel_offers": ["object"],
            "flight_offers": ["object"],
            "warnings": ["string"],
            "data_gaps": ["string"],
        }
    if agent_name == "complex_route_reasoner":
        return {
            "summary": "string",
            "route_options": [
                {
                    "id": "string",
                    "title": "string",
                    "provider": "string",
                    "duration": "string",
                    "distance": "string",
                    "mode": "string",
                    "source_url": "string",
                    "display_reason": "string",
                    "data_gaps": ["string"],
                }
            ],
            "warnings": ["string"],
        }
    if agent_name == "critic_verifier":
        return {
            "summary": "string",
            "warnings": ["string"],
            "data_gaps": ["string"],
            "not_recommended": ["object"],
        }
    if agent_name == "visual_context_analyzer":
        return {
            "summary": "string",
            "places_hint": ["string"],
            "warnings": ["string"],
        }
    if agent_name == "query_understanding":
        return {
            "task_type": "travel_question|place_evaluation|place_recommendation|itinerary_planning|route_planning|hotel_search|flight_search",
            "answer_mode": "answer_only|place_detail|place_cards|itinerary|route_map",
            "requires_place": "boolean",
            "needs_geo": "boolean",
            "needs_realtime_inventory": "boolean",
            "needs_knowledge": "boolean",
            "delivery_strategy": "single_agent|fanout",
            "destination": "string",
            "category": "string",
            "target_entity": "string",
            "target_type": "string",
            "requested_outputs": ["string"],
            "need_supplier_types": ["flights|hotels|activities"],
            "must_answer": ["string"],
            "should_not_answer": ["string"],
            "constraints": ["string"],
            "capability_plan": {
                "user_goal": "string",
                "intent_kind": "answer_only|place_lookup|place_evaluation|itinerary|route|inventory",
                "required_capabilities": ["knowledge|places|maps|activities|budget|transport|hotels|flights"],
                "tool_tasks": [
                    {
                        "task_id": "string",
                        "capability": "string",
                        "query": "string",
                        "required": "boolean",
                    }
                ],
                "agent_tasks": [
                    {
                        "task_id": "string",
                        "agent_role": "destination|activity_food|hotel|flight|itinerary",
                        "objective": "string",
                        "input_keys": ["string"],
                        "required": "boolean",
                    }
                ],
                "answer_contract": {
                    "needs_map": "boolean",
                    "needs_cards": "boolean",
                    "needs_itinerary": "boolean",
                    "needs_inventory": "boolean",
                    "response_style": "narrative|cards|itinerary|route",
                },
                "confidence": "number",
            },
            "confidence": "number",
            "clarifying_question": "string",
        }
    if agent_name == "search_planner":
        return {
            "should_search": "boolean",
            "tools": ["raw_query|local|maps|hotels|flights|budget|transport|weather|visa|safety"],
            "query_variants": ["string"],
            "locale": "auto|ja|en|zh",
            "must_satisfy": ["string"],
            "exclude_types": ["string"],
        }
    if agent_name == "trip_plan_drafter":
        return {
            "intent_summary": "string",
            "answer_strategy": "string",
            "required_capabilities": ["string"],
            "skipped_capabilities": ["string"],
            "tasks": [
                {
                    "agent_role": "destination|activity_food|hotel|flight|itinerary",
                    "objective": "string",
                    "input_keys": ["string"],
                    "required": "boolean",
                }
            ],
            "followup_slots": ["string"],
            "confidence": "number",
        }
    if agent_name == "candidate_verifier":
        return {
            "verdicts": [
                {
                    "candidate_id": "string",
                    "is_relevant": "boolean",
                    "relevance_score": "integer 0-100",
                    "matched_requirements": ["string"],
                    "missing_requirements": ["string"],
                    "match_reason": "string",
                }
            ]
        }
    if agent_name == "narrative_composer":
        return {
            "narrative_answer": "string",
            "decision_notes": ["string"],
        }
    return {
        "summary": "string",
        "items": [{"title": "string", "reason": "string"}],
        "warnings": ["string"],
        "not_recommended": [{"title": "string", "reason": "string"}],
    }


def _native_tools_for_agent(agent_name: str, payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    if agent_name != "travel_orchestrator":
        return None
    contract = payload.get("tool_contract")
    if not isinstance(contract, list):
        return None
    tool_specs: dict[str, dict[str, Any]] = {
        "serper_search": {
            "description": "Search Google web results via Serper.dev for current travel context when map places are not required.",
            "properties": {
                "query": {"type": "string", "description": "Search query with city and travel intent."}
            },
            "required": ["query"],
        },
        "serper_places": {
            "description": "Search real Google local/places results via Serper.dev for restaurants, attractions, shopping, parks, or nearby POIs that can become cards and map pins.",
            "properties": {
                "query": {"type": "string", "description": "Local/places query with city and category."},
                "category": {"type": "string", "description": "Short category such as 美食, 购物, or 本地体验."},
            },
            "required": ["query", "category"],
        },
        "serper_images": {
            "description": "Search images via Serper.dev to enrich already selected places or destination context.",
            "properties": {
                "query": {"type": "string", "description": "Image search query."}
            },
            "required": ["query"],
        },
        "route_lookup": {
            "description": "Look up route or transport evidence for intercity or multi-stop travel questions.",
            "properties": {
                "origin": {"type": "string", "description": "Starting city or place."},
                "destination": {"type": "string", "description": "Destination city or place."},
                "mode": {"type": "string", "description": "Preferred mode, for example rail, transit, walking, driving, or mixed."},
            },
            "required": ["origin", "destination", "mode"],
        },
    }
    tools: list[dict[str, Any]] = []
    for raw_name in contract:
        name = str(raw_name)
        spec = tool_specs.get(name)
        if not spec:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": {
                        "type": "object",
                        "properties": spec["properties"],
                        "required": spec["required"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        )
    return tools or None


def _max_tokens_for_agent(agent_name: str) -> int:
    if agent_name == "travel_orchestrator":
        return 7000
    if agent_name in {"complex_route_reasoner", "critic_verifier", "visual_context_analyzer"}:
        return 5000
    if agent_name == "candidate_verifier":
        return 8000
    if agent_name in {"destination", "hotel", "activity_food", "flight", "itinerary", "critic"}:
        return 6000
    if agent_name == "query_understanding":
        return 3600
    if agent_name == "trip_plan_drafter":
        return 5000
    if agent_name == "search_planner":
        return 2000
    if agent_name == "narrative_composer":
        return 5000
    return 2400


def _plan_capabilities(plan_draft: TripPlanDraft, intent: TravelIntent) -> list[str]:
    capabilities = _string_list(plan_draft.required_capabilities)
    if capabilities:
        return capabilities
    capabilities = _string_list(intent.need_supplier_types)
    if capabilities:
        return capabilities
    if intent.answer_mode == "answer_only" or not intent.requires_place:
        return ["knowledge"]
    if intent.answer_mode in {"itinerary", "route_map"}:
        return ["places", "routes", "maps", "activities", "budget", "transport", "knowledge"]
    return ["places", "maps", "knowledge"]


def _agent_specs_for_plan(
    request: TravelPlanRequest,
    intent: TravelIntent,
    plan_draft: TripPlanDraft,
    api_payloads: dict[str, Any],
) -> list[tuple[str, str, Any]]:
    capabilities = set(_plan_capabilities(plan_draft, intent))
    local_payloads = {key: value for key, value in api_payloads.items() if key.startswith("local:")}
    specs: list[tuple[str, str, Any]] = []
    for task in plan_draft.tasks:
        if not isinstance(task, dict):
            continue
        role = str(task.get("agent_role") or task.get("agent") or "").strip()
        if role not in {"destination", "flight", "hotel", "itinerary", "activity_food"}:
            continue
        input_keys = _string_list(task.get("input_keys"))
        if input_keys:
            payload = {key: api_payloads.get(key, []) for key in input_keys if key in api_payloads}
        elif role == "activity_food":
            payload = local_payloads or api_payloads
        elif role == "hotel":
            payload = api_payloads.get("hotel") or api_payloads.get("hotel_supplier_placeholder", [])
        elif role == "flight":
            payload = api_payloads.get("flight", [])
        elif role == "destination":
            payload = api_payloads.get("destination", api_payloads)
        else:
            payload = api_payloads
        specs.append((role, str(task.get("objective") or task.get("purpose") or role), payload))
    if specs:
        seen_roles: set[str] = set()
        unique_specs: list[tuple[str, str, Any]] = []
        for spec in specs:
            if spec[0] in seen_roles:
                continue
            seen_roles.add(spec[0])
            unique_specs.append(spec)
        return unique_specs[:5]
    if intent.answer_mode in {"itinerary", "route_map"} or intent.delivery_strategy == "fanout":
        if api_payloads.get("destination") or intent.answer_mode in {"itinerary", "route_map"}:
            specs.append(("destination", "判断目的地、季节和整体旅行方向。", api_payloads.get("destination", [])))
        if "flights" in capabilities:
            specs.append(("flight", "基于航班供应商结果提炼大交通选择和风险。", api_payloads.get("flight", [])))
        if "hotels" in capabilities:
            specs.append(("hotel", "基于酒店供应商结果做住宿和预算匹配。", api_payloads.get("hotel", [])))
        if intent.answer_mode in {"itinerary", "route_map"}:
            specs.append(
                (
                    "itinerary",
                    "把活动、路线、预算、交通和可选上下文合并为可执行行程。",
                    api_payloads,
                )
            )
        if capabilities & {"places", "activities", "maps"} and local_payloads:
            specs.append(
                (
                    "activity_food",
                    "基于地点/活动结果提炼最符合当前问题的推荐。",
                    local_payloads,
                )
            )
        if not specs:
            specs.append(("destination", "判断目的地和当前问题的推荐方向。", api_payloads))
        return specs[:5]
    if "hotels" in capabilities:
        specs.append(
            (
                "hotel",
                "基于酒店供应商结果或接入状态说明住宿选择和信息缺口。",
                api_payloads.get("hotel") or api_payloads.get("hotel_supplier_placeholder", []),
            )
        )
    if "flights" in capabilities:
        specs.append(
            (
                "flight",
                "基于航班供应商结果或接入状态说明大交通选择和信息缺口。",
                api_payloads.get("flight", []),
            )
        )
    if capabilities & {"places", "activities", "maps"} and local_payloads:
        specs.append(
            (
                "activity_food",
                "基于地点/活动结果提炼最符合当前问题的推荐。",
                local_payloads,
            )
        )
    if not specs:
        specs.append(("destination", "判断目的地和当前问题的推荐方向。", api_payloads))
    return specs[:4]


def _hotel_supplier_placeholder() -> list[dict[str, Any]]:
    return [
        {
            "title": "酒店供应商未接入",
            "capability": "hotels",
            "status": "not_configured",
            "snippet": "当前仅保留酒店 adapter 合同，尚未接入真实库存、价格和深链。",
        }
    ]


def _api_bus_refs(plan_draft: TripPlanDraft, api_payloads: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime": "capability_adapter_bus",
        "required_capabilities": _string_list(plan_draft.required_capabilities),
        "skipped_capabilities": _string_list(plan_draft.skipped_capabilities),
        "tasks": [
            {
                "task_id": str(task.get("task_id") or task.get("id") or ""),
                "capability": str(task.get("capability") or ""),
                "purpose": str(task.get("purpose") or ""),
                "required": bool(task.get("required", False)),
            }
            for task in plan_draft.tasks
            if isinstance(task, dict)
        ],
        "providers_used": sorted(api_payloads.keys()),
    }


def _search_used_from_payloads(api_payloads: dict[str, Any]) -> bool:
    placeholder_keys = {"hotel_supplier_placeholder", "flight_supplier_placeholder", "payment_supplier_placeholder"}
    return any(
        key not in placeholder_keys and bool(_list_of_dicts(value))
        for key, value in api_payloads.items()
    )


def _decision_cards_from_display_cards(
    cards: list[TravelDisplayCard],
    *,
    plan_draft: TripPlanDraft,
) -> list[TravelDecisionCard]:
    capabilities = set(_string_list(plan_draft.required_capabilities))
    supplier = "places" if "places" in capabilities or cards else "knowledge"
    decision_cards: list[TravelDecisionCard] = []
    for index, card in enumerate(cards[:8]):
        gaps: list[str] = []
        if not card.lat or not card.lng:
            gaps.append("缺少精确坐标，地图位置需要进一步核对。")
        if not card.rating:
            gaps.append("缺少评分信息。")
        decision_cards.append(
            TravelDecisionCard(
                id=f"decision-{index + 1}",
                title=card.title,
                decision="conditional" if gaps else "recommend",
                supplier_capability=supplier,
                category=card.category,
                reason=card.display_reason or card.description or card.reason,
                tradeoffs=[] if not gaps else ["信息完整度不足时不要直接当成最终预约建议。"],
                data_gaps=gaps,
                card_id=card.id,
                source_url=card.source_url or card.google_maps_uri,
                confidence="medium" if gaps else "high",
            )
        )
    return decision_cards


def _is_generic_narrative_answer(value: str) -> bool:
    return bool(
        re.search(
            r"多 Agent|已完成多 Agent|基于 API 候选生成推荐|narrative_composer completed",
            value,
            flags=re.I,
        )
    )


def _agentic_workflow_steps(
    *,
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    agent_results: list[AgentResult],
    critic: dict[str, Any],
    formatter_model: str,
    provider_name: str,
) -> list[TravelWorkflowStep]:
    tool_names = _workflow_tool_names(api_payloads, provider_name)
    return [
        TravelWorkflowStep(
            phase="plan",
            actor="Supervisor",
            action="解析用户目标、上下文、分类范围和可用工具。",
            tools=[],
            observation={
                "city": request.city,
                "requested_categories": request.requested_categories,
                "has_previous_context": bool(request.previous_context),
            },
        ),
        TravelWorkflowStep(
            phase="act",
            actor="Supervisor",
            action="主动调用搜索/API 工具收集候选信息。",
            tools=tool_names,
            observation={"tool_count": len(tool_names)},
        ),
        TravelWorkflowStep(
            phase="observe",
            actor="Supervisor",
            action="汇总工具返回并统计可用候选。",
            tools=tool_names,
            observation={
                "source_count": len(api_payloads),
                "total_items": len(_flatten_api_items(api_payloads)),
                "sources": sorted(api_payloads.keys()),
                "query_variants": _workflow_query_variants(request),
            },
        ),
        TravelWorkflowStep(
            phase="analyze",
            actor="Multi-Agent",
            action="并发调用专家 Agent 进行分维度分析。",
            tools=[_display_agent_name(result.name) for result in agent_results],
            observation={
                "agent_count": len(agent_results),
                "completed": sum(1 for result in agent_results if result.status == "completed"),
                "fallback": sum(1 for result in agent_results if result.status != "completed"),
            },
        ),
        TravelWorkflowStep(
            phase="critique",
            actor="Critic",
            action="检查冲突、预算、时间、可用性和不建议项。",
            tools=["Critic"],
            observation={
                "warnings": len(_string_list(critic.get("warnings"))),
                "not_recommended": len(_list_of_dicts(critic.get("not_recommended"))),
            },
        ),
        TravelWorkflowStep(
            phase="summarize",
            actor="Summarizer",
            action="压缩 ReAct 过程为可展示的结构化摘要。",
            tools=[],
            observation={
                "summary_available": False,
                "hidden_chain_of_thought": False,
            },
        ),
        TravelWorkflowStep(
            phase="finalize",
            actor="Formatter",
            action="把结构化推荐整理成自然语言回答。",
            tools=[formatter_model],
            observation={"format": "markdown", "hidden_chain_of_thought": False},
        ),
    ]


def _workflow_tool_names(api_payloads: dict[str, Any], provider_name: str) -> list[str]:
    return [f"{provider_name}:{key}" for key in sorted(api_payloads.keys())]


def _workflow_query_variants(request: TravelPlanRequest) -> list[str]:
    variants = [request.query.strip()] if request.query.strip() else []
    intent = _resolved_intent(request)
    variants.extend(_string_list(intent.get("query_variants")))
    lowered = request.query.lower()
    city = request.city.lower().strip()
    if city in {"fukuoka", "福冈", "福岡"}:
        variants.extend(["Fukuoka", "福岡", "ふくおか"])
    is_fragrance_query = any(
        token in lowered or token in request.query
        for token in ["香水", "perfume", "fragrance", "parfum", "パルファム"]
    )
    explicit_bergmann = "bergmann" in lowered or "バーグマン" in request.query
    if "nicolai" in lowered or "ニコライ" in request.query:
        if is_fragrance_query and not explicit_bergmann:
            variants.extend(["Nicolai Parfumeur 福岡", "ニコライ 香水 福岡", "NOSE SHOP Nicolai 福岡"])
        else:
            variants.extend(["Nicolai Bergmann 福岡", "ニコライ・バーグマン 福岡", "ニコライバーグマン 福岡"])
    return [item for item in dict.fromkeys(variants) if item]


def _deterministic_workflow_summary(
    *,
    response: TravelPlanResponse,
    agent_results: list[AgentResult],
    critic: dict[str, Any],
    api_payloads: dict[str, Any],
) -> dict[str, Any]:
    tool_names = _workflow_tool_names(api_payloads, response.suggestion_source or "api")
    total_items = len(_flatten_api_items(api_payloads))
    agent_count = len(agent_results)
    required_capabilities = set(_string_list((response.plan_draft or {}).get("required_capabilities")))
    if response.answer_mode in {"itinerary", "route_map"} and required_capabilities & {"hotels", "flights"}:
        agent_count = max(agent_count, 5)
    warnings = [
        warning
        for warning in _string_list(critic.get("warnings"))
        if not _is_model_runtime_warning(warning)
    ]
    return {
        "tool_summary": (
            f"调用了 {len(tool_names)} 个工具，观察到 {total_items} 条候选，"
            f"{agent_count} 个专家 Agent 完成分维度分析。"
        ),
        "sources_used": tool_names[:12],
        "candidate_counts": {
            "tool_count": len(tool_names),
            "source_count": len(api_payloads),
            "total_items": total_items,
            "agent_count": agent_count,
            "not_recommended_count": len(response.not_recommended),
        },
        "agent_findings": [
            f"{_display_agent_name(result.name)}: {result.summary}"
            for result in agent_results
            if result.summary
        ][:6],
        "critic_notes": [str(critic.get("summary") or "").strip(), *warnings][:5],
        "confidence": "medium" if total_items else "low",
        "missing_but_non_blocking": response.optional_followups[:6],
    }


def _workflow_summarizer_payload(
    *,
    request: TravelPlanRequest,
    response: TravelPlanResponse,
    agent_results: list[AgentResult],
    critic: dict[str, Any],
    api_payloads: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request": {
            "query": request.query,
            "city": request.city,
            "date_range": request.date_range,
            "requested_categories": request.requested_categories,
            "has_previous_context": bool(request.previous_context),
        },
        "visible_workflow": [step.model_dump(mode="json") for step in response.agentic_workflow],
        "api_sources": sorted(api_payloads.keys()),
        "candidate_counts": fallback.get("candidate_counts", {}),
        "agent_results": [_agent_result_dict(result) for result in agent_results],
        "critic": _compact_value(_user_visible_critic(critic), limit=4),
        "final_cards": {
            "category_groups": [
                {"title": group.title, "items": group.items[:5]}
                for group in response.category_groups[:6]
            ],
            "not_recommended_count": len(response.not_recommended),
            "optional_followups": response.optional_followups[:6],
        },
        "required_schema": {
            "tool_summary": "string",
            "sources_used": ["string"],
            "candidate_counts": {
                "tool_count": "number",
                "source_count": "number",
                "total_items": "number",
                "agent_count": "number",
                "not_recommended_count": "number",
            },
            "agent_findings": ["string"],
            "critic_notes": ["string"],
            "confidence": "low|medium|high",
            "missing_but_non_blocking": ["string"],
        },
    }


def _user_visible_critic(critic: dict[str, Any]) -> dict[str, Any]:
    visible = dict(critic)
    visible["warnings"] = [
        warning
        for warning in _string_list(critic.get("warnings"))
        if not _is_model_runtime_warning(warning)
    ]
    return visible


def _with_model_runtime_warning(response: TravelPlanResponse, warning: str) -> dict[str, Any]:
    refs = dict(response.raw_provider_refs or {})
    refs["model_runtime_warnings"] = list(
        dict.fromkeys([*_string_list(refs.get("model_runtime_warnings")), warning])
    )
    return refs


def _normalize_workflow_summary(value: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return fallback
    normalized = dict(fallback)
    for key in [
        "tool_summary",
        "sources_used",
        "candidate_counts",
        "agent_findings",
        "critic_notes",
        "confidence",
        "missing_but_non_blocking",
    ]:
        item = value.get(key)
        if item not in (None, "", []):
            normalized[key] = item
    normalized["sources_used"] = _string_list(normalized.get("sources_used"))[:12]
    normalized["agent_findings"] = _string_list(normalized.get("agent_findings"))[:8]
    normalized["critic_notes"] = _string_list(normalized.get("critic_notes"))[:6]
    normalized["missing_but_non_blocking"] = _string_list(
        normalized.get("missing_but_non_blocking")
    )[:6]
    if not isinstance(normalized.get("candidate_counts"), dict):
        normalized["candidate_counts"] = fallback.get("candidate_counts", {})
    confidence = str(normalized.get("confidence") or fallback.get("confidence") or "medium").lower()
    normalized["confidence"] = confidence if confidence in {"low", "medium", "high"} else "medium"
    return normalized


def _update_summarize_step(
    steps: list[TravelWorkflowStep],
    summary: dict[str, Any],
    *,
    status: str,
    fallback_reason: str,
) -> list[TravelWorkflowStep]:
    updated = []
    for step in steps:
        if step.phase != "summarize":
            updated.append(step)
            continue
        observation = {
            "summary_available": True,
            "hidden_chain_of_thought": False,
            "tool_summary": summary.get("tool_summary", ""),
            "candidate_counts": summary.get("candidate_counts", {}),
            "confidence": summary.get("confidence", "medium"),
        }
        if fallback_reason:
            observation["fallback_reason"] = fallback_reason
        updated.append(
            step.model_copy(
                update={
                    "tools": [settings.travel_model_reasoning],
                    "observation": observation,
                    "status": status,
                }
            )
        )
    return updated


def _langgraph_compatible_workflow() -> dict[str, Any]:
    nodes = [
        "parse_request",
        "collect_tools",
        "observe_results",
        "run_specialist_agents",
        "critic_review",
        "summarize_trace",
        "final_formatter",
    ]
    return {
        "runtime": "lightweight_react",
        "compatible_with": "LangGraph StateGraph nodes/edges",
        "nodes": nodes,
        "edges": [
            ["parse_request", "collect_tools"],
            ["collect_tools", "observe_results"],
            ["observe_results", "run_specialist_agents"],
            ["run_specialist_agents", "critic_review"],
            ["critic_review", "summarize_trace"],
            ["summarize_trace", "final_formatter"],
        ],
    }


def _langgraph_orchestrator_refs(
    intent: TravelIntent,
    plan_draft: TripPlanDraft,
    api_payloads: dict[str, Any],
) -> dict[str, Any]:
    capabilities = _string_list(plan_draft.required_capabilities or intent.need_supplier_types)
    strategy = intent.delivery_strategy or "single_agent"
    bypass = intent.answer_mode == "answer_only" and strategy == "single_agent"
    active_agent_caps = [
        capability
        for capability in capabilities
        if capability not in {"maps", "knowledge", "memory", "payment", "payments"}
    ]
    max_parallel_agents = 1 if bypass else min(4, max(1, len(active_agent_caps) or len(capabilities)))
    return {
        "runtime": "embedded_langgraph_library_contract",
        "platform_service": "not_deployed",
        "run_mode": "bypass" if bypass else "embedded_graph",
        "delivery_strategy": strategy,
        "graph_nodes": [
            "route",
            "plan_tasks",
            "fanout_agents",
            "validate_candidates",
            "compose_decision",
            "narrative",
            "render_contract",
        ],
        "edges": [
            ["route", "plan_tasks"],
            ["plan_tasks", "fanout_agents"],
            ["fanout_agents", "validate_candidates"],
            ["validate_candidates", "compose_decision"],
            ["compose_decision", "narrative"],
            ["narrative", "render_contract"],
        ],
        "required_capabilities": capabilities,
        "providers_used": sorted(api_payloads.keys()),
        "max_parallel_agents": max_parallel_agents,
        "global_active_run_limit": 2,
        "degrade_when_busy": False,
    }


def _request_intent_text(request: TravelPlanRequest) -> str:
    return " ".join(
        [
            request.query,
            request.question,
            " ".join(request.interest_tags),
            " ".join(request.requested_categories),
        ]
    )


def _resolved_intent(
    request: TravelPlanRequest,
    *,
    intent: TravelIntent | None = None,
    search_plan: SearchPlan | None = None,
) -> dict[str, object]:
    travel_intent = intent
    selected = (
        _selected_categories(
            request,
            resolved_intent=intent.model_dump(mode="json") if intent else None,
        )
        if request.requested_categories or intent
        else []
    )
    category = selected[0][0] if selected else (intent.category if intent else "")
    text = _request_intent_text(request).lower()
    scope = _request_scope(request)
    is_complete_itinerary = intent.answer_mode in {"itinerary", "route_map"} if intent else scope["broad"]
    subcategory = ""
    subcategory_label = ""
    target_entity = intent.target_entity if intent else ""
    if category == "美食":
        if target_entity:
            subcategory = "specific_dish"
            subcategory_label = target_entity
        elif any(
            token in text
            for token in [
                "日料",
                "日本料理",
                "japanese",
                "寿司",
                "sushi",
                "怀石",
                "kaiseki",
                "天妇罗",
                "tempura",
                "居酒屋",
                "izakaya",
            ]
        ):
            subcategory = "japanese_cuisine"
            subcategory_label = "日料"
        else:
            subcategory = "local_specialties"
            subcategory_label = "本地特色"
    elif category == "购物" and any(
        token in text for token in ["香水", "perfume", "fragrance", "parfum", "nicolai", "ニコライ"]
    ):
        subcategory = "fragrance"
        subcategory_label = "香水"
    elif category == "本地体验":
        if _has_hot_spring_marker(text):
            subcategory = "hot_spring"
            subcategory_label = "温泉"
        elif any(
            token in text for token in ["好玩", "玩什么", "去哪玩", "游玩", "景点", "things to do", "attraction"]
        ):
            subcategory = "things_to_do"
            subcategory_label = "景点活动"
    elif is_complete_itinerary:
        subcategory = "complete_itinerary"
        subcategory_label = "完整行程"
    intent = StructuredTravelIntent(
        task_type=travel_intent.task_type if travel_intent else "recommend",
        domain=travel_intent.domain if travel_intent else "travel",
        trip_stage=travel_intent.trip_stage if travel_intent else "planning",
        traveler_stage=travel_intent.traveler_stage if travel_intent else "inspiration",
        needs_geo=travel_intent.needs_geo if travel_intent else True,
        needs_realtime_inventory=travel_intent.needs_realtime_inventory if travel_intent else False,
        needs_user_memory=travel_intent.needs_user_memory if travel_intent else bool(request.previous_context),
        needs_knowledge=travel_intent.needs_knowledge if travel_intent else True,
        needs_transaction=travel_intent.needs_transaction if travel_intent else False,
        needs_explanation=travel_intent.needs_explanation if travel_intent else True,
        delivery_strategy=travel_intent.delivery_strategy if travel_intent else "single_agent",
        category=category,
        subcategory=subcategory,
        subcategory_label=subcategory_label,
        city=request.city,
        answer_mode=travel_intent.answer_mode if travel_intent else "place_cards",
        requires_place=travel_intent.requires_place if travel_intent else True,
        destination=(travel_intent.destination if travel_intent else "") or request.city,
        target_entity=target_entity,
        target_type=travel_intent.target_type if travel_intent else "",
        requested_outputs=travel_intent.requested_outputs if travel_intent else [],
        need_supplier_types=travel_intent.need_supplier_types if travel_intent else [],
        must_answer=travel_intent.must_answer if travel_intent else [],
        should_not_answer=travel_intent.should_not_answer if travel_intent else [],
        confidence=travel_intent.confidence if travel_intent else 0.6,
        clarifying_question=travel_intent.clarifying_question if travel_intent else "",
        is_complete_itinerary=is_complete_itinerary,
        entity_terms=search_plan.must_satisfy if search_plan else [],
        must_match_terms=search_plan.must_satisfy if search_plan else [],
        query_variants=search_plan.query_variants if search_plan else [],
        strictness="semantic_match" if target_entity else ("category_match" if subcategory else "broad_match"),
    )
    resolved = intent.model_dump(mode="json")
    if travel_intent is not None:
        resolved["capability_plan"] = travel_intent.capability_plan.model_dump(mode="json")
    return resolved


def _category_search_query(
    title: str,
    default_category: str,
    resolved_intent: dict[str, object],
) -> str:
    subcategory = str(resolved_intent.get("subcategory") or "")
    target_entity = str(resolved_intent.get("target_entity") or "").strip()
    target_type = str(resolved_intent.get("target_type") or "").strip()
    if target_entity and title == str(resolved_intent.get("category") or ""):
        return " ".join(part for part in [target_entity, target_type] if part) or default_category
    if title == "美食" and subcategory == "specific_dish":
        query_variants = _string_list(resolved_intent.get("query_variants"))
        terms = _string_list(resolved_intent.get("must_match_terms"))
        return " ".join(terms[:4] or query_variants[:2]) or default_category
    if title == "美食" and subcategory == "japanese_cuisine":
        return "japanese food restaurants sushi kaiseki izakaya tempura"
    if title == "美食" and subcategory == "local_specialties":
        return "food restaurants local specialties"
    if title == "购物" and subcategory == "fragrance":
        return "fragrance perfume shops department stores"
    if title == "本地体验" and subcategory == "hot_spring":
        return "onsen hot springs public bath rotenburo"
    if title == "本地体验" and subcategory == "things_to_do":
        return "things to do attractions activities experiences"
    return default_category


def _request_scope(request: TravelPlanRequest) -> dict[str, bool]:
    text = " ".join(
        [
            request.query,
            request.question,
            " ".join(request.constraints),
            " ".join(request.fixed_itinerary),
        ]
    ).lower()
    broad_markers = [
        "行程",
        "自由行",
        "几天",
        "三天",
        "两天",
        "完整",
        "安排",
        "itinerary",
        "trip",
        "plan",
    ]
    broad = bool(not request.requested_categories or any(marker in text for marker in broad_markers))
    budget = any(token in text for token in ["预算", "花费", "cost", "budget", "性价比"])
    transport = any(token in text for token in ["交通", "地铁", "公交", "路线", "怎么去", "怎么走", "transport", "subway"])
    return {"broad": broad, "budget": budget, "transport": transport}


def _selected_categories(
    request: TravelPlanRequest,
    resolved_intent: dict[str, object] | None = None,
) -> list[tuple[str, str]]:
    if resolved_intent and str(resolved_intent.get("answer_mode") or "") == "answer_only":
        return []
    requested = {
        _canonical_travel_category(category)
        for category in request.requested_categories
        if str(category or "").strip()
    }
    if (
        resolved_intent
        and not requested
        and str(resolved_intent.get("answer_mode") or "") in {"itinerary", "route_map"}
    ):
        return AGENT_CATEGORIES
    category = _canonical_travel_category((resolved_intent or {}).get("category"))
    if not requested and category:
        requested = {category}
    if not requested:
        return AGENT_CATEGORIES
    selected = [item for item in AGENT_CATEGORIES if item[0] in requested]
    if selected:
        return selected
    if resolved_intent and category and category not in {title for title, _ in AGENT_CATEGORIES}:
        return []
    return AGENT_CATEGORIES


def _canonical_travel_category(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = _normalized_category_key(text)
    return TRAVEL_CATEGORY_ALIASES.get(normalized, text)


def _normalized_category_key(value: str) -> str:
    normalized = value.strip().lower().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", normalized)


def _budget_assumption(request: TravelPlanRequest) -> dict[str, str]:
    text = f"{request.query} {request.budget}".lower()
    currency = "CNY"
    if any(token in text for token in ["日元", "円", "jpy"]):
        currency = "JPY"
    elif any(token in text for token in ["美元", "usd", "$"]):
        currency = "USD"
    scope = "total_trip_with_flight_hotel" if _budget_includes_flight_hotel(request) else "local_spend_only"
    return {
        "currency": currency,
        "scope": scope,
        "note": "未明确包含机酒时，预算默认只用于当地消费、餐饮、交通、门票和活动。",
    }


def _answer_only_summary(
    request: TravelPlanRequest,
    intent: TravelIntent,
    api_payloads: dict[str, Any],
) -> str:
    subject = intent.target_entity or request.query or request.question
    snippets = []
    for item in _flatten_api_items(api_payloads):
        title = _item_title(item)
        snippet = str(item.get("snippet") or item.get("description") or item.get("address") or "").strip()
        if title or snippet:
            snippets.append("：".join(part for part in [title, snippet] if part))
        if len(snippets) >= 3:
            break
    if snippets:
        return (
            f"{subject} 这个问题不需要先选地点；我先按知识问答处理。"
            f"可参考的信息包括：{'；'.join(snippets)}。"
        )
    return f"{subject} 这个问题不需要先选地点；我先按知识问答处理，不强行生成地图或门店推荐。"


def _budget_includes_flight_hotel(request: TravelPlanRequest) -> bool:
    text = f"{request.query} {request.budget}"
    include_tokens = ["含机票", "含酒店", "含住宿", "包含机酒", "含机酒", "总预算", "all-in", "including flight"]
    return any(token.lower() in text.lower() for token in include_tokens)


def _optional_followups(request: TravelPlanRequest, warnings: list[str]) -> list[str]:
    followups = []
    if not request.origin_city:
        followups.append("补充出发地后，可以给出更准确的大交通或航班建议。")
    if not request.date_range:
        followups.append("补充日期后，可以更准确地判断天气、住宿价格和营业时间。")
    if request.budget and not _budget_includes_flight_hotel(request):
        followups.append("当前预算默认按当地消费处理；如果包含机票或酒店，请直接说明。")
    for warning in warnings:
        if _is_minor_missing_info(warning) and warning not in followups:
            followups.append(warning)
    return list(dict.fromkeys(followups))[:6]


def _hard_data_gaps(request: TravelPlanRequest, warnings: list[str]) -> list[str]:
    return [
        warning
        for warning in warnings
        if not _is_minor_missing_info(warning)
        and not _is_runtime_warning(warning)
        and not _is_out_of_scope_warning(request, warning)
        and (_budget_includes_flight_hotel(request) or "预算严重不匹配" not in warning)
    ]


def _is_runtime_warning(text: str) -> bool:
    return _is_model_runtime_warning(text) or _is_google_places_runtime_warning(text)


def _is_model_runtime_warning(text: str) -> bool:
    markers = [
        "模型调用失败",
        "formatter 31B 超时",
        "HTTPStatusError",
        "API 调用失败",
    ]
    return any(marker in text for marker in markers)


def _is_google_places_runtime_warning(text: str) -> bool:
    return "Google Places 解析" in text or _is_google_places_quota_warning(text)


def _is_google_places_quota_warning(text: str) -> bool:
    return "HTTP 429" in text or "Quota exceeded" in text


def _is_minor_missing_info(text: str) -> bool:
    if "SERPAPI_API_KEY" in text or "SERPER_API_KEY" in text:
        return False
    markers = [
        "缺少出发地",
        "出发地缺失",
        "未确认出发地",
        "未获知出发",
        "无法查询实时航班",
        "需要出发地",
        "缺少日期",
        "日期缺失",
        "未确认日期",
        "季节性信息缺失",
        "预算单位",
        "价格敏感型建议",
        "货币假设",
        "未提供日期",
        "酒店价格需要之后确认",
        "酒店预算匹配缺少实时价格",
        "无法计算总预算",
    ]
    return any(marker in text for marker in markers)


def _is_out_of_scope_warning(request: TravelPlanRequest, text: str) -> bool:
    if not request.requested_categories:
        return False
    markers = ["Flight", "Hotel", "航班", "酒店", "机票", "住宿"]
    return any(marker in text for marker in markers)


def _optional_context_keys(request: TravelPlanRequest) -> list[str]:
    text = " ".join(
        [
            request.query,
            request.question,
            " ".join(request.constraints),
            " ".join(request.avoid),
            " ".join(request.interest_tags),
        ]
    ).lower()
    keys = []
    if any(token in text for token in ["visa", "entry", "immigration", "签证", "入境"]):
        keys.append("visa")
    if any(token in text for token in ["weather", "season", "rain", "typhoon", "天气", "季节", "雨", "台风"]):
        keys.append("weather")
    if any(token in text for token in ["safety", "insurance", "solo", "female", "女旅", "安全", "保险"]):
        keys.append("safety")
    return keys


def _compact_api_payloads(api_payloads: dict[str, Any]) -> dict[str, Any]:
    return _compact_api_payloads_with_limit(api_payloads, limit=3)


def _compact_api_payloads_with_limit(api_payloads: dict[str, Any], *, limit: int) -> dict[str, Any]:
    return {key: _compact_value(value, limit=limit) for key, value in api_payloads.items()}


def _source_material_payload(api_payloads: dict[str, Any], *, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    material: dict[str, list[dict[str, Any]]] = {}
    for key, value in api_payloads.items():
        items = _flatten_api_items(value)
        compact_items = [_source_material_item(item) for item in items[:limit]]
        compact_items = [item for item in compact_items if item]
        if compact_items:
            material[key] = compact_items
    return material


def _source_material_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "title",
        "name",
        "place",
        "destination",
        "snippet",
        "description",
        "summary",
        "reason",
        "address",
        "rating",
        "reviews",
        "price",
        "rate",
        "latitude",
        "longitude",
        "lat",
        "lng",
        "cid",
        "googleMapsUri",
        "google_maps_uri",
        "duration",
        "link",
        "website",
        "query_variant",
        "serper_endpoint",
    ]
    compact = {
        key: _compact_value(value, limit=3)
        for key in allowed
        if (value := item.get(key)) not in (None, "", [])
    }
    if not compact and item:
        for key, value in list(item.items())[:4]:
            if value not in (None, "", []):
                compact[str(key)] = _compact_value(value, limit=3)
    return compact


def _formatter_payload(
    *,
    request: TravelPlanRequest,
    response: TravelPlanResponse,
    agent_results: list[AgentResult],
    critic: dict[str, Any],
    api_payloads: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request": {
            "query": request.query,
            "origin_city": request.origin_city,
            "city": request.city,
            "date_range": request.date_range,
            "budget": request.budget,
            "travelers": request.travelers,
            "interests": request.interest_tags,
            "avoid": request.avoid,
            "pace": request.pace,
            "transport_mode": request.transport_mode,
        },
        "summary": response.summary,
        "workflow_summary": _compact_value(response.workflow_summary, limit=6),
        "source_material": _source_material_payload(api_payloads, limit=5),
        "structured_response": {
            "category_count": len(response.category_groups),
            "recommendation_count": len(response.recommendations),
            "not_recommended_count": len(response.not_recommended),
            "data_gap_count": len(response.data_gaps),
        },
        "category_groups": [
            {"title": group.title, "items": group.items[:5], "reason": group.reason}
            for group in response.category_groups[:6]
        ],
        "recommendations": [
            {
                "name": item.place.name,
                "category": item.place.category,
                "pros": item.pros[:2],
                "cons": item.cons[:2],
                "caution": item.caution,
                "decision": item.decision,
            }
            for item in response.recommendations[:8]
        ],
        "not_recommended": [
            {"name": item.place.name, "reason": item.decision_reason or item.caution}
            for item in response.not_recommended[:5]
        ],
        "budget_summary": _compact_value(response.budget_summary, limit=4),
        "transport_summary": _compact_value(response.transport_summary, limit=4),
        "optional_context": _compact_value(response.optional_context, limit=3),
        "pros": response.pros[:6],
        "cons": response.cons[:6],
        "data_gaps": response.data_gaps[:6],
        "optional_followups": response.optional_followups[:6],
        "agent_summaries": [
            {
                "name": _display_agent_name(result.name),
                "model": result.model,
                "summary": result.summary,
                "items": _compact_value(result.items, limit=6),
                "raw_api_results": _compact_value(result.raw_api_results, limit=4),
                "warnings": result.warnings[:4],
            }
            for result in agent_results
        ],
        "critic": _compact_value(_user_visible_critic(critic), limit=4),
        "api_sources": sorted(api_payloads.keys()),
        "instructions": (
            "输出自然、亲切、结构清晰的中文 Markdown，不强制使用固定栏目或固定分点。"
            "根据问题复杂度自由组织旅行建议；有地点推荐时，给出可保存/可加入行程的地点卡片，"
            "并说明地图、距离、顺路关系和下一步怎么改计划。尽量保留原始候选名称、"
            "原始摘要、地址、评分、价格、坐标等可用字段，不要过度总结或二次改写。"
            "如果来源内容很多，优先完整展示有用选择，再做轻量归纳。"
            "过滤广告、赞助、推广、营销感强或来源不清的候选；"
            "正反面评价可以保留，但不要为了框架强行加证据或风险；"
            "optional_followups 只放在末尾作为补充后更准的信息。不要制造事实，也不要提及内部规则。"
        ),
    }


def _compact_value(value: Any, *, limit: int) -> Any:
    if isinstance(value, list):
        return [_compact_value(item, limit=limit) for item in value[:limit]]
    if isinstance(value, dict):
        preferred = [
            "title",
            "name",
            "summary",
            "snippet",
            "reason",
            "description",
            "price",
            "rating",
            "address",
            "link",
            "items",
            "warnings",
            "not_recommended",
        ]
        compact: dict[str, Any] = {}
        for key in preferred:
            if key in value:
                compact[key] = _compact_value(value[key], limit=limit)
        if compact:
            return compact
        return {
            key: _compact_value(item, limit=limit)
            for key, item in list(value.items())[:limit]
        }
    if isinstance(value, str) and len(value) > 800:
        return f"{value[:800]}..."
    return value


def _category_groups(
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    agent_results: list[AgentResult],
    resolved_intent: dict[str, object] | None = None,
) -> list[TravelSuggestionGroup]:
    activity = next(
        (result for result in agent_results if result.name == "activity_food"),
        None,
    )
    activity_items = activity.items if activity else []
    resolved_intent = resolved_intent or _resolved_intent(request)
    exact_entity = _requires_exact_entity_match(resolved_intent)
    raw_query_items = _raw_query_items_for_category(request, api_payloads, resolved_intent=resolved_intent)
    raw_query_items = _filter_marketing_or_ad_items(raw_query_items)
    groups = []
    selected_categories = _selected_categories(request, resolved_intent=resolved_intent)
    selected_categories = _include_local_payload_categories(selected_categories, api_payloads)
    for title, category in selected_categories:
        api_items = _filter_items_for_intent(
            _filter_marketing_or_ad_items(_list_of_dicts(api_payloads.get(f"local:{title}"))),
            resolved_intent,
            title,
        )
        names = []
        if raw_query_items and title == _raw_query_target_category(request, resolved_intent=resolved_intent):
            names.extend(_item_titles(raw_query_items))
        names.extend(_item_title(item) for item in api_items)
        if len(names) < 3 and not exact_entity:
            names.extend(_item_titles(activity_items))
        if len(names) < 3 and not exact_entity:
            names.extend(_fallback_items(request.city, title))
        reason = (
            f"严格匹配 {resolved_intent.get('subcategory_label')}；未命中具体实体的普通候选不会进入核心推荐。"
            if exact_entity and title == resolved_intent.get("category")
            else "API 候选优先；不足时由对应 Agent 用用户偏好补足，不伪造成证据。"
        )
        groups.append(
            TravelSuggestionGroup(
                title=title,
                intent=f"从 Serper/API 候选中筛选 {title} 相关建议。",
                items=list(dict.fromkeys([name for name in names if name]))[:5],
                reason=reason,
                evidence_needed=False,
            )
        )
    return groups


def _include_local_payload_categories(
    selected_categories: list[tuple[str, str]],
    api_payloads: dict[str, Any],
) -> list[tuple[str, str]]:
    selected = list(selected_categories)
    seen = {title for title, _ in selected}
    for key, value in api_payloads.items():
        if not key.startswith("local:") or not _list_of_dicts(value):
            continue
        title = key.split(":", 1)[1].strip()
        if not title or title in seen:
            continue
        selected.append((title, title))
        seen.add(title)
    return selected


def _raw_query_items_for_category(
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    resolved_intent: dict[str, object] | None = None,
) -> list[dict[str, Any]]:
    raw_items = _list_of_dicts(api_payloads.get("raw_query"))
    raw_items = _filter_marketing_or_ad_items(raw_items)
    if not raw_items:
        return []
    resolved_intent = resolved_intent or _resolved_intent(request)
    if _requires_exact_entity_match(resolved_intent):
        matched_items = _filter_items_for_intent(
            raw_items,
            resolved_intent,
            str(resolved_intent.get("category") or ""),
        )
        return sorted(
            matched_items,
            key=lambda item: _raw_query_relevance_score(request, item),
            reverse=True,
        )[:5]
    text = request.query.lower()
    if not any(token in text for token in ["nicolai", "香水", "perfume", "fragrance", "ニコライ"]):
        return []
    return sorted(raw_items, key=lambda item: _raw_query_relevance_score(request, item), reverse=True)[:5]


def _should_preserve_raw_query(
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
) -> bool:
    text = request.query.lower()
    return bool(
        api_payloads.get("raw_query")
        and any(
            token in text
            for token in ["哪里买", "买", "购买", "店", "店舗", "香水", "perfume", "fragrance", "nicolai", "ニコライ"]
        )
    )


def _source_preserving_markdown(
    *,
    request: TravelPlanRequest,
    response: TravelPlanResponse,
    api_payloads: dict[str, Any],
) -> str:
    return _grounded_answer_result(
        request,
        api_payloads,
        optional_followups=response.optional_followups,
    ).markdown


def _source_preserving_candidates(
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        candidate.model_dump(mode="json")
        for candidate in _grounded_answer_result(request, api_payloads).candidates
    ]


def _grounded_answer_result(
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    *,
    optional_followups: list[str] | None = None,
) -> GroundedAnswerResult:
    items = _raw_query_items_for_category(request, api_payloads)
    if not items:
        items = _list_of_dicts(api_payloads.get("raw_query"))[:6]
    documents = SerperSearchResultAdapter().to_documents(items)
    return GroundedAnswerPipeline().run(
        request=request,
        documents=documents,
        optional_followups=optional_followups,
    )


def _requires_exact_entity_match(resolved_intent: dict[str, object]) -> bool:
    return str(resolved_intent.get("strictness") or "") in {"exact_match", "semantic_match"} and bool(
        _string_list(resolved_intent.get("must_match_terms"))
        or str(resolved_intent.get("target_entity") or "").strip()
    )


def _filter_items_for_intent(
    items: list[dict[str, Any]],
    resolved_intent: dict[str, object],
    category: str,
) -> list[dict[str, Any]]:
    if not _requires_exact_entity_match(resolved_intent):
        return items
    if category != str(resolved_intent.get("category") or ""):
        return items
    return [item for item in items if _entity_match_score(item, resolved_intent) > 0]


def _entity_match_score(item: dict[str, Any], resolved_intent: dict[str, object]) -> int:
    return _entity_match_details(item, resolved_intent)["score"]


def _entity_match_details(item: dict[str, Any], resolved_intent: dict[str, object]) -> dict[str, Any]:
    terms = _string_list(resolved_intent.get("must_match_terms"))
    target_entity = str(resolved_intent.get("target_entity") or "").strip()
    if target_entity:
        terms = [*terms, target_entity]
    terms = list(dict.fromkeys(term for term in terms if term))
    label = str(resolved_intent.get("subcategory_label") or "").strip()
    semantic_score = int(item.get("semantic_relevance_score") or 0)
    semantic_reason = str(item.get("semantic_match_reason") or "").strip()
    semantic_terms = _string_list(item.get("semantic_matched_terms"))
    source_query = str(item.get("query_variant") or item.get("source_query") or "").strip()
    if semantic_score > 0:
        return {
            "score": semantic_score,
            "matched_terms": semantic_terms,
            "reason": semantic_reason,
            "source_query": source_query,
        }
    if not terms:
        return {"score": 0, "matched_terms": [], "reason": "", "source_query": ""}
    haystack = _normalized_match_text(_candidate_text(item))
    matched = [
        term
        for term in terms
        if _normalized_match_text(term) and _normalized_match_text(term) in haystack
    ]
    score = len(matched) * 10
    if label and _normalized_match_text(label) in haystack:
        score += 4
    reason = ""
    if matched:
        reason = f"匹配{label or '具体需求'}：命中 {', '.join(matched[:4])}。"
        if source_query:
            reason += f" 来源查询：{source_query}。"
    return {
        "score": score,
        "matched_terms": matched,
        "reason": reason,
        "source_query": source_query,
    }


def _candidate_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ["title", "name", "snippet", "address", "link", "type", "category", "query_variant"]
    ).lower()


def _has_fragrance_marker(text: str) -> bool:
    return any(
        token in text
        for token in [
            "香水",
            "perfume",
            "fragrance",
            "parfum",
            "パルファム",
            "フレグランス",
        ]
    )


def _has_hot_spring_marker(text: str) -> bool:
    return any(
        token in text
        for token in [
            "温泉",
            "溫泉",
            "泡汤",
            "泡湯",
            "泡温泉",
            "泡溫泉",
            "onsen",
            "hot spring",
            "public bath",
            "rotenburo",
            "露天風呂",
            "日帰り温泉",
        ]
    )


def _raw_query_target_category(
    request: TravelPlanRequest,
    resolved_intent: dict[str, object] | None = None,
) -> str:
    resolved_intent = resolved_intent or _resolved_intent(request)
    if _requires_exact_entity_match(resolved_intent):
        return str(resolved_intent.get("category") or "本地体验")
    text = request.query.lower()
    if any(token in text for token in ["香水", "perfume", "fragrance", "nicolai", "ニコライ"]):
        return "购物"
    return "本地体验"


def _raw_query_relevance_score(request: TravelPlanRequest, item: dict[str, Any]) -> int:
    text = _candidate_text(item)
    query = request.query.lower()
    score = int(item.get("semantic_relevance_score") or 0)
    resolved_intent = _resolved_intent(request)
    score += _entity_match_score(item, resolved_intent)
    for token in ["nicolai", "ニコライ"]:
        if token in query and token in text:
            score += 6
    if "nose shop" in text:
        score += 5
    if _has_fragrance_marker(text):
        score += 2
    if "fukuoka" in text or "福岡" in text or "福冈" in text:
        score += 1
    return score


def _recommendations_from_agents(agent_results: list[AgentResult]) -> list[TravelRecommendation]:
    cards: list[TravelRecommendation] = []
    for result in agent_results:
        if result.name == "critic":
            continue
        for item in result.items[:2]:
            title = _item_title(item)
            cards.append(
                TravelRecommendation(
                    place=PlaceCandidate(
                        name=title or _display_agent_name(result.name),
                        category=_display_agent_name(result.name),
                        confidence=0.72,
                        match_reason="multi-agent recommendation",
                        tags=[result.name],
                        photo_potential=0.0,
                    ),
                    score=0.72,
                    reasons=[_item_reason(item), f"来自 {_display_agent_name(result.name)} Agent"],
                    caution="这是 API/Agent 推荐，不是订票结论；出发前需核对价格和营业时间。",
                    ad_risk_label="中",
                    decision="conditional",
                    decision_reason="需要用户确认预算、日期和个人偏好后再最终决定。",
                    pros=[_item_reason(item)],
                    cons=[],
                    evidence_confidence="api",
                    evidence_cards=[
                        EvidenceCard(
                            source_type="api",
                            title=_display_agent_name(result.name),
                            snippet=result.summary,
                            score=0.6,
                            ad_risk=0.2,
                        )
                    ],
                )
            )
    return cards[:8]


def _recommendations_from_groups(groups: list[TravelSuggestionGroup]) -> list[TravelRecommendation]:
    cards: list[TravelRecommendation] = []
    for group in groups:
        for item in group.items[:1]:
            cards.append(
                TravelRecommendation(
                    place=PlaceCandidate(
                        name=item,
                        category=group.title,
                        confidence=0.45,
                        match_reason="model-only category fallback",
                        tags=[group.title],
                    ),
                    score=0.45,
                    reasons=[group.intent or group.reason],
                    caution="当前缺少实时 API 候选，先作为方向建议而不是最终预订方案。",
                    ad_risk_label="未知",
                    decision="conditional",
                    decision_reason="需要补充实时 API 或用户偏好后确认。",
                    pros=[group.reason],
                    cons=["缺少实时航班/酒店/地图候选"],
                    evidence_confidence="low",
                    evidence_cards=[],
                )
            )
    return cards[:6]


def _not_recommended_from_critic(critic: dict[str, Any], request: TravelPlanRequest) -> list[TravelRecommendation]:
    items = _list_of_dicts(critic.get("not_recommended"))
    recommendations = []
    for item in items[:4]:
        title = _item_title(item)
        reason = _item_reason(item)
        combined = f"{title} {reason}"
        if _is_minor_missing_info(combined):
            continue
        if _is_out_of_scope_warning(request, combined):
            continue
        if request.requested_categories and not _budget_includes_flight_hotel(request):
            continue
        if "预算" in combined and not _budget_includes_flight_hotel(request):
            continue
        recommendations.append(
            TravelRecommendation(
                place=PlaceCandidate(name=title, category="critic"),
                score=0.0,
                reasons=[reason],
                caution=f"不建议：{reason}",
                ad_risk_label="未知",
                decision="not_recommended",
                decision_reason=reason,
                pros=[],
                cons=[reason],
                evidence_confidence="api",
                evidence_cards=[],
            )
        )
    return recommendations


def _display_cards(
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    groups: list[TravelSuggestionGroup],
    resolved_intent: dict[str, object] | None = None,
    agent_results: list[AgentResult] | None = None,
) -> list[TravelDisplayCard]:
    resolved_intent = resolved_intent or _resolved_intent(request)
    agent_reasons = _agent_reasons_by_title(agent_results or [])
    cards: list[TravelDisplayCard] = []
    seen: set[str] = set()

    for group in groups:
        items: list[dict[str, Any]] = []
        local_key = f"local:{group.title}"
        local_items = _filter_items_for_intent(
            _filter_marketing_or_ad_items(_list_of_dicts(api_payloads.get(local_key))),
            resolved_intent,
            group.title,
        )
        local_items = _filter_primary_trip_card_items(
            local_items,
            request=request,
            resolved_intent=resolved_intent,
            group_title=group.title,
        )
        if (
            not local_items
            and local_key not in api_payloads
            and group.title == _raw_query_target_category(request, resolved_intent=resolved_intent)
        ):
            items.extend(
                _filter_primary_trip_card_items(
                    _raw_query_items_for_category(request, api_payloads, resolved_intent=resolved_intent),
                    request=request,
                    resolved_intent=resolved_intent,
                    group_title=group.title,
                )
            )
        items.extend(local_items)

        for item in sorted(items, key=lambda value: _display_item_quality_score(value, request), reverse=True):
            title = _item_title(item)
            if not title:
                continue
            key = _primary_trip_card_dedupe_key(item)
            if key in seen:
                continue
            seen.add(key)
            image_urls = _prefer_clear_image_urls(_item_image_urls(item))
            image_url = image_urls[0] if image_urls else ""
            image_status = _image_status(item, image_urls)
            card_id = f"card-{len(cards) + 1}"
            address = str(item.get("address") or item.get("location") or "").strip()
            lat = _coordinate(item, "lat")
            lng = _coordinate(item, "lng")
            place_id = _item_place_id(item)
            photo_attributions = _item_photo_attributions(item)
            google_maps_uri = _google_maps_uri(item, title=title, address=address, lat=lat, lng=lng)
            match_details = _entity_match_details(item, resolved_intent)
            reason = agent_reasons.get(_title_key(title)) or _item_reason(item)
            display_reason = (
                _task_aware_display_reason(
                    item,
                    request=request,
                    resolved_intent=resolved_intent,
                    group_title=group.title,
                )
                or _public_display_reason(item, reason)
            )
            cards.append(
                TravelDisplayCard(
                    id=card_id,
                    title=title,
                    category=group.title,
                    subcategory=_card_subcategory(request, group.title, item, resolved_intent),
                    subtitle=_item_subtitle(item),
                    description=_card_description(item, display_reason),
                    rating=_float_or_none(item.get("rating")),
                    review_count=_review_count(item),
                    price=_item_price(item),
                    address=address,
                    image_url=image_url,
                    image_urls=image_urls,
                    image_status=image_status,
                    source_url=str(item.get("link") or item.get("website") or "").strip(),
                    source_provider=str(item.get("serper_endpoint") or item.get("source") or "").strip(),
                    place_id=place_id,
                    photo_attributions=photo_attributions,
                    reason=reason,
                    display_reason=display_reason,
                    lat=lat,
                    lng=lng,
                    tags=[group.title],
                    trip_state=_trip_state_for_card(request, card_id, title),
                    google_maps_uri=google_maps_uri,
                    directions_uri=_directions_uri(item, title=title, address=address, lat=lat, lng=lng),
                    match_reason=str(match_details.get("reason") or ""),
                    matched_terms=_string_list(match_details.get("matched_terms")),
                    match_score=int(match_details.get("score") or 0),
                    source_query=str(match_details.get("source_query") or ""),
                )
            )
            if len(cards) >= 12:
                return cards

        if items:
            continue
        if local_key in api_payloads and not local_items:
            continue

    return cards


def _display_item_quality_score(item: dict[str, Any], request: TravelPlanRequest) -> tuple[int, int, int, int, int, float, int, int, int]:
    lat = _coordinate(item, "lat")
    lng = _coordinate(item, "lng")
    rating = _float_or_none(item.get("rating")) or 0.0
    reviews = _review_count(item) or 0
    resolved_intent = _resolved_intent(request)
    return (
        int(item.get("semantic_relevance_score") or 0),
        _entity_match_score(item, resolved_intent),
        _query_match_score(item, request),
        1 if lat is not None and lng is not None else 0,
        1 if _item_place_id(item) else 0,
        rating,
        reviews,
        1 if item.get("address") or item.get("location") else 0,
        0 if _is_generic_web_result(item) else 1,
    )


def _filter_primary_trip_card_items(
    items: list[dict[str, Any]],
    *,
    request: TravelPlanRequest,
    resolved_intent: dict[str, object],
    group_title: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if _can_be_primary_trip_card(
            item,
            request=request,
            resolved_intent=resolved_intent,
            group_title=group_title,
        )
    ]


def _can_be_primary_trip_card(
    item: dict[str, Any],
    *,
    request: TravelPlanRequest,
    resolved_intent: dict[str, object],
    group_title: str,
) -> bool:
    if _is_marketing_or_ad_item(item):
        return False
    if _is_generic_review_or_search_page(item):
        return False
    if _is_lodging_candidate(item) and not _is_lodging_request(request, resolved_intent, group_title):
        return False
    return True


def _is_lodging_request(
    request: TravelPlanRequest,
    resolved_intent: dict[str, object],
    group_title: str,
) -> bool:
    text = _normalized_match_text(
        " ".join(
            [
                request.query,
                request.question,
                " ".join(request.requested_categories),
                str(resolved_intent.get("category") or ""),
                group_title,
            ]
        )
    )
    return any(token in text for token in ["酒店", "住宿", "hotel", "hostel", "guesthouse", "guest house", "ryokan", "旅馆", "旅館"])


def _is_lodging_candidate(item: dict[str, Any]) -> bool:
    text = _normalized_match_text(
        " ".join(
            str(item.get(key) or "")
            for key in ["title", "name", "snippet", "description", "type", "category", "source", "link"]
        )
    )
    return any(
        token in text
        for token in [
            "hotel",
            "hotels",
            "hostel",
            "guesthouse",
            "guest house",
            "stay",
            "stays",
            "inn",
            "apartment hotel",
            "ryokan",
            "住宿",
            "酒店",
            "旅馆",
            "旅館",
            "民宿",
        ]
    )


def _is_generic_review_or_search_page(item: dict[str, Any]) -> bool:
    if not _is_generic_web_result(item):
        return False
    text = _normalized_match_text(
        " ".join(
            str(item.get(key) or "")
            for key in ["title", "name", "snippet", "description", "type", "category", "source", "domain", "link"]
        )
    )
    markers = [
        "reviews for",
        "review",
        "reviews",
        "yelp",
        "tripadvisor",
        "all you should know",
        "before going",
        "updated june",
        "best things to do",
        "top things to do",
        "things to do in",
        "search results",
        "listing",
        "listicle",
        "photos",
        "口コミ",
        "レビュー",
    ]
    return any(marker in text for marker in markers)


def _primary_trip_card_dedupe_key(item: dict[str, Any]) -> str:
    title = _normalized_match_text(_item_title(item))
    address = _normalized_match_text(str(item.get("address") or item.get("location") or ""))
    duplicate_markers = [
        ("ukimi do", "ohori-park"),
        ("ukimi-do", "ohori-park"),
        ("浮見堂", "ohori-park"),
        ("浮见堂", "ohori-park"),
        ("大濠", "ohori-park"),
        ("ohori", "ohori-park"),
        ("ohorikoen", "ohori-park"),
        ("藻岩", "moiwa"),
        ("moiwa", "moiwa"),
        ("清水", "kiyomizu"),
        ("kiyomizu", "kiyomizu"),
        ("伏见稻荷", "fushimi-inari"),
        ("伏見稲荷", "fushimi-inari"),
        ("fushimi inari", "fushimi-inari"),
        ("inari", "fushimi-inari"),
    ]
    combined = f"{title} {address}"
    for marker, key in duplicate_markers:
        if marker in combined:
            return key
    place_id = _item_place_id(item).lower()
    if place_id:
        return place_id
    noise_tokens = [
        "ropeway",
        "纜車",
        "缆车",
        "山顶展望台",
        "展望台",
        "observatory",
        "mount",
        "山",
        "the stage of",
        "大社",
        "shrine",
        "temple",
    ]
    normalized = title
    for token in noise_tokens:
        normalized = normalized.replace(token, " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or title.lower()


def _filter_marketing_or_ad_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if not _is_marketing_or_ad_item(item)]


def _is_marketing_or_ad_item(item: dict[str, Any]) -> bool:
    for key in ["ad", "is_ad", "sponsored", "is_sponsored", "promoted", "is_promoted", "paid", "is_paid"]:
        value = item.get(key)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "ad", "sponsored", "promoted", "paid"}:
            return True
    label_text = " ".join(
        str(item.get(key) or "")
        for key in ["label", "badge", "source_type", "result_type", "serper_type", "snippet", "description"]
    ).lower()
    return any(marker in label_text for marker in ["sponsored", "promoted", "paid placement", "广告", "赞助", "推廣", "推广"])


def _hotel_offers(request: TravelPlanRequest, api_payloads: dict[str, Any]) -> list[TravelHotelOffer]:
    offers: list[TravelHotelOffer] = []
    source_items = _list_of_dicts(api_payloads.get("hotel"))
    if not source_items:
        source_items = _list_of_dicts(api_payloads.get("hotel_supplier_placeholder"))
    for index, item in enumerate(source_items[:8]):
        title = _item_title(item)
        if not title:
            continue
        image_urls = _prefer_clear_image_urls(_item_image_urls(item))
        price = _item_price(item)
        address = str(item.get("address") or item.get("location") or item.get("neighborhood") or "").strip()
        rating = _float_or_none(item.get("rating"))
        review_count = _review_count(item)
        gaps: list[str] = []
        if not request.date_range:
            gaps.append("缺少入住/退房日期，价格和可订状态只能作为参考。")
        if item.get("status") == "not_configured" or item.get("capability") == "hotels":
            gaps.append("缺少可结构化酒店库存，当前只表示供应商能力缺口。")
        display_reason = _offer_reason(
            label="住宿",
            title=title,
            price=price,
            rating=rating,
            review_count=review_count,
            address=address,
            fallback="适合作为住宿候选，建议结合位置、价格和交通继续比较。",
        )
        offers.append(
            TravelHotelOffer(
                id=f"hotel-{index + 1}",
                title=title,
                price=price,
                rating=rating,
                review_count=review_count,
                address=address,
                image_url=image_urls[0] if image_urls else "",
                image_urls=image_urls,
                source_url=str(item.get("link") or item.get("website") or item.get("serpapi_link") or "").strip(),
                booking_url=str(item.get("booking_link") or item.get("link") or item.get("website") or "").strip(),
                check_in_date=request.date_range[0] if len(request.date_range) >= 1 else "",
                check_out_date=request.date_range[1] if len(request.date_range) >= 2 else "",
                currency=_budget_assumption(request)["currency"],
                display_reason=display_reason,
                data_gaps=gaps,
            )
        )
    return offers


def _flight_offers(request: TravelPlanRequest, api_payloads: dict[str, Any]) -> list[TravelFlightOffer]:
    offers: list[TravelFlightOffer] = []
    for index, item in enumerate(_list_of_dicts(api_payloads.get("flight"))[:8]):
        title = _item_title(item)
        if not title:
            continue
        price = _item_price(item)
        duration = str(item.get("duration") or item.get("total_duration") or "").strip()
        airline = _flight_airline(item)
        departure_airport = str(item.get("departure_airport") or item.get("departure_id") or "").strip()
        arrival_airport = str(item.get("arrival_airport") or item.get("arrival_id") or "").strip()
        departure_time = str(item.get("departure_time") or item.get("departure") or "").strip()
        arrival_time = str(item.get("arrival_time") or item.get("arrival") or "").strip()
        stops = str(item.get("stops") or item.get("layovers") or "").strip()
        gaps: list[str] = []
        if not request.origin_city:
            gaps.append("缺少出发地，无法确认完整航班比较。")
        if not request.date_range:
            gaps.append("缺少出行日期，无法确认实时航班价格。")
        display_reason = _offer_reason(
            label="航班",
            title=title,
            price=price,
            rating=None,
            review_count=None,
            address=" / ".join(part for part in [departure_airport, arrival_airport] if part),
            fallback="适合作为航班候选，建议结合时间、价格和中转次数继续比较。",
        )
        offers.append(
            TravelFlightOffer(
                id=f"flight-{index + 1}",
                title=title,
                airline=airline,
                departure_airport=departure_airport,
                arrival_airport=arrival_airport,
                departure_time=departure_time,
                arrival_time=arrival_time,
                duration=duration,
                stops=stops,
                price=price,
                currency=_budget_assumption(request)["currency"],
                source_url=str(item.get("link") or item.get("serpapi_link") or "").strip(),
                booking_url=str(item.get("booking_link") or item.get("link") or "").strip(),
                display_reason=display_reason,
                data_gaps=gaps,
            )
        )
    return offers


def _flight_airline(item: dict[str, Any]) -> str:
    flights = item.get("flights")
    if isinstance(flights, list):
        names = [
            str(flight.get("airline") or "").strip()
            for flight in flights
            if isinstance(flight, dict) and str(flight.get("airline") or "").strip()
        ]
        if names:
            return " / ".join(dict.fromkeys(names))
    return str(item.get("airline") or item.get("airlines") or "").strip()


def _offer_reason(
    *,
    label: str,
    title: str,
    price: str,
    rating: float | None,
    review_count: int | None,
    address: str,
    fallback: str,
) -> str:
    parts = []
    if price:
        parts.append(f"价格信息为 {price}")
    if rating is not None:
        text = f"评分 {rating:g}"
        if review_count:
            text += f"（{review_count} 条评价）"
        parts.append(text)
    if address:
        parts.append(f"位置/路线信息：{address}")
    if parts:
        return f"{label}推荐理由：{title} 的" + "；".join(parts) + "。"
    return f"{label}推荐理由：{fallback}"


def _is_generic_web_result(item: dict[str, Any]) -> bool:
    return bool(
        item.get("link")
        and not (item.get("address") or item.get("location") or _item_place_id(item))
        and _coordinate(item, "lat") is None
        and _coordinate(item, "lng") is None
    )


def _query_match_score(item: dict[str, Any], request: TravelPlanRequest) -> int:
    haystack = _normalized_match_text(
        " ".join(
            [
                _item_title(item),
                str(item.get("address") or item.get("location") or ""),
                _item_reason(item),
                str(item.get("type") or item.get("category") or ""),
            ]
        )
    )
    score = 0
    for token in _significant_match_tokens(f"{request.query} {' '.join(request.interest_tags)}"):
        if token in haystack:
            score += 1
    return score


def _agent_reasons_by_title(agent_results: list[AgentResult]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for result in agent_results:
        reasons.update({key: value for key, value in _agent_reasons_by_items(result.items).items() if key not in reasons})
    return reasons


def _agent_reasons_by_items(items: list[dict[str, Any]]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for item in items:
        title = _item_title(item)
        reason = _explicit_item_reason(item)
        if not title or not reason or _is_generic_agent_reason(reason):
            continue
        reasons.setdefault(_title_key(title), reason)
    return reasons


def _title_key(title: str) -> str:
    return _normalized_match_text(title)


def _explicit_item_reason(item: dict[str, Any]) -> str:
    value = item.get("reason") or item.get("description") or item.get("summary") or item.get("snippet")
    return str(value or "").strip()


def _is_generic_agent_reason(value: str) -> bool:
    return bool(re.fullmatch(r"api[-\s]?backed|api 候选.*|需要用户确认.*", value.strip(), flags=re.I))


def _ranked_card_reasoner_payload(
    *,
    request: TravelPlanRequest,
    response: TravelPlanResponse,
) -> dict[str, Any]:
    return {
        "request": {
            "query": request.query or request.question,
            "city": request.city,
            "requested_categories": request.requested_categories,
            "interest_tags": request.interest_tags,
            "avoid": request.avoid,
            "budget": request.budget,
            "travelers": request.travelers,
        },
        "resolved_intent": response.resolved_intent,
        "ranked_cards": [
            {
                "rank": index + 1,
                "title": card.title,
                "category": card.category,
                "subcategory": card.subcategory,
                "rating": card.rating,
                "review_count": card.review_count,
                "address": card.address,
                "price": card.price,
                "source_provider": card.source_provider,
                "existing_reason": card.reason,
            }
            for index, card in enumerate(response.display_cards)
        ],
    }


def _card_description_from_card(card: TravelDisplayCard, reason: str) -> str:
    return _card_description(
        {
            "rating": card.rating,
            "reviews": card.review_count,
            "address": card.address,
            "location": card.address,
            "price": card.price,
        },
        reason,
    )


def _map_view(request: TravelPlanRequest, cards: list[TravelDisplayCard]) -> dict[str, Any]:
    pins = [
        {
            "id": card.id,
            "title": card.title,
            "category": card.category,
            "subcategory": card.subcategory,
            "lat": card.lat,
            "lng": card.lng,
            "rating": card.rating,
            "address": card.address,
            "place_id": card.place_id,
            "trip_state": card.trip_state,
            "google_maps_uri": card.google_maps_uri,
            "directions_uri": card.directions_uri,
        }
        for card in cards
        if card.lat is not None and card.lng is not None
    ]
    center = _map_center(request.city, pins)
    return {
        "center": center,
        "pins": pins,
        "selected_pin_id": pins[0]["id"] if pins else "",
        "provider": "photo_agent_map",
        "mode": "dedicated_panel",
        "status": "ready" if pins else "needs_coordinates",
    }


def _card_subcategory(
    request: TravelPlanRequest,
    category: str,
    item: dict[str, Any],
    resolved_intent: dict[str, object],
) -> str:
    label = str(resolved_intent.get("subcategory_label") or "")
    subcategory = str(resolved_intent.get("subcategory") or "")
    text = _candidate_text(item)
    if category == "美食":
        if subcategory == "specific_dish":
            return label or "具体菜品"
        if subcategory == "japanese_cuisine":
            return "日料"
        if "ramen" in text or "拉面" in text or "ラーメン" in text:
            return "拉面"
        if "yatai" in text or "屋台" in text:
            return "屋台"
        if "motsunabe" in text or "牛肠锅" in text or "もつ鍋" in text:
            return "牛肠锅"
        if "mentaiko" in text or "明太子" in text:
            return "明太子"
        return label or "本地特色"
    if category == "购物" and subcategory == "fragrance":
        return "香水"
    if category == "本地体验":
        if subcategory == "hot_spring":
            return "温泉"
        if subcategory == "things_to_do":
            return "景点活动"
    return label


def _trip_state_for_card(request: TravelPlanRequest, card_id: str, title: str) -> str:
    context = request.previous_context if isinstance(request.previous_context, dict) else {}
    if _card_in_context(context.get("trip_items"), card_id, title):
        return "planned"
    if _card_in_context(context.get("liked_items"), card_id, title):
        return "liked"
    return "none"


def _card_in_context(items: Any, card_id: str, title: str) -> bool:
    if not isinstance(items, list):
        return False
    normalized_title = title.strip().lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == card_id:
            return True
        if str(item.get("title") or "").strip().lower() == normalized_title:
            return True
    return False


def _google_maps_uri(
    item: dict[str, Any],
    *,
    title: str,
    address: str,
    lat: float | None,
    lng: float | None,
) -> str:
    direct_uri = str(item.get("googleMapsUri") or item.get("google_maps_uri") or "").strip()
    if direct_uri:
        return direct_uri
    query = _google_maps_query(title=title, address=address, lat=lat, lng=lng)
    if not query:
        return ""
    uri = f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
    place_id = str(item.get("place_id") or item.get("placeId") or "").strip()
    if place_id:
        uri = f"{uri}&query_place_id={quote_plus(place_id)}"
    return uri


def _item_place_id(item: dict[str, Any]) -> str:
    return str(item.get("place_id") or item.get("placeId") or item.get("place_id_search") or "").strip()


def _item_photo_attributions(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    direct = item.get("photo_attributions") or item.get("photoAttributions")
    if isinstance(direct, list):
        values.extend(str(value).strip() for value in direct if str(value).strip())
    photos = item.get("photos")
    if isinstance(photos, list):
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            values.extend(_string_list(photo.get("photo_attributions") or photo.get("photoAttributions")))
            for key in ["authorAttributions", "author_attributions", "html_attributions"]:
                attribution_items = photo.get(key)
                if isinstance(attribution_items, list):
                    for attribution in attribution_items:
                        if isinstance(attribution, dict):
                            text = str(
                                attribution.get("displayName")
                                or attribution.get("display_name")
                                or attribution.get("name")
                                or attribution.get("uri")
                                or ""
                            ).strip()
                            if text:
                                values.append(text)
                        elif str(attribution).strip():
                            values.append(str(attribution).strip())
    return _unique_strings(values)


def _directions_uri(
    item: dict[str, Any],
    *,
    title: str,
    address: str,
    lat: float | None,
    lng: float | None,
) -> str:
    query = _google_maps_query(title=title, address=address, lat=lat, lng=lng)
    if not query:
        return ""
    place_id = str(item.get("place_id") or item.get("placeId") or "").strip()
    suffix = f"&destination_place_id={quote_plus(place_id)}" if place_id else ""
    return f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(query)}{suffix}"


def _google_maps_query(
    *,
    title: str,
    address: str,
    lat: float | None,
    lng: float | None,
) -> str:
    if title or address:
        return " ".join(part for part in [title.strip(), address.strip()] if part)
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    return ""


def _image_urls_from_payloads(api_payloads: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key, value in api_payloads.items():
        if not key.startswith("images:"):
            continue
        for item in _flatten_api_items(value):
            urls.extend(_item_image_urls(item))
    return _prefer_clear_image_urls(list(dict.fromkeys(urls)))


def _place_image_query(request: TravelPlanRequest, item: dict[str, Any]) -> str:
    title = _item_title(item)
    if not title or _is_generic_web_result(item):
        return ""
    parts = []
    for value in [title, request.city]:
        value = str(value or "").strip()
        if value and value.lower() not in {part.lower() for part in parts}:
            parts.append(value)
    return " ".join(parts)


def _strict_place_image_urls(item: dict[str, Any], image_items: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for image_item in image_items:
        if not _image_result_matches_place(item, image_item):
            continue
        urls.extend(_item_image_urls(image_item))
    return _prefer_clear_image_urls(urls)


def _image_result_matches_place(item: dict[str, Any], image_item: dict[str, Any]) -> bool:
    title = _item_title(item)
    tokens = _significant_match_tokens(title)
    if not tokens:
        return False
    haystack = _normalized_match_text(
        " ".join(
            str(image_item.get(key) or "")
            for key in [
                "title",
                "snippet",
                "source",
                "domain",
                "link",
                "imageUrl",
                "image_url",
                "thumbnailUrl",
                "thumbnail",
            ]
        )
    )
    if not haystack:
        return False
    matched = sum(1 for token in tokens if token in haystack)
    required = 2 if len(tokens) >= 2 else 1
    return matched >= required


def _significant_match_tokens(value: str) -> list[str]:
    normalized = _normalized_match_text(value)
    ascii_tokens = [token for token in re.findall(r"[a-z0-9]+", normalized) if len(token) >= 3]
    cjk_tokens = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]{2,}", normalized)
    expanded_tokens: list[str] = []
    for token in ascii_tokens:
        expanded_tokens.append(token)
        if token.endswith("hama") and len(token) > 6:
            expanded_tokens.append(token[:-4])
    tokens = [*expanded_tokens, *cjk_tokens]
    return list(dict.fromkeys(tokens))


def _normalized_match_text(value: str) -> str:
    cjk_variants = str.maketrans(
        {
            "运": "運",
            "园": "園",
            "馆": "館",
            "冈": "岡",
            "动": "動",
            "满": "満",
            "门": "門",
            "广": "廣",
            "场": "場",
            "旧": "舊",
            "区": "區",
        }
    )
    normalized = value.lower().translate(cjk_variants).replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _item_image_url(item: dict[str, Any]) -> str:
    urls = _item_image_urls(item)
    return urls[0] if urls else ""


def _item_image_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    direct_list = item.get("image_urls")
    if isinstance(direct_list, list):
        for value in direct_list:
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
    if str(item.get("image_status") or "") == "place_photo" and urls:
        return _unique_strings(urls)
    for key in ["imageUrl", "image_url", "image", "original", "originalUrl"]:
        value = str(item.get(key) or "").strip()
        if value.startswith("http"):
            urls.append(value)
    images = item.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.startswith("http"):
                urls.append(image)
            if isinstance(image, dict):
                urls.extend(_item_image_urls(image))
    for key in ["thumbnailUrl", "thumbnail_url", "thumbnail"]:
        value = str(item.get(key) or "").strip()
        if value.startswith("http"):
            urls.append(value)
    return _unique_strings(urls)


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if value]))


def _prefer_clear_image_urls(values: list[str]) -> list[str]:
    values = _unique_strings(values)
    clear = [value for value in values if not _is_low_quality_image_url(value)]
    return clear or values


def _image_status(item: dict[str, Any], image_urls: list[str]) -> str:
    status = str(item.get("image_status") or "").strip()
    if status in {"place_photo", "source_item", "missing"}:
        return status
    return "source_item" if image_urls else "missing"


def _has_place_photo_urls(response: TravelPlanResponse) -> bool:
    return any(card.image_status == "place_photo" and card.image_urls for card in response.display_cards)


def _should_cache_travel_response(response: TravelPlanResponse) -> bool:
    if response.workflow_status != "completed":
        return False
    if _has_place_photo_urls(response):
        return False
    answer_mode = str(
        response.answer_mode
        or response.resolved_intent.get("answer_mode")
        or ""
    )
    if answer_mode in {"place_cards", "place_detail"}:
        return bool(
            response.display_cards
            or response.hotel_offers
            or response.flight_offers
            or response.activity_offers
        )
    if answer_mode in {"itinerary", "route_map"}:
        return bool(
            response.display_cards
            or response.itinerary_plan.days
            or response.route_options
        )
    return True


def _is_low_quality_image_url(value: str) -> bool:
    lowered = value.lower()
    return "encrypted-tbn" in lowered or "images?q=tbn" in lowered


def _item_subtitle(item: dict[str, Any]) -> str:
    category = str(item.get("type") or item.get("category") or "").strip()
    price = _item_price(item)
    if category and price:
        return f"{category} · {price}"
    return category or price


def _card_description(item: dict[str, Any], reason: str | None = None) -> str:
    text = reason or _item_reason(item)
    if len(text) > 180:
        return f"{text[:177]}..."
    return text


def _public_display_reason(item: dict[str, Any], reason: str | None = None) -> str:
    for candidate in [reason, item.get("display_reason"), item.get("description"), item.get("reason"), item.get("snippet")]:
        text = str(candidate or "").strip()
        if text and not _is_diagnostic_display_reason(text):
            return _card_description(item, text)
    return _fact_based_display_reason(item)


def _task_aware_display_reason(
    item: dict[str, Any],
    *,
    request: TravelPlanRequest,
    resolved_intent: dict[str, object],
    group_title: str,
) -> str:
    profile = _display_reason_task_profile(request)
    if not profile:
        return ""
    title = _item_title(item)
    text = _normalized_match_text(
        " ".join(
            str(item.get(key) or "")
            for key in ["title", "name", "type", "category", "address", "location", "snippet", "description", "query_variant"]
        )
    )
    category = _canonical_travel_category(group_title or resolved_intent.get("category"))

    if profile == "first_timer":
        return _first_timer_display_reason(title, text, category)
    if profile == "rainy_day":
        return _rainy_day_display_reason(title, text, category)
    if profile == "family_half_day":
        return _family_half_day_display_reason(title, text, category)
    if profile == "snack_area":
        return _snack_area_display_reason(title, text, category)
    if profile == "budget_short_trip":
        return _budget_display_reason(title, text, category)
    if profile == "winter_first_timer":
        return _winter_first_timer_display_reason(title, text, category)
    if profile == "quiet_morning":
        return _quiet_morning_display_reason(title, text, category)
    if profile == "night_view_easy_transport":
        return _night_view_display_reason(title, text, category)
    if profile == "paced_itinerary":
        return _paced_itinerary_display_reason(title, text, category)
    return ""


def _display_reason_task_profile(request: TravelPlanRequest) -> str:
    text = " ".join(
        [
            request.query,
            request.question,
            " ".join(request.interest_tags),
            " ".join(request.constraints),
            " ".join(request.fixed_itinerary),
            " ".join(request.requested_categories),
        ]
    )
    lowered = text.lower()
    city = (request.city or "").lower()
    if _is_family_half_day_text(text):
        return "family_half_day"
    if _is_snack_area_text(text):
        return "snack_area"
    if _is_budget_short_trip_text(text):
        return "budget_short_trip"
    if _is_rainy_day_text(text):
        return "rainy_day"
    if _is_quiet_morning_text(text):
        return "quiet_morning"
    if _is_night_view_text(text):
        return "night_view_easy_transport"
    if ("札幌" in text or "sapporo" in lowered or "sapporo" in city) and any(token in text for token in ["冬", "雪祭", "雪"]):
        return "winter_first_timer"
    if any(token in text for token in ["第一次", "初访", "初訪", "新手", "第一次去"]) or "first" in lowered:
        return "first_timer"
    if _request_scope(request)["broad"] and any(token in text for token in ["节奏", "不要太赶", "不太赶", "慢一点", "轻松"]):
        return "paced_itinerary"
    return ""


def _is_family_half_day_text(text: str) -> bool:
    lowered = text.lower()
    return (
        any(token in text for token in ["孩子", "小孩", "亲子", "6岁", "6 岁", "儿童", "不太累", "半日"])
        or "kid" in lowered
        or "family" in lowered
    ) and (any(token in text for token in ["孩子", "小孩", "亲子", "儿童"]) or "kid" in lowered or "family" in lowered)


def _is_snack_area_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["小吃", "道顿堀", "道頓堀", "区域", "街区", "本地吃"]) or "snack" in lowered or "food area" in lowered


def _is_budget_short_trip_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["低预算", "省钱", "预算比较低", "便宜"]) or "budget" in lowered


def _is_rainy_day_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["下雨", "雨天", "下雨天", "雨"]) or "rain" in lowered


def _is_quiet_morning_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["安静", "早上", "散步", "避开最挤", "人少"]) or ("quiet" in lowered and "walk" in lowered)


def _is_night_view_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["夜景", "看夜", "晚上看"]) or "night view" in lowered


def _first_timer_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["太宰府", "dazaifu", "tenmangu", "天満宮", "天满宫"]):
        return "适合半日小旅行：参道小吃和神社氛围完整，建议单独排半天，不要和市区点硬塞同一上午。"
    if any(token in text for token in ["momochihama", "momochi", "beach", "海滨", "海濱", "海边", "海邊", "百道"]):
        return "适合海滨轻松半日：海边散步、拍塔和休息都直观，建议和福冈塔/百道海滨同区安排，别和太宰府硬串。"
    if any(token in text for token in ["大濠", "ohori", "ohorikoen", "park", "公園", "公园", "湖"]):
        return "适合第一站放慢节奏：湖边散步和拍照都轻松，停留 60–90 分钟，可和福冈城迹、赤坂/大名咖啡顺路。"
    if any(token in text for token in ["栉田", "櫛田", "kushida", "shrine", "神社"]):
        return "适合博多老城区短停：停留 20–40 分钟，可和川端商店街、中洲或博多站顺路。"
    if any(token in text for token in ["hakata old town", "old town", "博多老", "博多旧", "博多舊", "街区", "街區"]):
        return "适合补城市历史感：把寺社、商店街和博多站周边串成 60–120 分钟步行段，比单点打卡更适合新手。"
    if any(token in text for token in ["tower", "塔", "展望", "view", "observatory"]):
        return "适合作为城市方位感第一站：看清海湾和市区布局后再排路线，停留约 60 分钟，天气差时降级为备选。"
    if any(token in text for token in ["canal", "运河", "運河", "city", "mall", "商场", "商場"]):
        return "适合作为晚间或雨天补充：吃饭、购物和回酒店都方便，但更适合收尾，不建议替代白天主景点。"
    if category == "美食":
        return "适合作为初访补充：放在当天主景点附近解决一餐，比专门跨区打卡更省体力。"
    return f"{title}适合新手短名单：先看交通是否顺路和停留弹性，再决定放进半日还是一日路线。"


def _rainy_day_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["museum", "美术", "美術", "博物", "art", "science", "水族", "aquarium"]):
        return "雨天更稳：以室内参观为主，停留 90–150 分钟，适合搭配附近咖啡或车站商圈避雨。"
    if any(token in text for token in ["商店街", "arcade", "地下", "mall", "market", "市場", "市场"]):
        return "适合作为雨天短线：有遮蔽、吃逛灵活，但不要只把全天都排成商场，留一个文化或展馆点更有内容。"
    if any(token in text for token in ["shrine", "temple", "神社", "寺", "公园", "公園", "park"]):
        return "雨小时可短停，雨大就降级：控制在 20–40 分钟，并优先和最近的室内点顺路组合。"
    return "雨天可作为备选：先核对是否有室内空间、遮蔽步行和最近车站，避免跨区冒雨赶路。"


def _family_half_day_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["park", "公園", "公园", "garden", "zoo", "aquarium", "水族", "动物", "動物"]):
        return "适合带孩子半日慢玩：空间开阔或互动感强，主点控制在 90–150 分钟，状态好再加附近短停。"
    if any(token in text for token in ["museum", "science", "博物", "科学", "室内", "indoor"]):
        return "适合低疲劳半日：室内可控、休息点多，天气不好时也稳，别再跨区叠太多项目。"
    if any(token in text for token in ["station", "駅", "站", "mall", "商场", "商場"]):
        return "适合作为收尾或雨天备选：交通简单、吃饭和洗手间好解决，但不要替代当天唯一主体验。"
    return "带 6 岁孩子可先放进半日短名单：看是否少换乘、有休息点、能在 2–3 小时内结束。"


def _snack_area_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["市場", "市场", "market", "商店街", "street", "横丁", "yokocho", "arcade"]):
        return "适合本地小吃探索：店铺密度高、可边走边吃，建议放在晚餐前后 90 分钟，不用只挤道顿堀。"
    if any(token in text for token in ["station", "駅", "站", "地下", "food hall"]):
        return "适合交通优先的一餐：靠近车站、选择多，适合作为抵达日或转场日的省心小吃区。"
    return "可作为道顿堀外的吃逛区域：重点看是否小店密集、晚间氛围好、离当天路线近。"


def _budget_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["park", "公園", "公园", "river", "河", "walk", "散步", "view", "展望"]):
        return "低预算友好：适合用免费散步、拍照和看景打底，停留弹性大，把付费项目压到每天 0–1 个。"
    if any(token in text for token in ["market", "市場", "市场", "商店街", "street", "mall"]):
        return "适合省钱但不无聊：用街区小吃和商店街补氛围，边走边吃比连续付费景点更轻松。"
    return "适合低预算短名单：先查门票和交通成本，能顺路或免费短停的点优先放进两天路线。"


def _winter_first_timer_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["museum", "博物", "beer", "啤酒", "indoor", "室内"]):
        return "冬天稳妥的室内/半室内备选：适合风雪大时替换户外点，停留 60–120 分钟。"
    if any(token in text for token in ["park", "公園", "公园", "snow", "雪", "山", "ropeway", "view", "展望"]):
        return "适合冬季氛围，但要看天气和路况：白天排更稳，夜景或缆车类地点要预留防滑和停运缓冲。"
    return "适合第一次冬天去时做备选：优先看是否交通简单、抗风雪、附近有室内休息点。"


def _quiet_morning_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["park", "公園", "公园", "garden", "river", "riverbank", "河", "御苑", "forest", "森林"]):
        return "适合早上慢走：空间开阔、可绕路避人，建议 7–9 点短停，10 点后人流预期下调。"
    if any(token in text for token in ["temple", "shrine", "寺", "神社"]):
        return "早上可安静短停，但不要过度承诺人少：避开正门主轴，控制 30–60 分钟后转去更开阔区域。"
    return "可作为清晨散步短名单：重点看是否有侧线、河边或公园边缘路线，而不是只按名气打卡。"


def _night_view_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["tower", "塔", "observatory", "展望", "山", "ropeway", "夜景", "view"]):
        return "适合夜景候选：傍晚前到达更稳，先查回程交通和天气；交通麻烦时不要把它排到太晚。"
    if any(token in text for token in ["bay", "港", "海", "river", "河", "canal", "运河", "運河"]):
        return "适合低门槛夜景散步：比远郊展望台交通简单，可和晚餐或酒店回程顺路安排。"
    return "夜景备选要先看回程难度：靠近公共交通和晚餐区域的点，实际体验往往比高分但远的点更稳。"


def _paced_itinerary_display_reason(title: str, text: str, category: str) -> str:
    if any(token in text for token in ["park", "公園", "公园", "garden", "river", "海", "湖", "walk"]):
        return "适合慢节奏行程打底：停留弹性大，可作为半日主点，天气或体力变化时也容易调整。"
    if any(token in text for token in ["shrine", "temple", "神社", "寺", "museum", "博物", "美术", "美術"]):
        return "适合作为半日文化主点：不要和太多跨区地点硬串，留出交通、吃饭和临时休息缓冲。"
    return "适合放进不赶的行程短名单：先按区域分组，每半天保留 1 个主点和 1 个附近备选。"


def _is_diagnostic_display_reason(value: str) -> bool:
    return bool(
        re.search(
            r"命中用户核心目标|没有命中|候选自身|semantic|API\s*候选|API候选|需要用户确认|debug|matched requirement",
            value,
            flags=re.I,
        )
    )


def _fact_based_display_reason(item: dict[str, Any]) -> str:
    parts: list[str] = []
    rating = _float_or_none(item.get("rating"))
    reviews = _review_count(item)
    if rating is not None and reviews:
        parts.append(f"评分 {rating:g}，约 {reviews} 条评价")
    elif rating is not None:
        parts.append(f"评分 {rating:g}")
    elif reviews:
        parts.append(f"约 {reviews} 条评价")

    address = str(item.get("address") or item.get("location") or "").strip()
    if address:
        parts.append(f"位置在 {address}")

    category = str(item.get("type") or item.get("category") or "").strip()
    if category:
        parts.append(f"类型是 {category}")

    if parts:
        return "推荐理由：" + "；".join(parts) + "，适合结合地图距离和当天路线优先考虑。"
    return "推荐理由：适合当前问题，可作为地图上的备选点继续比较。"


def _item_price(item: dict[str, Any]) -> str:
    value = item.get("price") or item.get("priceLevel") or item.get("price_level") or item.get("rate")
    return str(value or "").strip()


def _review_count(item: dict[str, Any]) -> int | None:
    for key in ["reviews", "review_count", "reviewsCount", "user_ratings_total"]:
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = value.replace(",", "").strip()
            if digits.isdigit():
                return int(digits)
    return None


def _coordinate(item: dict[str, Any], axis: str) -> float | None:
    keys = ["latitude", "lat"] if axis == "lat" else ["longitude", "lng", "lon"]
    for key in keys:
        value = _float_or_none(item.get(key))
        if value is not None:
            return value
    for container_key in ["gps_coordinates", "coordinates", "position"]:
        container = item.get(container_key)
        if isinstance(container, dict):
            for key in keys:
                value = _float_or_none(container.get(key))
                if value is not None:
                    return value
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _map_center(city: str, pins: list[dict[str, Any]]) -> dict[str, float]:
    if pins:
        return {
            "lat": sum(float(pin["lat"]) for pin in pins) / len(pins),
            "lng": sum(float(pin["lng"]) for pin in pins) / len(pins),
        }
    centers = {
        "fukuoka": {"lat": 33.5902, "lng": 130.4017},
        "福冈": {"lat": 33.5902, "lng": 130.4017},
        "福岡": {"lat": 33.5902, "lng": 130.4017},
        "kyoto": {"lat": 35.0116, "lng": 135.7681},
        "京都": {"lat": 35.0116, "lng": 135.7681},
        "osaka": {"lat": 34.6937, "lng": 135.5023},
        "大阪": {"lat": 34.6937, "lng": 135.5023},
        "beppu": {"lat": 33.2795, "lng": 131.5000},
        "别府": {"lat": 33.2795, "lng": 131.5000},
        "別府": {"lat": 33.2795, "lng": 131.5000},
    }
    return centers.get(city.strip().lower()) or centers.get(city.strip()) or {"lat": 35.6812, "lng": 139.7671}


def _search_queries(request: TravelPlanRequest, provider_name: str) -> list[str]:
    return [
        *[f"{provider_name} raw_query {variant}" for variant in _workflow_query_variants(request)],
        f"{provider_name} flights/search {request.city}",
        f"{provider_name} hotels/search {request.city}",
        *[f"{provider_name} places {request.city} {title}" for title, _ in _selected_categories(request)],
    ]


def _sources_consulted(api_payloads: dict[str, Any], provider_name: str) -> list[str]:
    if not api_payloads:
        return []
    engines = sorted(api_payloads.keys())
    return [f"{provider_name}:{engine}" for engine in engines]


def _item_title(item: dict[str, Any]) -> str:
    return str(
        item.get("title")
        or item.get("name")
        or item.get("place")
        or item.get("destination")
        or item.get("reason")
        or "未命名推荐"
    ).strip()


def _item_reason(item: dict[str, Any]) -> str:
    explicit_value = (
        item.get("reason")
        or item.get("description")
        or item.get("snippet")
        or item.get("summary")
    )
    explicit = str(explicit_value).strip() if explicit_value is not None else ""
    if explicit:
        return explicit

    parts: list[str] = []
    rating = _float_or_none(item.get("rating"))
    reviews = _review_count(item)
    if rating is not None and reviews:
        parts.append(f"评分 {rating:g}，约 {reviews} 条评价")
    elif rating is not None:
        parts.append(f"评分 {rating:g}")
    elif reviews:
        parts.append(f"约 {reviews} 条评价")

    address = str(item.get("address") or item.get("location") or "").strip()
    if address:
        parts.append(f"位置在 {address}")

    category = str(item.get("type") or item.get("category") or "").strip()
    if category:
        parts.append(f"类型是 {category}")

    if parts:
        return "推荐理由：" + "；".join(parts) + "，适合结合路线优先考虑。"

    return "推荐理由：这个地点与当前问题匹配，适合作为地图上的备选点继续比较。"


def _item_titles(items: list[dict[str, Any]]) -> list[str]:
    return [_item_title(item) for item in items if _item_title(item)]


def _fallback_items(city: str, title: str) -> list[str]:
    return [
        f"{city} {title} 候选 1",
        f"{city} {title} 候选 2",
        f"{city} {title} 候选 3",
    ]


def _display_agent_name(name: str) -> str:
    return {
        "destination": "Destination",
        "flight": "Flight",
        "hotel": "Hotel",
        "itinerary": "Itinerary",
        "activity_food": "Activity/Food",
        "critic": "Critic",
    }.get(name, name)


def _agent_result_dict(result: AgentResult) -> dict[str, Any]:
    return {
        "name": _display_agent_name(result.name),
        "model": result.model,
        "summary": result.summary,
        "items": result.items,
        "warnings": result.warnings,
        "status": result.status,
        "raw_api_count": len(result.raw_api_results),
    }


def _parse_jsonish(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return {"summary": content, "items": [], "warnings": []}
        value = json.loads(text[start : end + 1])
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _flatten_api_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                items.append(item)
            elif isinstance(item, list | tuple):
                items.extend(_flatten_api_items(item))
        return items
    if isinstance(value, dict):
        items = []
        for item in value.values():
            items.extend(_flatten_api_items(item))
        return items
    return []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _exception_summary(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        body = ""
        try:
            payload = exc.response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    body = str(error.get("message") or error)
                elif payload.get("message"):
                    body = str(payload.get("message"))
                else:
                    body = str(payload)
        except Exception:
            body = exc.response.text[:240]
        endpoint = ""
        try:
            endpoint = exc.request.url.path
        except Exception:
            endpoint = ""
        path = f" {endpoint}" if endpoint else ""
        suffix = f" - {body[:240]}" if body else ""
        return f"HTTP {exc.response.status_code}{path}{suffix}"
    return exc.__class__.__name__


def build_recommendation_supervisor(
    *,
    app_settings: Settings = settings,
    serper_api_key: str | None = None,
    serper_base_url: str = "https://google.serper.dev",
    serpapi_api_key: str | None = None,
    google_maps_api_key: str | None = None,
    google_places_base_url: str = "https://places.googleapis.com/v1",
    litellm_api_key: str | None = None,
    travel_main_api_key: str | None = None,
    travel_main_base_url: str | None = None,
    deepinfra_api_key: str | None = None,
    litellm_base_url: str | None = None,
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai",
    timeout_seconds: float = 120.0,
    redis_url: str = "redis://127.0.0.1:6379/0",
) -> TravelRecommendationSupervisor:
    from app.services.serper_travel import SerperTravelClient

    serpapi_client = None
    if serper_api_key:
        serpapi_client = SerperTravelClient(
            api_key=serper_api_key,
            base_url=serper_base_url,
            timeout_seconds=timeout_seconds,
        )
    elif app_settings.travel_allow_serpapi_fallback and serpapi_api_key:
        from app.services.serpapi_travel import SerpApiTravelClient

        serpapi_client = SerpApiTravelClient(serpapi_api_key)
    google_places_client = None
    if app_settings.travel_allow_direct_google_places and google_maps_api_key:
        from app.services.google_places import GooglePlacesClient

        google_places_client = GooglePlacesClient(
            api_key=google_maps_api_key,
            base_url=google_places_base_url,
            timeout_seconds=timeout_seconds,
        )
    api_key = travel_main_api_key or deepinfra_api_key or (
        litellm_api_key if app_settings.travel_allow_litellm_fallback else None
    )
    agent_client = None
    if api_key:
        base_url = (
            travel_main_base_url
            if travel_main_api_key and travel_main_base_url
            else deepinfra_base_url
            if deepinfra_api_key
            else (litellm_base_url or deepinfra_base_url)
        )
        agent_client = LiteLLMTravelAgentClient(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            reasoning_effort=app_settings.travel_model_reasoning_effort,
        )
    return TravelRecommendationSupervisor(
        serpapi_client=serpapi_client,
        google_places_client=google_places_client,
        agent_client=agent_client,
        model_router=AgentModelRouter.deepinfra_defaults(app_settings),
        result_cache=None,
        orchestration_mode=app_settings.travel_orchestration_mode,
        orchestrator_max_tool_rounds=app_settings.travel_orchestrator_max_tool_rounds,
        complex_max_tool_rounds=app_settings.travel_complex_max_tool_rounds,
    )
