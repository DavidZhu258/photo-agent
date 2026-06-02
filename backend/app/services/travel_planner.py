from __future__ import annotations

import hashlib
import json

from app.schemas.travel import (
    TravelPlanRequest,
    TravelPlanResponse,
    TravelRecommendation,
    TravelSuggestionGroup,
)
from app.config import Settings, settings
from app.schemas.visual import EvidenceCard, PlaceCandidate
from app.services.place_catalog import SeedPlaceCatalog
from app.services.exa_search import EvidenceSearchService, ExaSearchClient
from app.services.routing import RouteEstimate, RouteEstimator
from app.services.travel_api_sources import TabijiClient, TrustedTravelSuggestionService
from app.services.travel_reasoning import DeepInfraTravelDecisionClient
from app.services.travel_query_understanding import TravelModelCallError
from app.services.travel_recommendation_supervisor import (
    TravelRecommendationSupervisor,
    build_recommendation_supervisor,
)
from app.services.cache import RedisJsonCache
from app.services.open_source_stack import (
    TRAVEL_COMMERCIAL_DISCLOSURE,
    cache_info,
    provider_refs,
    source_breakdown,
    travel_sources,
    travel_trace_steps,
)


class LightweightTravelPlanner:
    """Deterministic P0 planner focused on transparent evidence-backed decisions."""

    def __init__(
        self,
        place_catalog: SeedPlaceCatalog | None = None,
        decision_client: object | None = None,
        evidence_search: object | None = None,
        suggestion_service: object | None = None,
        route_estimator: RouteEstimator | None = None,
        result_cache: object | None = None,
    ) -> None:
        self.place_catalog = place_catalog or SeedPlaceCatalog()
        self.decision_client = decision_client
        self.evidence_search = evidence_search
        self.suggestion_service = suggestion_service
        self.route_estimator = route_estimator or RouteEstimator()
        self.result_cache = result_cache

    async def plan(self, request: TravelPlanRequest) -> TravelPlanResponse:
        request_cache_key = self._request_cache_key(request)
        if self.result_cache is not None:
            cached = await self.result_cache.get(request_cache_key)
            if cached is not None:
                cache = cache_info("travel", request_cache_key, hit=True)
                return cached.model_copy(
                    update={
                        "cache": cache,
                        "thinking_steps": travel_trace_steps(
                            llm_used=cached.llm_used,
                            model_used=cached.model_used,
                            suggestion_source=cached.suggestion_source,
                            search_used=cached.search_used,
                            cache_hit=True,
                        ),
                    }
                )
        candidates = await self.place_catalog.search(
            query=request.query or request.question,
            city=request.city,
            interest_tags=request.interest_tags,
        )
        if len(candidates) < 2:
            known_places = await self.place_catalog.list_places(city=request.city)
            seen = {place.place_id for place in candidates}
            candidates.extend(
                place
                for place in known_places
                if place.place_id not in seen
            )
        suggestion_groups = self._broad_suggestion_groups(request)
        suggestion_source = "fallback" if suggestion_groups else "none"
        suggestion_owner = self.suggestion_service or self.evidence_search
        if suggestion_groups and request.allow_web_search and suggestion_owner is not None:
            suggestion_provider = getattr(suggestion_owner, "suggestion_groups", None)
            if callable(suggestion_provider):
                try:
                    api_groups = await suggestion_provider(request, suggestion_groups)
                    if api_groups:
                        suggestion_groups = api_groups
                        suggestion_source = str(
                            getattr(suggestion_owner, "source_name", "api")
                        )
                except Exception:
                    suggestion_source = "fallback"
        evidence_by_place_id: dict[int | None, list[EvidenceCard]] = {}
        for place in candidates:
            evidence_by_place_id[place.place_id] = await self.place_catalog.evidence_for(
                place.place_id
            )
        search_meta = {
            "search_used": False,
            "search_queries": [],
            "sources_consulted": [],
            "data_gaps": [],
            "evidence_freshness": "seed",
            "candidates": [],
        }
        if await self._should_search(request, candidates, evidence_by_place_id):
            search_meta = await self.evidence_search.search(
                request,
                trigger_reason=self._search_trigger_reason(
                    request,
                    candidates,
                    evidence_by_place_id,
                ),
            )
            for search_candidate in search_meta.get("candidates", []):
                place = search_candidate.get("place")
                evidence = search_candidate.get("evidence_cards", [])
                if isinstance(place, PlaceCandidate):
                    candidates.append(place)
                    evidence_by_place_id[place.place_id] = [
                        card for card in evidence if isinstance(card, EvidenceCard)
                    ]
        recommendations = []
        route_warnings = []
        for place in candidates:
            evidence = evidence_by_place_id.get(place.place_id)
            if evidence is None:
                evidence = await self.place_catalog.evidence_for(place.place_id)
            route_estimate = await self.route_estimator.estimate(
                request.current_location,
                place,
                request.transport_mode,
            )
            if route_estimate.warning:
                route_warnings.append(route_estimate.warning)
            recommendations.append(
                self._recommendation_for(place, evidence, request, route_estimate)
            )
        recommendations.sort(key=lambda item: item.score, reverse=True)
        top = recommendations[: max(1, request.max_results)]
        notes = [
            "最终决策仍由用户确认；这里只按兴趣、证据、本地信号、可执行性和拥挤风险排序。",
            "无证据或低置信度地点会被明确标记，避免把信息缺口包装成确定结论。",
        ]
        data_gaps = list(search_meta.get("data_gaps") or [])
        evidence_optional = bool(suggestion_groups) and not _needs_evidence(request)
        if not recommendations and not evidence_optional:
            data_gaps.append("证据不足：本地库没有足够 POI 或真实评价。")
        elif recommendations and not any(item.evidence_cards for item in recommendations):
            data_gaps.append("证据不足：候选地点缺少可审计来源。")
        uncertainty = []
        if request.arrive_at is not None:
            notes.append(f"到达时间已纳入判断：{request.arrive_at.isoformat()}")
        if request.fixed_itinerary:
            notes.append("已定行程：" + "；".join(request.fixed_itinerary))
        summary = "透明推荐：优先给出信息完整、证据清楚、符合兴趣且不过热的地点。"
        if suggestion_groups:
            summary = (
                "全方位建议：先按美食、历史文化、本地体验、购物街区和自然摄影分组，"
                "每组给 3-5 个方向；有证据的 POI 会另行进入推荐卡。"
            )
        needs_user_confirmation = not top or any(
            not item.evidence_cards for item in top[:1]
        ) or bool(data_gaps)
        llm_used = False
        model_used = "deterministic"
        reasoning_mode = "deterministic_ranker"

        if self.decision_client is not None and top:
            try:
                decision = await self.decision_client.decide(
                    request,
                    top,
                    suggestion_groups=suggestion_groups,
                )
                self._apply_model_decision(top, decision)
                summary = decision.get("summary") or summary
                notes = decision.get("decision_notes") or notes
                uncertainty = decision.get("uncertainty") or uncertainty
                needs_user_confirmation = bool(
                    decision.get("needs_user_confirmation", needs_user_confirmation)
                )
                llm_used = True
                model_used = str(getattr(self.decision_client, "model", "llm"))
                reasoning_mode = "deterministic_ranker+llm_decision"
            except Exception as exc:
                raise TravelModelCallError(
                    "travel_decision",
                    exc.__class__.__name__,
                    model=str(getattr(self.decision_client, "model", "llm")),
                ) from exc
        not_recommended = [
            item for item in top if item.decision == "not_recommended"
        ]
        conditional_options = [
            item for item in top if item.decision == "conditional"
        ]
        evidence_cards = [
            card
            for item in top
            for card in item.evidence_cards
        ]
        route_used = any(item.route_minutes is not None for item in recommendations)
        api_sources = travel_sources()
        cache = cache_info("travel", request_cache_key)
        response = TravelPlanResponse(
            summary=summary,
            recommendations=top,
            not_recommended=not_recommended,
            conditional_options=conditional_options,
            excluded_candidates=[],
            decision_notes=notes,
            uncertainty=uncertainty,
            evidence_cards=evidence_cards,
            pros=[reason for item in top for reason in item.pros],
            cons=[reason for item in top for reason in item.cons],
            route_summary={
                "used": route_used,
                "source": self.route_estimator.osrm_base_url and "osrm" or "haversine",
                "warnings": route_warnings,
            },
            suggestion_groups=suggestion_groups,
            category_groups=suggestion_groups,
            suggestion_source=suggestion_source,
            api_sources_used=api_sources,
            source_breakdown=source_breakdown(api_sources),
            commercial_disclosure=TRAVEL_COMMERCIAL_DISCLOSURE,
            raw_provider_refs=provider_refs("travel"),
            thinking_steps=travel_trace_steps(
                llm_used=llm_used,
                model_used=model_used,
                suggestion_source=suggestion_source,
                search_used=bool(search_meta.get("search_used")),
                cache_hit=cache.hit,
            ),
            cache=cache,
            search_used=bool(search_meta.get("search_used")),
            search_queries=list(search_meta.get("search_queries") or []),
            sources_consulted=list(search_meta.get("sources_consulted") or []),
            data_gaps=data_gaps,
            evidence_freshness=str(search_meta.get("evidence_freshness") or "seed"),
            llm_used=llm_used,
            model_used=model_used,
            reasoning_mode=reasoning_mode,
            needs_user_confirmation=needs_user_confirmation,
        )
        if self.result_cache is not None:
            await self.result_cache.put(request_cache_key, response)
        return response

    @staticmethod
    def _request_cache_key(request: TravelPlanRequest) -> str:
        payload = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _broad_suggestion_groups(
        request: TravelPlanRequest,
    ) -> list[TravelSuggestionGroup]:
        if request.interest_tags or request.constraints or request.avoid:
            return []
        text = f"{request.query} {request.question}".strip()
        if _has_specific_intent(text):
            return []
        city = request.city or "当地"
        return [
            TravelSuggestionGroup(
                title="美食",
                intent="先找本地人和游客都反复认可的吃法，再补充预约、排队和价格信息。",
                items=[
                    f"{city} 本地人常去的早餐/午餐",
                    f"{city} 特色小吃或老店",
                    f"{city} 晚上适合轻松体验的餐饮街区",
                    f"{city} 需要预约或排队但值得确认的店",
                ],
                reason="吃饭建议要同时说明口味、排队、价格和是否适合你的行程节奏。",
            ),
            TravelSuggestionGroup(
                title="购物",
                intent="先判断什么值得买、在哪里买、是否比游客店更可靠。",
                items=[
                    f"{city} 特色伴手礼和食品",
                    f"{city} 在地品牌或设计小物",
                    f"{city} 药妆、生活用品或实用采购",
                    f"{city} 需要避开的游客溢价购物点",
                ],
                reason="购物本身可替代性强，必须说明值得买的理由和避坑点。",
            ),
            TravelSuggestionGroup(
                title="历史文化",
                intent="找真正有故事和现场感的地点，而不是只看热门排名。",
                items=[
                    f"{city} 历史遗迹",
                    f"{city} 小众寺社/纪念馆",
                    f"{city} 老街、町屋或传统街区",
                    f"{city} 与当地身份有关的地标",
                ],
                reason="文化类地点要看背景、争议和是否名副其实。",
            ),
            TravelSuggestionGroup(
                title="本地体验",
                intent="优先找当地生活感、季节性和可参与的体验。",
                items=[
                    f"{city} 市场或商店街",
                    f"{city} 当地节庆/展览/临时活动",
                    f"{city} 手作、温泉、茶、酒或工艺体验",
                    f"{city} 本地人评价高但游客榜单少的区域",
                ],
                reason="体验类推荐要补足参与方式、季节性、预约和现场反馈。",
            ),
            TravelSuggestionGroup(
                title="购物与街区",
                intent="按值得逛、值得买、是否游客化来分层。",
                items=[
                    f"{city} 特色伴手礼",
                    f"{city} 独立店/古着/杂货",
                    f"{city} 适合雨天或晚上逛的街区",
                    f"{city} 不建议专门绕路的商业点",
                ],
                reason="购物建议要明确是不是可替代，以及是否值得占用行程时间。",
            ),
            TravelSuggestionGroup(
                title="自然与摄影",
                intent="判断时间、光线、路线成本和现场拥挤程度。",
                items=[
                    f"{city} 适合日落或夜景的位置",
                    f"{city} 适合短途散步的自然点",
                    f"{city} 需要体力/交通成本评估的山海景点",
                    f"{city} 拍照好但可能过热的打卡点",
                ],
                reason="自然和摄影点必须结合到达时间，否则很容易推荐不可执行路线。",
            ),
        ]

    def _recommendation_for(
        self,
        place: PlaceCandidate,
        evidence: list[EvidenceCard],
        request: TravelPlanRequest,
        route_estimate: RouteEstimate | None = None,
    ) -> TravelRecommendation:
        wanted = {tag.strip().lower() for tag in request.interest_tags if tag.strip()}
        place_tags = {tag.lower() for tag in place.tags}
        matched = sorted(wanted.intersection(place_tags))
        average_evidence = (
            sum(card.score for card in evidence) / len(evidence) if evidence else 0.0
        )
        local_signal = max((card.local_signal for card in evidence), default=0.0)
        tourist_signal = max((card.tourist_signal for card in evidence), default=0.0)
        ad_risk = max((card.ad_risk for card in evidence), default=0.0)
        avoid_crowds = any(
            "crowd" in item.lower() or "游客" in item or "人" in item
            for item in request.constraints + [request.question]
        )
        score = (
            len(matched) * 0.25
            + average_evidence * 0.35
            + local_signal * 0.2
            + place.photo_potential * 0.15
            - ad_risk * 0.2
        )
        if avoid_crowds:
            score -= tourist_signal * 0.2
        route_warning = None
        if route_estimate and route_estimate.used and route_estimate.minutes is not None:
            if self._route_time_conflicts(request, place, route_estimate.minutes):
                score -= 0.45
                route_warning = (
                    f"路线/时间不合适：预计单程约 {route_estimate.minutes:.0f} 分钟，"
                    "到达时间偏晚。"
                )
        reasons = []
        if matched:
            reasons.append("兴趣匹配：" + "、".join(matched))
        if evidence:
            reasons.append(f"证据强度 {average_evidence:.2f}")
        if local_signal:
            reasons.append(f"本地/深度游信号 {local_signal:.2f}")
        if route_estimate and route_estimate.used and route_estimate.minutes is not None:
            reasons.append(f"路线时间约 {route_estimate.minutes:.0f} 分钟")
        decision = self._deterministic_decision(
            has_evidence=bool(evidence),
            score=score,
            ad_risk=ad_risk,
            tourist_signal=tourist_signal,
            avoid_crowds=avoid_crowds,
            route_warning=route_warning,
        )
        pros = []
        cons = []
        if matched:
            pros.append("符合兴趣：" + "、".join(matched))
        if local_signal >= 0.55:
            pros.append("有本地/深度游信号")
        if average_evidence >= 0.75:
            pros.append("证据强度较高")
        if tourist_signal >= 0.75:
            cons.append("游客热度高")
        if ad_risk >= 0.12:
            cons.append("来源商业化程度偏高")
        if not evidence:
            cons.append("证据不足")
        if route_warning:
            cons.append(route_warning)
        caution = (
            "游客热度高，建议错峰或作为备选。"
            if tourist_signal >= 0.75
            else "当前证据未显示明显过热。"
        )
        if route_warning:
            caution = "不建议把它作为当前时段主目的地，除非你能提前到达或改天安排。"
        return TravelRecommendation(
            place=place,
            score=round(score, 3),
            reasons=reasons or ["证据不足，需要补充来源"],
            caution=caution,
            ad_risk_label=self._ad_risk_label(ad_risk),
            evidence_cards=evidence,
            decision=decision,
            decision_reason=self._decision_reason(decision),
            pros=pros or ["算法认为可作为候选，但需要更多个人偏好确认"],
            cons=cons,
            evidence_confidence=self._evidence_confidence(average_evidence, evidence),
            route_minutes=(
                route_estimate.minutes
                if route_estimate and route_estimate.used
                else None
            ),
            route_warning=route_warning,
        )

    async def _should_search(
        self,
        request: TravelPlanRequest,
        candidates: list[PlaceCandidate],
        evidence_by_place_id: dict[int | None, list[EvidenceCard]],
    ) -> bool:
        if self.evidence_search is None:
            return False
        if not request.allow_web_search or request.evidence_refresh == "cache_only":
            return False
        if request.evidence_refresh == "force":
            return _needs_evidence(request)
        if self._broad_suggestion_groups(request) and not _needs_evidence(request):
            return False
        evidence_count = sum(len(cards) for cards in evidence_by_place_id.values())
        return len(candidates) < 3 or evidence_count < 3

    @staticmethod
    def _search_trigger_reason(
        request: TravelPlanRequest,
        candidates: list[PlaceCandidate],
        evidence_by_place_id: dict[int | None, list[EvidenceCard]],
    ) -> str:
        if request.evidence_refresh == "force":
            return "forced_refresh"
        evidence_count = sum(len(cards) for cards in evidence_by_place_id.values())
        if not candidates:
            return "no_local_candidates"
        if len(candidates) < 3:
            return "few_local_candidates"
        if evidence_count < 3:
            return "insufficient_local_evidence"
        return "auto"

    @staticmethod
    def _route_time_conflicts(
        request: TravelPlanRequest,
        place: PlaceCandidate,
        route_minutes: float,
    ) -> bool:
        text = " ".join(
            [request.query, request.question, place.category, *place.tags]
        ).lower()
        is_hike = any(
            token in text for token in ["hike", "mountain", "trail", "爬山", "登山", "山"]
        )
        late_arrival = request.arrive_at is not None and request.arrive_at.hour >= 15
        return (is_hike and late_arrival and route_minutes >= 30) or route_minutes >= 120

    @staticmethod
    def _apply_model_decision(
        recommendations: list[TravelRecommendation],
        decision: dict,
    ) -> None:
        by_id = {
            item.place.place_id: item
            for item in recommendations
            if item.place.place_id is not None
        }
        by_name = {item.place.name: item for item in recommendations}
        for item in decision.get("recommendations") or []:
            if not isinstance(item, dict):
                continue
            recommendation = by_id.get(item.get("place_id")) or by_name.get(
                item.get("place_name") or item.get("name")
            )
            if recommendation is None:
                continue
            if item.get("decision"):
                recommendation.decision = str(item["decision"])
            if item.get("decision_reason"):
                recommendation.decision_reason = str(item["decision_reason"])
            if item.get("pros"):
                recommendation.pros = [str(value) for value in item["pros"]]
            if item.get("cons"):
                recommendation.cons = [str(value) for value in item["cons"]]
            if item.get("caution"):
                recommendation.caution = str(item["caution"])

    @staticmethod
    def _deterministic_decision(
        *,
        has_evidence: bool,
        score: float,
        ad_risk: float,
        tourist_signal: float,
        avoid_crowds: bool,
        route_warning: str | None = None,
    ) -> str:
        if not has_evidence:
            return "insufficient_evidence"
        if route_warning:
            return "not_recommended"
        if ad_risk >= 0.35 or (avoid_crowds and tourist_signal >= 0.75):
            return "not_recommended"
        if score >= 0.65:
            return "recommended"
        return "conditional"

    @staticmethod
    def _decision_reason(decision: str) -> str:
        return {
            "recommended": "证据、兴趣匹配和风险信号支持推荐。",
            "conditional": "可以考虑，但需要结合时间、路线和个人偏好确认。",
            "not_recommended": "与当前约束或风险信号冲突，不建议作为主选择。",
            "insufficient_evidence": "证据不足，不能负责任地推荐。",
        }[decision]

    @staticmethod
    def _evidence_confidence(
        average_evidence: float,
        evidence: list[EvidenceCard],
    ) -> str:
        if not evidence:
            return "low"
        if average_evidence >= 0.8 and len(evidence) >= 2:
            return "high"
        if average_evidence >= 0.6:
            return "medium"
        return "low"

    @staticmethod
    def _ad_risk_label(value: float) -> str:
        if value >= 0.35:
            return "高"
        if value >= 0.12:
            return "中"
        return "低"


