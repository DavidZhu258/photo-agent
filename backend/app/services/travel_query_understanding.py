from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.schemas.travel import TravelPlanRequest


AnswerMode = Literal["answer_only", "place_detail", "place_cards", "itinerary", "route_map"]


class TravelModelCallError(RuntimeError):
    def __init__(self, stage: str, message: str, *, model: str = "") -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.model = model
        self.message = message


class TravelToolTask(BaseModel):
    task_id: str
    capability: str
    query: str = ""
    required: bool = True


class TravelAgentTask(BaseModel):
    task_id: str
    agent_role: str
    objective: str = ""
    input_keys: list[str] = Field(default_factory=list)
    required: bool = True


class TravelAnswerContract(BaseModel):
    needs_map: bool = False
    needs_cards: bool = False
    needs_itinerary: bool = False
    needs_inventory: bool = False
    response_style: str = "narrative"


class TravelCapabilityPlan(BaseModel):
    user_goal: str = ""
    intent_kind: str = "travel_question"
    required_capabilities: list[str] = Field(default_factory=list)
    tool_tasks: list[TravelToolTask] = Field(default_factory=list)
    agent_tasks: list[TravelAgentTask] = Field(default_factory=list)
    answer_contract: TravelAnswerContract = Field(default_factory=TravelAnswerContract)
    confidence: float = 0.6


class TravelIntent(BaseModel):
    task_type: str = "place_recommendation"
    answer_mode: AnswerMode = "place_cards"
    requires_place: bool = True
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
    destination: str = ""
    category: str = ""
    target_entity: str = ""
    target_type: str = ""
    requested_outputs: list[str] = Field(default_factory=list)
    need_supplier_types: list[str] = Field(default_factory=list)
    must_answer: list[str] = Field(default_factory=list)
    should_not_answer: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    capability_plan: TravelCapabilityPlan = Field(default_factory=TravelCapabilityPlan)
    confidence: float = 0.6
    clarifying_question: str = ""


class SearchPlan(BaseModel):
    should_search: bool = True
    tools: list[str] = Field(default_factory=list)
    query_variants: list[str] = Field(default_factory=list)
    locale: str = "auto"
    must_satisfy: list[str] = Field(default_factory=list)
    exclude_types: list[str] = Field(default_factory=list)


class CandidateDocument(BaseModel):
    candidate_id: str
    title: str = ""
    snippet: str = ""
    address: str = ""
    type: str = ""
    category: str = ""
    query_variant: str = ""
    source_key: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class CandidateVerdict(BaseModel):
    candidate_id: str
    is_relevant: bool = True
    relevance_score: int = 50
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    match_reason: str = ""


class TripPlanDraft(BaseModel):
    intent_summary: str = ""
    answer_strategy: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    skipped_capabilities: list[str] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    followup_slots: list[str] = Field(default_factory=list)
    confidence: float = 0.6


async def understand_travel_query(
    *,
    request: TravelPlanRequest,
    agent_client: object | None,
    model: str,
) -> TravelIntent:
    runner = getattr(agent_client, "run_agent", None)
    if not callable(runner):
        raise TravelModelCallError("query_understanding", "agent client unavailable", model=model)
    try:
        result = await runner(
            agent_name="query_understanding",
            model=model,
            prompt=(
                "Parse the user's travel request into strict JSON. Prefer a generalized "
                "capability_plan with required_capabilities, tool_tasks, agent_tasks, and "
                "answer_contract. Legacy answer_mode fields may be included only for "
                "backward compatibility and must be derived from the capability plan."
            ),
            payload={"request": request.model_dump(mode="json")},
        )
        return _validated_intent(result, request)
    except TravelModelCallError:
        raise
    except Exception as exc:
        raise TravelModelCallError("query_understanding", exc.__class__.__name__, model=model) from exc


async def plan_travel_search(
    *,
    request: TravelPlanRequest,
    intent: TravelIntent,
    agent_client: object | None,
    model: str,
) -> SearchPlan:
    runner = getattr(agent_client, "run_agent", None)
    if not callable(runner):
        raise TravelModelCallError("search_planner", "agent client unavailable", model=model)
    try:
        result = await runner(
            agent_name="search_planner",
            model=model,
            prompt=(
                "Create a compact search plan from the capability plan. Generate localized "
                "query variants from the semantic target, not from a hardcoded term list."
            ),
            payload={
                "request": request.model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
                "capability_plan": intent.capability_plan.model_dump(mode="json"),
            },
        )
        return _validated_search_plan(result, request, intent)
    except TravelModelCallError:
        raise
    except Exception as exc:
        raise TravelModelCallError("search_planner", exc.__class__.__name__, model=model) from exc