def _has_specific_intent(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    specific_markers = [
        "几点",
        "是否",
        "能不能",
        "爬山",
        "预约",
        "排队",
        "只想",
        "不要",
        "避开",
        "avoid",
        "hike",
        "restaurant",
        "temple",
        "museum",
    ]
    return any(marker in lowered for marker in specific_markers)


def _needs_evidence(request: TravelPlanRequest) -> bool:
    text = " ".join(
        [
            request.query,
            request.question,
            " ".join(request.interest_tags),
            " ".join(request.constraints),
            " ".join(request.avoid),
        ]
    ).lower()
    evidence_markers = [
        "真实",
        "评价",
        "值得",
        "推荐",
        "不建议",
        "避雷",
        "本地人",
        "游客",
        "广告",
        "商单",
        "reddit",
        "review",
        "overhyped",
        "local",
        "worth",
        "avoid",
    ]
    if request.interest_tags or request.constraints or request.avoid:
        return True
    return any(marker in text for marker in evidence_markers)


def build_travel_planner(
    app_settings: Settings = settings,
    place_catalog: SeedPlaceCatalog | None = None,
    evidence_search: object | None = None,
    suggestion_service: object | None = None,
) -> LightweightTravelPlanner | TravelRecommendationSupervisor:
    if (
        app_settings.travel_main_api_key
        or
        app_settings.deepinfra_api_key
        or (
            app_settings.travel_allow_litellm_fallback
            and app_settings.litellm_base_url
        )
    ):
        return build_recommendation_supervisor(
            app_settings=app_settings,
            serper_api_key=app_settings.serper_api_key,
            serper_base_url=app_settings.serper_base_url,
            serpapi_api_key=app_settings.serpapi_api_key,
            google_maps_api_key=app_settings.google_maps_api_key,
            google_places_base_url=app_settings.google_places_base_url,
            litellm_api_key=app_settings.litellm_api_key,
            travel_main_api_key=app_settings.travel_main_api_key,
            travel_main_base_url=app_settings.travel_main_base_url,
            deepinfra_api_key=app_settings.deepinfra_api_key,
            litellm_base_url=app_settings.litellm_base_url,
            deepinfra_base_url=app_settings.deepinfra_base_url,
            timeout_seconds=app_settings.travel_decision_timeout_seconds,
            redis_url=app_settings.redis_url,
        )
    decision_client = None
    if (
        app_settings.vlm_provider.lower() == "deepinfra"
        and app_settings.deepinfra_api_key
    ):
        decision_client = DeepInfraTravelDecisionClient(
            api_key=app_settings.deepinfra_api_key,
            model=app_settings.travel_decision_model,
            base_url=app_settings.deepinfra_base_url,
            timeout_seconds=app_settings.travel_decision_timeout_seconds,
            reasoning_effort=app_settings.travel_model_reasoning_effort,
        )
    if evidence_search is None and app_settings.exa_api_key:
        evidence_search = EvidenceSearchService(
            ExaSearchClient(
                api_key=app_settings.exa_api_key,
                base_url=app_settings.exa_base_url,
                timeout_seconds=app_settings.exa_timeout_seconds,
            )
        )
    if suggestion_service is None and app_settings.tabiji_enabled:
        suggestion_service = TrustedTravelSuggestionService(
            tabiji_client=TabijiClient(
                base_url=app_settings.tabiji_base_url,
                timeout_seconds=app_settings.tabiji_timeout_seconds,
            ),
            fallback_service=evidence_search,
        )
    return LightweightTravelPlanner(
        place_catalog=place_catalog,
        decision_client=decision_client,
        evidence_search=evidence_search,
        suggestion_service=suggestion_service,
        route_estimator=RouteEstimator(
            osrm_base_url=app_settings.osrm_base_url,
            timeout_seconds=app_settings.osrm_timeout_seconds,
        ),
        result_cache=RedisJsonCache(
            app_settings.redis_url,
            TravelPlanResponse,
            namespace="travel:plan",
        ),
    )