async def draft_trip_plan(
    *,
    request: TravelPlanRequest,
    intent: TravelIntent,
    search_plan: SearchPlan,
    agent_client: object | None,
    model: str,
) -> TripPlanDraft:
    runner = getattr(agent_client, "run_agent", None)
    if not callable(runner):
        raise TravelModelCallError("trip_plan_drafter", "agent client unavailable", model=model)
    try:
        result = await runner(
            agent_name="trip_plan_drafter",
            model=model,
            prompt=(
                "Create an internal TripPlanDraft from the capability plan before any final "
                "answer. Do not add flights, hotels, full itinerary, weather, visa, or safety "
                "tasks unless the user or capability plan asked for them."
            ),
            payload={
                "request": request.model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
                "capability_plan": intent.capability_plan.model_dump(mode="json"),
                "search_plan": search_plan.model_dump(mode="json"),
            },
        )
        if not isinstance(result, dict):
            raise ValueError("trip_plan_drafter returned non-object")
        draft = TripPlanDraft.model_validate(result)
        if not draft.required_capabilities or not draft.tasks:
            raise ValueError("trip_plan_drafter omitted required_capabilities or tasks")
        return _normalize_trip_plan_draft(draft, request, intent)
    except TravelModelCallError:
        raise
    except Exception as exc:
        raise TravelModelCallError("trip_plan_drafter", exc.__class__.__name__, model=model) from exc


async def verify_candidates(
    *,
    request: TravelPlanRequest,
    intent: TravelIntent,
    search_plan: SearchPlan,
    candidates: list[CandidateDocument],
    agent_client: object | None,
    model: str,
) -> list[CandidateVerdict]:
    if not candidates:
        return []
    runner = getattr(agent_client, "run_agent", None)
    if not callable(runner):
        raise TravelModelCallError("candidate_verifier", "agent client unavailable", model=model)
    try:
        result = await runner(
            agent_name="candidate_verifier",
            model=model,
            prompt=(
                "Verify each candidate against the original user query and capability plan. "
                "Return structured verdicts only. A high rating must not override a semantic mismatch."
            ),
            payload={
                "request": request.model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
                "capability_plan": intent.capability_plan.model_dump(mode="json"),
                "search_plan": search_plan.model_dump(mode="json"),
                "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            },
        )
        verdicts = _verdicts_from_result(result)
        if not verdicts:
            raise ValueError("candidate_verifier returned no verdicts")
        return _stabilize_verdicts(candidates, verdicts, search_plan)
    except TravelModelCallError:
        raise
    except Exception as exc:
        raise TravelModelCallError("candidate_verifier", exc.__class__.__name__, model=model) from exc


def candidate_documents_from_payloads(api_payloads: dict[str, Any]) -> list[CandidateDocument]:
    documents: list[CandidateDocument] = []
    for key, value in api_payloads.items():
        if not (key == "raw_query" or key.startswith("local:")):
            continue
        for index, item in enumerate(_list_of_dicts(value)):
            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue
            documents.append(
                CandidateDocument(
                    candidate_id=f"{key}:{index}",
                    title=title,
                    snippet=str(item.get("snippet") or item.get("description") or "").strip(),
                    address=str(item.get("address") or item.get("location") or "").strip(),
                    type=str(item.get("type") or item.get("category") or "").strip(),
                    category=str(item.get("category") or "").strip(),
                    query_variant=str(item.get("query_variant") or item.get("source_query") or "").strip(),
                    source_key=key,
                    raw=dict(item),
                )
            )
    return documents


def apply_candidate_verdicts(
    api_payloads: dict[str, Any],
    verdicts: list[CandidateVerdict],
) -> dict[str, Any]:
    if not verdicts:
        return api_payloads
    by_id = {verdict.candidate_id: verdict for verdict in verdicts}
    updated = dict(api_payloads)
    for key, value in api_payloads.items():
        if not (key == "raw_query" or key.startswith("local:")):
            continue
        items = [dict(item) for item in _list_of_dicts(value)]
        next_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            verdict = by_id.get(f"{key}:{index}")
            if verdict is not None:
                item["semantic_relevance_score"] = verdict.relevance_score
                item["semantic_match_reason"] = verdict.match_reason
                item["semantic_matched_terms"] = verdict.matched_requirements
                item["semantic_missing_terms"] = verdict.missing_requirements
                item["semantic_is_relevant"] = verdict.is_relevant
                if not verdict.is_relevant:
                    continue
            next_items.append(item)
        updated[key] = sorted(
            next_items,
            key=lambda candidate: int(candidate.get("semantic_relevance_score") or 0),
            reverse=True,
        )
    return updated


def _validated_intent(result: Any, request: TravelPlanRequest) -> TravelIntent:
    if not isinstance(result, dict):
        raise ValueError("query_understanding returned non-object")
    if not any(key in result for key in ["answer_mode", "requires_place", "task_type", "target_entity", "target_type"]):
        raise ValueError("query_understanding omitted intent fields")
    result = _normalize_nullable_intent_payload(result)
    try:
        intent = TravelIntent.model_validate(result)
    except ValidationError:
        raise
    intent = _coerce_place_evaluation_intent(intent, request)
    if not intent.destination:
        intent.destination = request.city or _destination_from_text(_request_text(request))
    if not intent.category:
        intent.category = _category_from_text(_request_text(request), request.requested_categories)
    if not intent.requested_outputs:
        intent.requested_outputs = _requested_outputs_for_intent(intent)
    if not intent.need_supplier_types:
        intent.need_supplier_types = _capabilities_for_intent(intent)
    if not intent.must_answer:
        intent.must_answer = _must_answer_for_intent(request, intent)
    if not intent.should_not_answer:
        intent.should_not_answer = _should_not_answer_for_intent(intent)
    if not intent.capability_plan.required_capabilities:
        intent.capability_plan = _capability_plan_from_intent(request, intent)
    return _normalize_router_fields(intent, request)


def _normalize_nullable_intent_payload(result: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(result)
    for field in [
        "task_type",
        "answer_mode",
        "domain",
        "trip_stage",
        "traveler_stage",
        "delivery_strategy",
        "destination",
        "category",
        "target_entity",
        "target_type",
        "clarifying_question",
    ]:
        if cleaned.get(field) is None:
            cleaned[field] = ""
    for field in [
        "requested_outputs",
        "need_supplier_types",
        "must_answer",
        "should_not_answer",
        "constraints",
        "avoid",
    ]:
        if cleaned.get(field) is None:
            cleaned[field] = []
    for field in [
        "requires_place",
        "needs_geo",
        "needs_realtime_inventory",
        "needs_user_memory",
        "needs_knowledge",
        "needs_transaction",
        "needs_explanation",
    ]:
        if cleaned.get(field) is None:
            cleaned.pop(field, None)
    if cleaned.get("confidence") is None:
        cleaned.pop("confidence", None)
    capability_plan = cleaned.get("capability_plan")
    if isinstance(capability_plan, dict):
        cleaned["capability_plan"] = _normalize_nullable_capability_plan(capability_plan)
    elif capability_plan is None:
        cleaned.pop("capability_plan", None)
    return cleaned


def _normalize_nullable_capability_plan(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(value)
    for field in ["user_goal", "intent_kind"]:
        if cleaned.get(field) is None:
            cleaned[field] = ""
    if cleaned.get("required_capabilities") is None:
        cleaned["required_capabilities"] = []
    if cleaned.get("tool_tasks") is None:
        cleaned["tool_tasks"] = []
    if cleaned.get("agent_tasks") is None:
        cleaned["agent_tasks"] = []
    if cleaned.get("confidence") is None:
        cleaned.pop("confidence", None)
    cleaned["tool_tasks"] = [
        _normalize_nullable_tool_task(item)
        for item in cleaned.get("tool_tasks", [])
        if isinstance(item, dict)
    ]
    cleaned["agent_tasks"] = [
        _normalize_nullable_agent_task(item)
        for item in cleaned.get("agent_tasks", [])
        if isinstance(item, dict)
    ]
    answer_contract = cleaned.get("answer_contract")
    if isinstance(answer_contract, dict):
        cleaned["answer_contract"] = _normalize_nullable_answer_contract(answer_contract)
    elif answer_contract is None:
        cleaned.pop("answer_contract", None)
    return cleaned


def _normalize_nullable_tool_task(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(value)
    for field in ["task_id", "capability", "query"]:
        if cleaned.get(field) is None:
            cleaned[field] = ""
    if cleaned.get("required") is None:
        cleaned.pop("required", None)
    return cleaned


def _normalize_nullable_agent_task(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(value)
    for field in ["task_id", "agent_role", "objective"]:
        if cleaned.get(field) is None:
            cleaned[field] = ""
    if cleaned.get("input_keys") is None:
        cleaned["input_keys"] = []
    if cleaned.get("required") is None:
        cleaned.pop("required", None)
    return cleaned


def _normalize_nullable_answer_contract(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(value)
    if cleaned.get("response_style") is None:
        cleaned["response_style"] = ""
    for field in ["needs_map", "needs_cards", "needs_itinerary", "needs_inventory"]:
        if cleaned.get(field) is None:
            cleaned.pop(field, None)
    return cleaned


def _validated_search_plan(
    result: Any,
    request: TravelPlanRequest,
    intent: TravelIntent,
) -> SearchPlan:
    if not isinstance(result, dict):
        raise ValueError("search_planner returned non-object")
    if not any(key in result for key in ["tools", "query_variants", "must_satisfy", "should_search"]):
        raise ValueError("search_planner omitted search fields")
    try:
        plan = SearchPlan.model_validate(result)
    except ValidationError:
        raise
    if not plan.tools:
        raise ValueError("search_planner omitted tools")
    if not plan.query_variants:
        raise ValueError("search_planner omitted query_variants")
    if intent.answer_mode == "answer_only" or not intent.requires_place:
        plan = plan.model_copy(update={"tools": ["serper_search", "exa_search"]})
    return plan


def _verdicts_from_result(result: Any) -> list[CandidateVerdict]:
    if not isinstance(result, dict):
        return []
    verdicts = result.get("verdicts")
    if not isinstance(verdicts, list):
        return []
    parsed: list[CandidateVerdict] = []
    for item in verdicts:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(CandidateVerdict.model_validate(item))
        except ValidationError:
            continue
    return parsed


def _stabilize_verdicts(
    candidates: list[CandidateDocument],
    verdicts: list[CandidateVerdict],
    search_plan: SearchPlan,
) -> list[CandidateVerdict]:
    requirements = _unique_non_empty(search_plan.must_satisfy)
    if not requirements:
        return verdicts
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    stabilized: list[CandidateVerdict] = []
    for verdict in verdicts:
        candidate = by_id.get(verdict.candidate_id)
        if candidate is None:
            stabilized.append(verdict)
            continue
        surface_raw = " ".join(
            [
                candidate.title,
                candidate.snippet,
                candidate.address,
                candidate.type,
                candidate.category,
            ]
        )
        surface_matches = _positive_surface_matches(surface_raw, requirements)
        if not surface_matches:
            stabilized.append(
                verdict.model_copy(
                    update={
                        "is_relevant": False,
                        "relevance_score": min(verdict.relevance_score, 12),
                        "matched_requirements": [],
                        "missing_requirements": requirements[:4],
                        "match_reason": "候选自身名称/摘要/类型没有命中用户核心目标。",
                    }
                )
            )
            continue
        stabilized.append(
            verdict.model_copy(
                update={
                    "is_relevant": True,
                    "matched_requirements": list(
                        dict.fromkeys([*verdict.matched_requirements, *surface_matches])
                    ),
                    "relevance_score": max(verdict.relevance_score, 80),
                }
            )
        )
    return stabilized


def _positive_surface_matches(surface: str, requirements: list[str]) -> list[str]:
    lowered = surface.lower()
    normalized = _normalized(surface)
    matches = []
    for term in requirements:
        if not term:
            continue
        for candidate in _expanded_requirement_terms(term):
            lower_term = candidate.lower()
            if f"no {lower_term}" in lowered or f"not {lower_term}" in lowered or f"without {lower_term}" in lowered:
                continue
            normalized_term = _normalized(candidate)
            if normalized_term and normalized_term in normalized:
                matches.append(candidate)
                break
    return matches


def _expanded_requirement_terms(term: str) -> list[str]:
    normalized = _normalized(term)
    terms = [term]
    if any(token in normalized for token in ["河豚", "ふぐ", "fugu", "pufferfish", "puffer"]):
        terms.extend(["河豚", "ふぐ", "フグ", "fugu", "pufferfish", "puffer fish", "blowfish", "とらふぐ"])
    if any(token in normalized for token in ["福冈", "福岡", "fukuoka"]):
        terms.extend(["福冈", "福岡", "fukuoka"])
    if any(token in normalized for token in ["餐厅", "餐廳", "restaurant", "料理店"]):
        terms.extend(["餐厅", "餐廳", "restaurant", "restaurants", "料理店", "店", "dining"])
    if any(token in normalized for token in ["美食", "food", "cuisine"]):
        terms.extend(["美食", "food", "cuisine", "restaurant", "料理"])
    if any(token in normalized for token in ["attraction", "attractions", "sightseeing", "things to do", "景点", "景點", "好玩"]):
        terms.extend(
            [
                "attraction",
                "attractions",
                "tourist attraction",
                "things to do",
                "sightseeing",
                "tower",
                "park",
                "museum",
                "shrine",
                "temple",
                "market",
                "beach",
                "garden",
                "景点",
                "景點",
                "公园",
                "公園",
                "神社",
                "寺",
                "塔",
                "市场",
                "市場",
                "海滨",
                "海濱",
            ]
        )
    if any(token in normalized for token in ["local experience", "local experiences", "local_experiences", "activity", "activities", "本地体验", "本地體驗"]):
        terms.extend(
            [
                "local experience",
                "local experiences",
                "activity",
                "activities",
                "things to do",
                "market",
                "workshop",
                "event",
                "park",
                "museum",
                "shrine",
                "temple",
                "tower",
                "本地体验",
                "本地體驗",
                "体验",
                "體驗",
                "活动",
                "活動",
                "市场",
                "市場",
                "公园",
                "公園",
                "神社",
            ]
        )
    return _unique_non_empty(terms)


def _normalize_trip_plan_draft(
    draft: TripPlanDraft,
    request: TravelPlanRequest,
    intent: TravelIntent,
) -> TripPlanDraft:
    capabilities = _unique_non_empty([*draft.required_capabilities])
    tasks = [dict(task) for task in draft.tasks if isinstance(task, dict)]
    if not capabilities:
        raise ValueError("trip plan draft omitted capabilities")
    if not tasks:
        raise ValueError("trip plan draft omitted tasks")
    return draft.model_copy(
        update={
            "required_capabilities": capabilities,
            "skipped_capabilities": _unique_non_empty(draft.skipped_capabilities),
            "tasks": tasks,
            "followup_slots": _unique_non_empty(draft.followup_slots),
        }
    )


def _capabilities_for_intent(intent: TravelIntent) -> list[str]:
    if intent.capability_plan.required_capabilities:
        return _unique_non_empty(intent.capability_plan.required_capabilities)
    if intent.need_supplier_types:
        return _unique_non_empty(intent.need_supplier_types)
    if intent.answer_mode == "answer_only" or not intent.requires_place:
        return ["knowledge"]
    if intent.answer_mode in {"itinerary", "route_map"}:
        return ["places", "routes", "maps", "activities", "budget", "transport", "knowledge"]
    if intent.target_type == "hotel" or intent.category in {"住宿", "酒店"}:
        return ["hotels", "maps", "knowledge"]
    if intent.target_type == "flight":
        return ["flights"]
    return ["places", "maps", "knowledge"]


def _capability_plan_from_intent(
    request: TravelPlanRequest,
    intent: TravelIntent,
) -> TravelCapabilityPlan:
    capabilities = _capabilities_for_intent(intent)
    requested_outputs = set(intent.requested_outputs or _requested_outputs_for_intent(intent))
    tool_tasks = [
        TravelToolTask(
            task_id=f"{capability}_task",
            capability=capability,
            query=intent.target_entity or request.query or request.question or intent.category,
            required=capability not in {"knowledge", "weather", "visa", "safety"},
        )
        for capability in capabilities
        if capability not in {"food"}
    ]
    agent_tasks = [
        TravelAgentTask(
            task_id=f"{role}_analysis",
            agent_role=role,
            objective=_capability_purpose(capability, intent),
            input_keys=[],
            required=True,
        )
        for capability, role in _agent_roles_for_capabilities(capabilities, intent)
    ]
    return TravelCapabilityPlan(
        user_goal=request.query or request.question or intent.target_entity or intent.category,
        intent_kind=intent.task_type,
        required_capabilities=capabilities,
        tool_tasks=tool_tasks,
        agent_tasks=agent_tasks,
        answer_contract=TravelAnswerContract(
            needs_map=bool({"maps", "places", "routes"} & set(capabilities)) and intent.requires_place,
            needs_cards="place_cards" in requested_outputs or bool({"places", "hotels", "flights"} & set(capabilities)),
            needs_itinerary="itinerary" in requested_outputs or intent.answer_mode == "itinerary",
            needs_inventory=bool({"hotels", "flights"} & set(capabilities)),
            response_style=intent.answer_mode,
        ),
        confidence=intent.confidence,
    )


def _agent_roles_for_capabilities(
    capabilities: list[str],
    intent: TravelIntent,
) -> list[tuple[str, str]]:
    capability_set = set(capabilities)
    roles: list[tuple[str, str]] = []
    if "flights" in capability_set:
        roles.append(("flights", "flight"))
    if "hotels" in capability_set:
        roles.append(("hotels", "hotel"))
    if intent.answer_mode == "itinerary" or len(capability_set & {"routes", "budget", "transport"}) >= 2:
        roles.append(("itinerary", "itinerary"))
    if capability_set & {"places", "activities", "food", "maps"} and intent.answer_mode != "answer_only":
        roles.append(("places", "activity_food"))
    if not roles and "knowledge" in capability_set:
        roles.append(("knowledge", "destination"))
    return roles


def _normalize_router_fields(intent: TravelIntent, request: TravelPlanRequest) -> TravelIntent:
    capabilities = _capabilities_for_intent(intent)
    capability_set = set(capabilities)
    text = _request_text(request)
    needs_transaction = _looks_like_transaction(text) or bool(capability_set & {"payment", "payments", "checkout"})
    needs_realtime_inventory = bool(capability_set & {"hotels", "flights"}) or _looks_like_inventory_search(text)
    needs_geo = (
        intent.answer_mode != "answer_only"
        and intent.requires_place
        and bool(capability_set & {"places", "maps", "routes", "activities", "hotels"})
    )
    return intent.model_copy(
        update={
            "traveler_stage": _traveler_stage_for_intent(text, intent, capabilities),
            "needs_geo": needs_geo,
            "needs_realtime_inventory": needs_realtime_inventory,
            "needs_user_memory": bool(request.previous_context),
            "needs_knowledge": "knowledge" in capability_set or intent.answer_mode == "answer_only",
            "needs_transaction": needs_transaction,
            "needs_explanation": intent.answer_mode != "route_map" or "knowledge" in capability_set,
            "delivery_strategy": _delivery_strategy_for_intent(intent, capabilities, text),
        }
    )


def _capabilities_for_text(text: str, *, itinerary: bool) -> list[str]:
    lowered = text.lower()
    capabilities = ["places", "routes", "maps", "activities", "budget", "transport", "knowledge"]
    if any(token in lowered for token in ["酒店", "住宿", "hotel", "晚"]):
        capabilities.append("hotels")
    if any(token in lowered for token in ["航班", "机票", "flight", "出发"]):
        capabilities.append("flights")
    return _unique_non_empty(capabilities if itinerary else ["places", "maps", "knowledge"])


def _traveler_stage_for_intent(text: str, intent: TravelIntent, capabilities: list[str]) -> str:
    lowered = text.lower()
    capability_set = set(capabilities)
    if _looks_like_transaction(lowered):
        return "book"
    if any(token in lowered for token in ["订单", "已订", "改签", "取消", "manage booked"]):
        return "manage_booked_trip"
    if intent.answer_mode in {"itinerary", "route_map"}:
        if any(token in lowered for token in ["调整", "修改", "第二天", "第三天", "refine"]):
            return "refine_itinerary"
        return "build_itinerary"
    if capability_set & {"hotels", "flights"} or _looks_like_inventory_search(lowered):
        return "search_offers"
    if intent.answer_mode == "answer_only":
        return "inspiration"
    if any(token in lowered for token in ["比较", "哪个好", "compare", "versus", "vs"]):
        return "compare_destinations"
    if any(token in lowered for token in ["现在", "附近", "去哪", "哪里", "where to", "nearby"]):
        return "on_trip_assistance"
    return "inspiration"


def _delivery_strategy_for_intent(intent: TravelIntent, capabilities: list[str], text: str) -> str:
    capability_set = set(capabilities)
    if intent.answer_mode == "answer_only" or not intent.requires_place:
        return "single_agent"
    if intent.answer_mode in {"itinerary", "route_map"}:
        return "fanout"
    if capability_set & {"hotels", "flights"}:
        return "single_agent"
    if _looks_like_transaction(text):
        return "sequential"
    if len(capability_set & {"places", "routes", "activities", "budget", "transport", "knowledge"}) >= 4:
        return "fanout"
    return "sequential" if capability_set & {"places", "maps", "knowledge"} else "single_agent"


def _looks_like_inventory_search(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"酒店|住宿|房价|房态|机票|航班|价格|库存|hotel|flight|fare|availability|offer",
            lowered,
        )
    )


def _looks_like_hotel_query(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"酒店|住宿|旅馆|旅館|旅店|民宿|房间|房价|hotel|ryokan|stay", lowered))


def _looks_like_flight_query(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"航班|机票|飛行機|flight|airfare|fare", lowered))


def _looks_like_transaction(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"支付|预订|下单|checkout|payment|book now|reserve", lowered))


def _capability_purpose(capability: str, intent: TravelIntent) -> str:
    return {
        "places": "搜索符合用户问题的真实地点候选",
        "maps": "生成地图坐标和外跳链接",
        "routes": "检查地点之间的路线可行性",
        "activities": "搜索活动和体验候选",
        "knowledge": "补充目的地或主题背景信息",
        "budget": "检查预算和性价比",
        "transport": "检查当地交通选项",
        "hotels": "查询住宿供应商候选",
        "flights": "查询航班供应商候选",
    }.get(capability, f"处理 {intent.target_entity or intent.category or capability} 相关任务")


def _followup_slots_for_intent(request: TravelPlanRequest, intent: TravelIntent) -> list[str]:
    slots: list[str] = []
    if intent.answer_mode != "answer_only" and not request.date_range:
        slots.append("日期")
    if intent.answer_mode in {"itinerary", "route_map"} and not request.budget:
        slots.append("预算")
    if request.travelers <= 1 and intent.answer_mode in {"itinerary", "route_map"}:
        slots.append("同行人数")
    return _unique_non_empty(slots)


def _requested_outputs_for_intent(intent: TravelIntent) -> list[str]:
    if intent.answer_mode == "answer_only":
        return ["narrative"]
    if intent.answer_mode == "itinerary":
        return ["itinerary", "place_cards", "map", "narrative"]
    return ["place_cards", "map", "narrative"]


def _must_answer_for_intent(request: TravelPlanRequest, intent: TravelIntent) -> list[str]:
    value = request.query or request.question or intent.target_entity or intent.category
    return [value] if value else []


def _should_not_answer_for_intent(intent: TravelIntent) -> list[str]:
    if intent.task_type == "place_evaluation":
        return ["generic_recommendations"]
    if intent.answer_mode == "answer_only":
        return ["places", "maps", "hotels", "flights"]
    if intent.answer_mode == "place_cards":
        return ["flights", "hotels", "完整行程"]
    return []


def _should_not_answer_for_place_query(text: str) -> list[str]:
    lowered = text.lower()
    blocked = ["完整行程"]
    if not any(token in lowered for token in ["航班", "机票", "flight"]):
        blocked.append("flights")
    if not any(token in lowered for token in ["酒店", "住宿", "hotel"]):
        blocked.append("hotels")
    return blocked


def _entity_requirements(entity: str) -> list[str]:
    if not entity:
        return []
    pieces = [entity]
    pieces.extend(re.findall(r"[A-Za-z][A-Za-z'-]+", entity))
    pieces.extend(re.findall(r"[\u4e00-\u9fff]{2,}", entity))
    return _unique_non_empty(pieces)


def _extract_target_entity(text: str, category: str) -> str:
    cleaned = re.sub(r"[？?。！!，,]", " ", text).strip()
    lowered = cleaned.lower()
    if re.search(r"有什么好吃|有什么好玩|好吃的|好玩的|玩什么|吃什么", lowered):
        return ""
    if re.search(r"日料|日本料理|japanese cuisine", lowered):
        return ""
    if re.search(r"哪里泡温泉|哪泡温泉|泡温泉比较好|泡湯|泡汤|onsen|hot spring", lowered):
        return ""
    latin_tokens = re.findall(r"[A-Za-z][A-Za-z'-]+", cleaned)
    if category == "购物" and latin_tokens and re.search(r"香水|perfume|fragrance|parfum", lowered):
        return " ".join([*latin_tokens[:3], "香水"]).strip()
    if category == "购物" and re.fullmatch(r".*(买|购买|购物).*(香水|perfume|fragrance).*", lowered) and not latin_tokens:
        return ""
    patterns = [
        r"(?:去哪|哪里|哪儿|推荐|想|要|吃|买|看|玩)(?:吃|买|看|玩|找|去)?\s*([^\s]+)",
        r"(?:where to|eat|buy|visit|find)\s+([a-zA-Z][a-zA-Z\s'-]{1,40})",
    ]
    city = _destination_from_text(cleaned)
    stopwords = {
        "什么",
        "好吃",
        "好玩",
        "推荐",
        "比较好",
        "哪里",
        "去哪",
        "福冈",
        "福岡",
        "fukuoka",
        "别府",
        "beppu",
    }
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if not match:
            continue
        entity = match.group(1).strip()
        entity = re.sub(r"^(?:的|个|点|些)", "", entity).strip()
        entity = re.sub(r"(?:比较好|比较好吃|哪里|去哪|推荐)$", "", entity).strip()
        if entity and entity.lower() not in stopwords and entity != city:
            return entity
    if category in {"购物", "美食"}:
        words = [word for word in re.split(r"\s+", cleaned) if word and word.lower() not in stopwords]
        return words[-1] if len(words) >= 2 else ""
    return ""


def _request_text(request: TravelPlanRequest) -> str:
    return " ".join(
        part
        for part in [
            request.query,
            request.question,
            request.city,
            " ".join(request.interest_tags),
            " ".join(request.requested_categories),
        ]
        if part
    )


def _category_from_text(text: str, requested_categories: list[str]) -> str:
    if requested_categories:
        return requested_categories[0]
    lowered = text.lower()
    if re.search(r"酒店|住宿|旅馆|旅館|旅店|民宿|房间|房价|hotel|ryokan|stay", lowered):
        return "住宿"
    if re.search(r"吃|美食|餐厅|food|restaurant|ramen|sushi|去哪吃", lowered):
        return "美食"
    if re.search(r"买|购物|香水|商场|shopping|perfume|fragrance", lowered):
        return "购物"
    if re.search(r"历史|文化|寺|神社|museum|heritage", lowered):
        return "历史文化"
    if re.search(r"自然|摄影|拍照|风景|公园|photo|sunset", lowered):
        return "自然与摄影"
    if re.search(r"街区|逛街|neighborhood", lowered):
        return "购物与街区"
    if re.search(r"好玩|玩什么|去哪玩|景点|活动|体验|温泉|onsen|attraction", lowered):
        return "本地体验"
    return ""


def _target_type_from_category(category: str, text: str) -> str:
    if category == "美食":
        return "restaurant"
    if category == "购物":
        return "store"
    if category in {"住宿", "酒店"}:
        return "hotel"
    if category in {"本地体验", "自然与摄影", "历史文化"}:
        return "place"
    return "poi"


def _looks_like_knowledge_question(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"是什么|为什么|什么意思|怎么回事|介绍一下|由来|history of|what is|why is", lowered)
        and not re.search(r"哪里|去哪|哪儿|推荐|路线|地图|吃|买|visit|where to", lowered)
    )


def _looks_like_place_evaluation_question(text: str) -> bool:
    lowered = text.lower()
    asks_evaluation = bool(
        re.search(
            r"评价|评论|口碑|怎么样|怎麼樣|如何|值得去吗|值不值得|是否值得|值得.*吗|"
            r"过誉|過譽|踩雷|避雷|好不好玩|好不好吃|好不好|worth visiting|worth it|"
            r"overrated|review|reputation",
            lowered,
        )
    )
    asks_for_recommendations = bool(
        re.search(r"哪里|去哪|哪儿|推荐|有哪些|吃什么|玩什么|买什么|where to|recommend", lowered)
    )
    return asks_evaluation and not asks_for_recommendations


def _extract_evaluation_target(text: str) -> str:
    cleaned = re.sub(r"[？?。！!，,]", " ", text).strip()
    cleaned = re.sub(r"\b(fukuoka|beppu|kyoto|osaka|miyajima)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"福冈|福岡|别府|別府|京都|大阪|宫岛|宮島", " ", cleaned)
    cleaned = re.sub(
        r"评价怎样|评价怎么样|评论怎样|评论怎么样|口碑如何|口碑怎么样|怎么样|怎麼樣|如何|"
        r"值得去吗|值不值得去|值不值得|是否值得|值得.*吗|过誉吗|過譽嗎|过誉|過譽|"
        r"踩雷吗|踩雷|避雷|好不好玩|好不好吃|好不好|worth visiting|worth it|"
        r"overrated|review|reputation",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^(?:的|这个|這個|the)\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*(?:的)$", "", cleaned).strip()
    return cleaned


def _coerce_place_evaluation_intent(intent: TravelIntent, request: TravelPlanRequest) -> TravelIntent:
    text = _request_text(request)
    if not _looks_like_place_evaluation_question(text) or _looks_like_itinerary(text):
        return intent
    target_entity = intent.target_entity or _extract_evaluation_target(text)
    return intent.model_copy(
        update={
            "task_type": "place_evaluation",
            "answer_mode": "answer_only",
            "requires_place": False,
            "domain": "travel",
            "trip_stage": "research",
            "target_entity": target_entity,
            "target_type": "knowledge",
            "requested_outputs": ["narrative"],
            "need_supplier_types": ["knowledge"],
            "should_not_answer": ["generic_recommendations"],
        }
    )


def _looks_like_itinerary(text: str) -> bool:
    return bool(re.search(r"行程|自由行|几天|两天|三天|完整|安排|itinerary|trip plan", text.lower()))


def _looks_like_route_query(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"怎么走|怎么去|如何去|路线|交通|换乘|到.+怎么|how to get|route|transport|transfer|from .+ to",
            lowered,
        )
    )


def _destination_from_text(text: str) -> str:
    lowered = text.lower()
    if "福冈" in text or "福岡" in text or "fukuoka" in lowered:
        return "Fukuoka"
    if "别府" in text or "別府" in text or "beppu" in lowered:
        return "Beppu"
    if "京都" in text or "kyoto" in lowered:
        return "Kyoto"
    if "大阪" in text or "osaka" in lowered:
        return "Osaka"
    return ""


def _category_search_phrase(category: str) -> str:
    return {
        "美食": "food restaurants",
        "购物": "shopping stores",
        "住宿": "hotels lodging",
        "历史文化": "history culture heritage",
        "本地体验": "things to do attractions",
        "购物与街区": "shopping neighborhoods",
        "自然与摄影": "nature photography views",
    }.get(category, "")


def _locale_for_text(text: str) -> str:
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "ja-JP"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh-CN"
    return "en-US"


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _unique_non_empty(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(item.strip() for item in values if item and item.strip())]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
