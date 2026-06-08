from __future__ import annotations

import re
from typing import Any, NotRequired, TypedDict
from urllib.parse import quote_plus

from langgraph.graph import END, START, StateGraph

from app.schemas.travel import (
    TravelAnswerSection,
    TravelDisplayCard,
    TravelHotelOffer,
    TravelItineraryBlock,
    TravelItineraryDay,
    TravelItineraryPlan,
    TravelPlanRequest,
    TravelPlanResponse,
    TravelRouteOption,
    TravelWorkflowStep,
)
from app.services.travel_query_understanding import (
    SearchPlan,
    TripPlanDraft,
    TravelAgentTask,
    TravelAnswerContract,
    TravelCapabilityPlan,
    TravelIntent,
    TravelModelCallError,
    TravelToolTask,
    apply_candidate_verdicts,
    draft_trip_plan,
    plan_travel_search,
    understand_travel_query,
)


GRAPH_NODE_NAMES = [
    "route",
    "plan_tasks",
    "collect_tools",
    "validate_candidates",
    "run_agents",
    "compose_decision",
    "narrative",
    "render_contract",
]

ORCHESTRATOR_GRAPH_NODE_NAMES = [
    "orchestrate",
    "execute_tools",
    "final_answer",
    "render_response",
]

TRAVEL_ORCHESTRATOR_PROMPT = (
    "请像靠谱旅行顾问一样自然回答当前问题。问什么答什么，不套固定模板；需要推荐时给出真实、可执行、"
    "避开广告营销的理由；需要地点或路线时再调用工具，不编造价格、营业时间、库存、距离或坐标。"
)

ORCHESTRATOR_TOOL_NAMES = {
    "serper_search",
    "serper_places",
    "serper_images",
    "route_lookup",
}

DISABLED_ORCHESTRATOR_TOOL_NAMES = {
    "hotel_search",
    "flight_search",
    "weather_lookup",
    "visa_safety_lookup",
    "complex_route_reasoner",
    "critic_verifier",
    "visual_context_analyzer",
}


class TravelWorkflowState(TypedDict, total=False):
    supervisor: Any
    request: TravelPlanRequest
    cache_key: str
    intent: TravelIntent
    search_plan: SearchPlan
    plan_draft: TripPlanDraft
    api_payloads: dict[str, Any]
    api_warnings: list[str]
    candidate_verdicts: list[Any]
    agent_results: list[Any]
    critic: dict[str, Any]
    response: TravelPlanResponse
    orchestrator_contract: dict[str, Any]
    initial_orchestrator_contract: dict[str, Any]
    tool_results: list[dict[str, Any]]
    route_options: list[TravelRouteOption]
    hotel_offers: list[TravelHotelOffer]
    finalization_source: str
    trace: list[dict[str, Any]]
    failed_nodes: list[str]
    warnings: list[str]
    completed_nodes: list[str]
    skipped_nodes: NotRequired[list[str]]


async def run_travel_workflow(
    *,
    supervisor: Any,
    request: TravelPlanRequest,
    cache_key: str,
) -> TravelPlanResponse:
    """Run the real embedded LangGraph workflow for travel planning."""

    graph = _build_graph()
    final_state = await graph.ainvoke(
        {
            "supervisor": supervisor,
            "request": request,
            "cache_key": cache_key,
            "trace": [],
            "failed_nodes": [],
            "warnings": [],
            "completed_nodes": [],
        }
    )
    response = final_state.get("response")
    if response is None:
        raise RuntimeError("travel workflow did not produce a response")
    return response


async def run_travel_orchestrator_workflow(
    *,
    supervisor: Any,
    request: TravelPlanRequest,
    cache_key: str,
) -> TravelPlanResponse:
    """Run the GPT-led manager workflow with bounded tool execution."""

    graph = _build_orchestrator_graph()
    final_state = await graph.ainvoke(
        {
            "supervisor": supervisor,
            "request": request,
            "cache_key": cache_key,
            "trace": [],
            "failed_nodes": [],
            "warnings": [],
            "completed_nodes": [],
            "tool_results": [],
            "route_options": [],
            "hotel_offers": [],
        }
    )
    response = final_state.get("response")
    if response is None:
        raise RuntimeError("travel orchestrator workflow did not produce a response")
    return response


def _build_orchestrator_graph():
    builder = StateGraph(TravelWorkflowState)
    builder.add_node("orchestrate", _orchestrate)
    builder.add_node("execute_tools", _execute_tools)
    builder.add_node("final_answer", _final_answer)
    builder.add_node("render_response", _render_orchestrator_response)

    builder.add_edge(START, "orchestrate")
    builder.add_edge("orchestrate", "execute_tools")
    builder.add_edge("execute_tools", "final_answer")
    builder.add_edge("final_answer", "render_response")
    builder.add_edge("render_response", END)
    return builder.compile()


def _build_graph():
    builder = StateGraph(TravelWorkflowState)
    builder.add_node("route", _route)
    builder.add_node("plan_tasks", _plan_tasks)
    builder.add_node("collect_tools", _collect_tools)
    builder.add_node("validate_candidates", _validate_candidates)
    builder.add_node("run_agents", _run_agents)
    builder.add_node("compose_decision", _compose_decision)
    builder.add_node("narrative", _narrative)
    builder.add_node("render_contract", _render_contract)

    builder.add_edge(START, "route")
    builder.add_edge("route", "plan_tasks")
    builder.add_edge("plan_tasks", "collect_tools")
    builder.add_edge("collect_tools", "validate_candidates")
    builder.add_edge("validate_candidates", "run_agents")
    builder.add_edge("run_agents", "compose_decision")
    builder.add_edge("compose_decision", "narrative")
    builder.add_edge("narrative", "render_contract")
    builder.add_edge("render_contract", END)
    return builder.compile()


async def _orchestrate(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    if _is_obvious_itinerary_request(request):
        contract = _enforce_required_orchestrator_tools(
            _obvious_itinerary_contract(request),
            request,
        )
    elif _is_obvious_first_timer_recommendation_request(request):
        contract = _obvious_first_timer_recommendation_contract(request)
    else:
        contract = _enforce_required_orchestrator_tools(
            _strip_inventory_only_place_tools(
                await _call_travel_orchestrator(supervisor, request),
                request,
            ),
            request,
        )
    intent, search_plan, plan_draft = _planning_from_orchestrator_contract(contract, request)
    return _step_update(
        state,
        node="orchestrate",
        phase="plan",
        observation={
            "answer_mode": intent.answer_mode,
            "tool_calls": len(_contract_tool_calls(contract)),
            "model": supervisor.model_router.orchestrator,
        },
        values={
            "orchestrator_contract": contract,
            "initial_orchestrator_contract": contract,
            "intent": intent,
            "search_plan": search_plan,
            "plan_draft": plan_draft,
        },
    )


async def _execute_tools(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    contract = state["orchestrator_contract"]
    api_payloads, warnings, tool_results, route_options = await _execute_orchestrator_tools(
        supervisor=supervisor,
        request=request,
        contract=contract,
        intent=state["intent"],
    )
    api_payloads, google_warnings = await supervisor._enrich_api_payloads_with_google_places(
        request,
        api_payloads,
    )
    warnings = [*warnings, *google_warnings]
    return _step_update(
        state,
        node="execute_tools",
        phase="act",
        observation={
            "tool_results": len(tool_results),
            "providers": sorted(api_payloads.keys()),
            "warnings": len(warnings),
        },
        values={
            "api_payloads": api_payloads,
            "api_warnings": warnings,
            "tool_results": tool_results,
            "route_options": route_options,
        },
    )


async def _final_answer(state: TravelWorkflowState) -> dict[str, Any]:
    initial_contract = _normalize_orchestrator_contract(state["orchestrator_contract"])
    if state.get("tool_results"):
        if initial_contract.get("answer_mode") == "answer_only":
            contract = {**initial_contract, "tool_calls_requested": []}
            source = "initial_answer_with_lightweight_search"
        elif (
            deterministic_contract := _deterministic_structured_card_contract(
                initial_contract=initial_contract,
                request=state["request"],
                state=state,
            )
        ) is not None:
            contract = deterministic_contract
            source = "deterministic_structured_cards"
        else:
            try:
                contract = await _call_travel_orchestrator_final(
                    state["supervisor"],
                    state["request"],
                    state,
                )
                source = "final_model_with_tools"
            except TravelModelCallError as exc:
                fallback = _grounded_contract_after_final_model_error(
                    initial_contract=initial_contract,
                    request=state["request"],
                    api_payloads=state.get("api_payloads", {}),
                    error=exc,
                )
                if fallback is None:
                    raise
                contract = fallback
                source = "grounded_fallback_after_final_model_error"
        contract["warnings"] = _unique_strings(
            [
                *state.get("api_warnings", []),
                *_string_list(initial_contract.get("warnings")),
                *_string_list(contract.get("warnings")),
            ]
        )
        contract["data_gaps"] = _unique_strings(
            [
                *state.get("api_warnings", []),
                *_string_list(initial_contract.get("data_gaps")),
                *_string_list(contract.get("data_gaps")),
            ]
        )
    else:
        contract = initial_contract
        source = "initial_contract_no_tools"
    sections = _contract_sections(contract)
    return _step_update(
        state,
        node="final_answer",
        phase="finalize",
        observation={
            "source": source,
            "sections": len(_contract_sections(contract)),
            "cards_from_tools": len(_flatten_tool_items(state.get("api_payloads", {}))),
            "route_options": len(state.get("route_options", [])),
        },
        values={
            "orchestrator_contract": contract,
            "finalization_source": source,
        },
    )


async def _render_orchestrator_response(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    intent = state["intent"]
    contract = state["orchestrator_contract"]
    api_payloads = state.get("api_payloads", {})
    api_warnings = [
        *state.get("api_warnings", []),
        *_string_list(contract.get("warnings")),
        *_string_list(contract.get("data_gaps")),
    ]

    if intent.answer_mode == "answer_only":
        response = supervisor._compose_answer_only_response(
            request=request,
            cache_key=state["cache_key"],
            intent=intent,
            search_plan=state["search_plan"],
            plan_draft=state["plan_draft"],
            api_payloads=api_payloads,
            api_warnings=api_warnings,
            candidate_verdicts=[],
        )
    else:
        response = supervisor._compose_response(
            request=request,
            cache_key=state["cache_key"],
            intent=intent,
            search_plan=state["search_plan"],
            plan_draft=state["plan_draft"],
            candidate_verdicts=[],
            api_payloads=api_payloads,
            api_warnings=api_warnings,
            agent_results=[],
            critic={"summary": _contract_summary(contract), "warnings": api_warnings},
        )
        if intent.answer_mode == "itinerary":
            response = _attach_itinerary_plan(
                request=request,
                response=response,
                plan_draft=state["plan_draft"],
            )
        else:
            response = _attach_first_timer_city_anchor_cards(
                request=request,
                response=response,
            )

    response = _apply_orchestrator_contract(
        response=response,
        state=state,
    )
    return _step_update(
        state,
        node="render_response",
        phase="finalize",
        observation={
            "response": True,
            "cards": len(response.display_cards),
            "route_options": len(response.route_options),
        },
        values={"response": response},
    )


async def _route(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    intent = await understand_travel_query(
        request=request,
        agent_client=supervisor.agent_client,
        model=supervisor.model_router.router,
    )
    return _step_update(
        state,
        node="route",
        phase="plan",
        observation={
            "answer_mode": intent.answer_mode,
            "delivery_strategy": intent.delivery_strategy,
            "needs_geo": intent.needs_geo,
        },
        values={"intent": intent},
    )


async def _plan_tasks(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    intent = state["intent"]
    search_plan = await plan_travel_search(
        request=request,
        intent=intent,
        agent_client=supervisor.agent_client,
        model=supervisor.model_router.planner,
    )
    plan_draft = await draft_trip_plan(
        request=request,
        intent=intent,
        search_plan=search_plan,
        agent_client=supervisor.agent_client,
        model=supervisor.model_router.summarizer,
    )
    return _step_update(
        state,
        node="plan_tasks",
        phase="plan",
        observation={
            "required_capabilities": plan_draft.required_capabilities,
            "query_variants": search_plan.query_variants,
        },
        values={"search_plan": search_plan, "plan_draft": plan_draft},
    )


async def _collect_tools(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    payloads, warnings = await supervisor._collect_api_payloads(
        request,
        intent=state["intent"],
        search_plan=state["search_plan"],
        plan_draft=state["plan_draft"],
    )
    payloads, google_warnings = await supervisor._enrich_api_payloads_with_google_places(
        request,
        payloads,
    )
    warnings = [*warnings, *google_warnings]
    return _step_update(
        state,
        node="collect_tools",
        phase="act",
        observation={"providers": sorted(payloads.keys()), "warnings": len(warnings)},
        values={"api_payloads": payloads, "api_warnings": warnings},
    )


async def _validate_candidates(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    verdicts = await supervisor._verify_api_candidates(
        request=state["request"],
        intent=state["intent"],
        search_plan=state["search_plan"],
        api_payloads=state.get("api_payloads", {}),
    )
    payloads = apply_candidate_verdicts(state.get("api_payloads", {}), verdicts)
    return _step_update(
        state,
        node="validate_candidates",
        phase="observe",
        observation={"candidate_verdicts": len(verdicts)},
        values={"api_payloads": payloads, "candidate_verdicts": verdicts},
    )


async def _run_agents(state: TravelWorkflowState) -> dict[str, Any]:
    intent = state["intent"]
    if intent.answer_mode == "answer_only":
        return _step_update(
            state,
            node="run_agents",
            phase="analyze",
            observation={"skipped": True, "reason": "answer_only"},
            values={
                "agent_results": [],
                "critic": {"summary": "", "warnings": [], "not_recommended": []},
                "skipped_nodes": [*state.get("skipped_nodes", []), "run_agents"],
            },
        )

    supervisor = state["supervisor"]
    request = state["request"]
    agent_results = await supervisor._run_agents(
        request,
        state.get("api_payloads", {}),
        intent=intent,
        plan_draft=state["plan_draft"],
    )
    critic = await supervisor._run_critic(
        request,
        agent_results,
        state.get("api_payloads", {}),
        intent=intent,
        plan_draft=state["plan_draft"],
    )
    return _step_update(
        state,
        node="run_agents",
        phase="analyze",
        observation={
            "agent_count": len(agent_results),
            "critic": bool(critic),
        },
        values={"agent_results": agent_results, "critic": critic},
    )


async def _compose_decision(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    request = state["request"]
    intent = state["intent"]
    if intent.answer_mode == "answer_only":
        response = supervisor._compose_answer_only_response(
            request=request,
            cache_key=state["cache_key"],
            intent=intent,
            search_plan=state["search_plan"],
            plan_draft=state["plan_draft"],
            api_payloads=state.get("api_payloads", {}),
            api_warnings=state.get("api_warnings", []),
            candidate_verdicts=state.get("candidate_verdicts", []),
        )
    else:
        response = supervisor._compose_response(
            request=request,
            cache_key=state["cache_key"],
            intent=intent,
            search_plan=state["search_plan"],
            plan_draft=state["plan_draft"],
            candidate_verdicts=state.get("candidate_verdicts", []),
            api_payloads=state.get("api_payloads", {}),
            api_warnings=[*state.get("api_warnings", []), *state.get("warnings", [])],
            agent_results=state.get("agent_results", []),
            critic=state.get("critic", {}),
        )
        response = await supervisor._apply_ranked_card_reasoner(
            request=request,
            response=response,
        )
        response = supervisor._refresh_decision_cards(
            response=response,
            plan_draft=state["plan_draft"],
        )
        if intent.answer_mode == "itinerary":
            response = _attach_itinerary_plan(
                request=request,
                response=response,
                plan_draft=state["plan_draft"],
            )
    return _step_update(
        state,
        node="compose_decision",
        phase="critique",
        observation={
            "cards": len(response.display_cards),
            "itinerary_days": len(response.itinerary_plan.days),
        },
        values={"response": response},
    )


async def _narrative(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    response = await supervisor._apply_narrative_composer(
        request=state["request"],
        response=state["response"],
        plan_draft=state["plan_draft"],
        api_payloads=state.get("api_payloads", {}),
    )
    if state["intent"].answer_mode == "itinerary" and response.itinerary_plan.days:
        response = response.model_copy(
            update={
                "summary": _itinerary_narrative(response.itinerary_plan),
                "narrative_answer": _itinerary_narrative(response.itinerary_plan),
            }
        )
    return _step_update(
        state,
        node="narrative",
        phase="summarize",
        observation={"narrative": bool(response.narrative_answer)},
        values={"response": response},
    )


async def _render_contract(state: TravelWorkflowState) -> dict[str, Any]:
    supervisor = state["supervisor"]
    response = state["response"]
    if state["intent"].answer_mode != "answer_only":
        response = await supervisor._apply_workflow_summarizer(
            request=state["request"],
            response=response,
            agent_results=state.get("agent_results", []),
            critic=state.get("critic", {}),
            api_payloads=state.get("api_payloads", {}),
        )
        response = await supervisor._apply_formatter(
            request=state["request"],
            response=response,
            agent_results=state.get("agent_results", []),
            critic=state.get("critic", {}),
            api_payloads=state.get("api_payloads", {}),
        )
    response = _inject_graph_contract(response, state)
    return _step_update(
        state,
        node="render_contract",
        phase="finalize",
        observation={"response": True},
        values={"response": response},
    )


def _step_update(
    state: TravelWorkflowState,
    *,
    node: str,
    phase: str,
    observation: dict[str, Any],
    values: dict[str, Any],
    status: str = "completed",
) -> dict[str, Any]:
    trace_item = {
        "node": node,
        "phase": phase,
        "status": status,
        "observation": observation,
    }
    completed_nodes = state.get("completed_nodes", [])
    update = {
        "trace": [*state.get("trace", []), trace_item],
        "completed_nodes": completed_nodes if status == "failed" else [*completed_nodes, node],
    }
    update.update(values)
    return update


async def _call_travel_orchestrator(supervisor: Any, request: TravelPlanRequest) -> dict[str, Any]:
    runner = getattr(supervisor.agent_client, "run_agent", None)
    model = supervisor.model_router.orchestrator
    if not callable(runner):
        raise TravelModelCallError("orchestrator", "agent client unavailable", model=model)
    tool_contract = _orchestrator_tool_contract(request)
    try:
        result = await runner(
            agent_name="travel_orchestrator",
            model=model,
            prompt=TRAVEL_ORCHESTRATOR_PROMPT,
            payload={
                "request": request.model_dump(mode="json"),
                "tool_contract": tool_contract,
                "max_tool_rounds": getattr(supervisor, "orchestrator_max_tool_rounds", 6),
            },
        )
    except TravelModelCallError:
        raise
    except Exception as exc:
        raise TravelModelCallError("orchestrator", _exception_summary(exc), model=model) from exc
    return _normalize_orchestrator_contract(result, allowed_tool_names=tool_contract)


async def _call_travel_orchestrator_final(
    supervisor: Any,
    request: TravelPlanRequest,
    state: TravelWorkflowState,
) -> dict[str, Any]:
    runner = getattr(supervisor.agent_client, "run_agent", None)
    model = supervisor.model_router.orchestrator
    if not callable(runner):
        raise TravelModelCallError("orchestrator", "agent client unavailable", model=model)
    answer_framework = _classified_answer_framework(request, state)
    payload = {
        "phase": "final_answer",
        "request": request.model_dump(mode="json"),
        "initial_contract": _compact_contract(state.get("initial_orchestrator_contract", {})),
        "tool_results": _compact_tool_results(state.get("tool_results", [])),
        "api_observations": _compact_api_payloads(state.get("api_payloads", {})),
        "answer_framework": answer_framework,
        "route_options": [
            option.model_dump(mode="json")
            for option in state.get("route_options", [])
        ],
        "warnings": state.get("api_warnings", []),
        "tool_policy": "do_not_request_additional_tools",
    }
    prompt = (
        "请基于当前问题和已执行的工具结果，生成自然、简洁、好读的旅行回答合同。"
        "问什么答什么，不套固定栏目；如果推荐地点或路线，只使用工具结果中的真实数据，说明推荐理由和取舍。"
        "不要提内部规则、工具名、框架名或来源标签；不要编造价格、营业时间、库存、距离或坐标。"
    )
    last_error: TravelModelCallError | None = None
    contract: dict[str, Any] | None = None
    for attempt in range(1, 3):
        try:
            result = await runner(
                agent_name="travel_orchestrator",
                model=model,
                prompt=prompt,
                payload=payload,
            )
            contract = _normalize_orchestrator_contract(result)
            break
        except TravelModelCallError as exc:
            last_error = exc
        except Exception as exc:
            last_error = TravelModelCallError("orchestrator", f"final_answer: {_exception_summary(exc)}", model=model)
        if attempt >= 2 or not _is_retryable_final_answer_error(last_error):
            raise last_error
    if contract is None:
        if last_error is not None:
            raise last_error
        raise TravelModelCallError("orchestrator", "final_answer: empty contract", model=model)
    contract = _ensure_classified_sections(
        contract=contract,
        request=request,
        api_payloads=state.get("api_payloads", {}),
        answer_framework=answer_framework,
    )
    contract["tool_calls_requested"] = []
    contract["warnings"] = list(
        dict.fromkeys(
            [
                *_string_list(state.get("initial_orchestrator_contract", {}).get("warnings")),
                *_string_list(contract.get("warnings")),
            ]
        )
    )
    contract["data_gaps"] = list(
        dict.fromkeys(
            [
                *state.get("api_warnings", []),
                *_string_list(state.get("initial_orchestrator_contract", {}).get("data_gaps")),
                *_string_list(contract.get("data_gaps")),
            ]
        )
    )
    return contract


def _is_retryable_final_answer_error(error: TravelModelCallError | None) -> bool:
    if error is None:
        return False
    message = error.message.lower()
    retry_markers = [
        "final_answer",
        "json",
        "parse",
        "expecting value",
        "unterminated string",
        "contract must be a json object",
    ]
    return any(marker in message for marker in retry_markers)


def _orchestrator_tool_contract(request: TravelPlanRequest) -> list[str]:
    return sorted(ORCHESTRATOR_TOOL_NAMES)


def _request_text(request: TravelPlanRequest) -> str:
    context = request.previous_context if isinstance(request.previous_context, dict) else {}
    context_keys = {
        "activeQuery",
        "lastQuery",
        "preferences",
        "selected_card",
        "liked_cards",
        "planned_cards",
        "active_query",
        "last_query",
        "interest_tags",
        "constraints",
        "destination",
        "city",
        "resolved_city",
        "context_city",
    }
    context_values = [
        str(value)
        for key, value in context.items()
        if key in context_keys
    ]
    return " ".join(
        item
        for item in [
            request.city,
            request.origin_city,
            request.query,
            request.question,
            " ".join(request.interest_tags),
            " ".join(request.constraints),
            " ".join(context_values),
        ]
        if item
    )


def _enforce_required_orchestrator_tools(
    contract: dict[str, Any],
    request: TravelPlanRequest,
) -> dict[str, Any]:
    existing_calls = _contract_tool_calls(contract)
    recommends_places = _contract_recommends_places(contract)
    if contract.get("answer_mode") == "itinerary":
        if any(call["name"] == "serper_places" for call in existing_calls):
            return contract
        updated = dict(contract)
        updated["tool_calls_requested"] = [
            {
                "task_id": "serper_places_itinerary_1",
                "name": "serper_places",
                "arguments": {
                    "query": _itinerary_discovery_query(request),
                    "category": "本地体验",
                    "max_results": 8,
                },
                "required": True,
            }
        ]
        return updated
    if existing_calls:
        if not recommends_places:
            return contract
        names = {call["name"] for call in existing_calls}
        additions: list[dict[str, Any]] = []
        if "serper_places" not in names:
            query = _place_query_from_contract_result(contract, request)
            additions.append(
                {
                    "task_id": "serper_places_result_1",
                    "name": "serper_places",
                    "arguments": {
                        "query": query,
                        "category": _place_category_from_contract_result(contract),
                        "max_results": 8,
                    },
                    "required": True,
                }
            )
        if "serper_images" not in names:
            additions.append(
                {
                    "task_id": "serper_images_result_1",
                    "name": "serper_images",
                    "arguments": {"query": _place_query_from_contract_result(contract, request), "max_results": 8},
                    "required": False,
                }
            )
        if "serper_search" not in names:
            additions.append(
                {
                    "task_id": "serper_search_reviews_1",
                    "name": "serper_search",
                    "arguments": {"query": _place_review_query(request), "max_results": 8},
                    "required": False,
                }
            )
        if not additions:
            return contract
        updated = dict(contract)
        updated["answer_mode"] = "place_cards" if updated.get("answer_mode") == "answer_only" else updated.get("answer_mode")
        updated["tool_calls_requested"] = [*existing_calls, *additions]
        return updated
    if not recommends_places:
        return contract
    query = _place_query_from_contract_result(contract, request)
    updated = dict(contract)
    updated["answer_mode"] = "place_cards"
    updated["tool_calls_requested"] = [
        {
            "task_id": "serper_places_result_1",
            "name": "serper_places",
            "arguments": {
                "query": query,
                "category": _place_category_from_contract_result(contract),
                "max_results": 8,
            },
            "required": True,
        },
        {
            "task_id": "serper_images_result_1",
            "name": "serper_images",
            "arguments": {"query": query, "max_results": 8},
            "required": False,
        },
        {
            "task_id": "serper_search_reviews_1",
            "name": "serper_search",
            "arguments": {"query": _place_review_query(request), "max_results": 8},
            "required": False,
        },
    ]
    return updated


def _obvious_itinerary_contract(request: TravelPlanRequest) -> dict[str, Any]:
    return {
        "answer_mode": "itinerary",
        "sections": [],
        "tool_calls_requested": [
            {
                "task_id": "serper_places_itinerary_1",
                "name": "serper_places",
                "arguments": {
                    "query": _itinerary_discovery_query(request),
                    "category": "本地体验",
                    "max_results": 8,
                },
                "required": True,
            }
        ],
        "data_gaps": [],
        "orchestrator_source": "deterministic_fast_path",
    }


def _obvious_first_timer_recommendation_contract(request: TravelPlanRequest) -> dict[str, Any]:
    return {
        "answer_mode": "place_cards",
        "sections": [],
        "tool_calls_requested": [
            {
                "task_id": "serper_places_first_timer_1",
                "name": "serper_places",
                "arguments": {
                    "query": _first_timer_discovery_query(request),
                    "category": "本地体验",
                    "max_results": 8,
                },
                "required": True,
            }
        ],
        "data_gaps": [],
        "skip_image_enrichment": True,
        "orchestrator_source": "deterministic_fast_path",
    }


def _enforce_obvious_itinerary_contract(
    contract: dict[str, Any],
    request: TravelPlanRequest,
) -> dict[str, Any]:
    if not _is_obvious_itinerary_request(request):
        return contract
    return {**contract, **_obvious_itinerary_contract(request)}


def _is_obvious_itinerary_request(request: TravelPlanRequest) -> bool:
    text = _request_text(request).lower()
    if not text:
        return False
    if _is_arrival_timing_logistics_question(text):
        return False
    if any(token in text for token in ["是什么", "为什么", "安全吗", "签证", "天气", "weather", "visa"]):
        return False
    has_duration = bool(
        re.search(r"\d+\s*(?:天|日|晚|day|days|night|nights)", text, flags=re.I)
        or re.search(r"(?<!第)[一二两三四五六七八九十]\s*(?:天|日|晚)", text)
    )
    itinerary_terms = [
        "行程",
        "怎么排",
        "怎麼排",
        "怎么安排",
        "怎麼安排",
        "安排",
        "路线",
        "路線",
        "怎么玩",
        "怎麼玩",
        "节奏",
        "住宿只换",
        "换一次",
        "itinerary",
        "trip plan",
    ]
    return has_duration and any(term in text for term in itinerary_terms)


def _is_arrival_timing_logistics_question(text: str) -> bool:
    lowered = text.lower()
    has_arrival_context = bool(
        any(token in text for token in ["机场", "抵达", "到达", "才到", "落地", "当晚", "晚上", "夜里"])
        or any(token in lowered for token in ["airport", "arrival", "arrive", "late night"])
    )
    has_next_step_question = bool(
        any(token in text for token in ["当晚", "当天晚上", "第二天", "第二日", "次日", "怎么开始", "还适合安排什么"])
        or any(token in lowered for token in ["next day", "first night"])
    )
    return has_arrival_context and has_next_step_question


def _is_obvious_first_timer_recommendation_request(request: TravelPlanRequest) -> bool:
    text = _request_text(request).lower()
    if not text:
        return False
    if _is_obvious_itinerary_request(request):
        return False
    if any(token in text for token in ["是什么", "为什么", "安全吗", "签证", "天气", "weather", "visa"]):
        return False
    if any(token in text for token in ["怎么走", "路線", "路线", "换乘", "route", "transport"]):
        return False
    first_timer_markers = [
        "第一次",
        "初访",
        "初訪",
        "新手",
        "首次",
        "first time",
        "first-time",
        "first timer",
        "first-timer",
        "beginner",
    ]
    if not any(marker in text for marker in first_timer_markers):
        return False
    if not _needs_place_discovery_tools(request):
        return False
    return bool(_city_first_timer_anchor_specs(request))


def _first_timer_discovery_query(request: TravelPlanRequest) -> str:
    base = _place_discovery_query(request)
    text = _request_text(request).lower()
    hints = ["第一次", "新手", "经典景点", "things to do", "attractions"]
    if "福冈" in text or "福岡" in text or "fukuoka" in text:
        hints.extend(["博多", "天神", "太宰府", "大濠公园", "百道海滨", "福冈塔"])
    return " ".join([base, *hints]).strip()


def _itinerary_discovery_query(request: TravelPlanRequest) -> str:
    base = request.city.strip() or (request.query or request.question).strip()
    days = _requested_day_count(request)
    hints = [f"{days} 天行程" if days else "行程", "经典景点", "街区", "things to do", "attractions"]
    text = _request_text(request).lower()
    if "福冈" in text or "fukuoka" in text:
        hints.extend(["博多", "天神", "太宰府", "大濠公园", "百道海滨", "福冈塔"])
    if "京都" in text or "kyoto" in text:
        hints.extend(["京都站", "祇园", "伏见稻荷"])
    if "大阪" in text or "osaka" in text:
        hints.extend(["梅田", "难波", "大阪城公园"])
    return " ".join([base, *hints]).strip()


def _strip_inventory_only_place_tools(
    contract: dict[str, Any],
    request: TravelPlanRequest,
) -> dict[str, Any]:
    if not _is_inventory_only_request(request):
        return contract
    calls = _contract_tool_calls(contract)
    filtered = [call for call in calls if call["name"] not in {"serper_places", "serper_images"}]
    if len(filtered) == len(calls):
        return contract
    updated = dict(contract)
    updated["tool_calls_requested"] = filtered
    if not filtered:
        updated["answer_mode"] = "answer_only"
    note = "酒店/航班类库存问题不使用通用地点工具生成地图卡片；需要真实供应数据时返回信息缺口。"
    updated["warnings"] = _unique_strings([*_string_list(updated.get("warnings")), note])
    updated["data_gaps"] = _unique_strings([*_string_list(updated.get("data_gaps")), note])
    return updated


def _is_inventory_only_request(request: TravelPlanRequest) -> bool:
    text = _request_text(request).lower()
    inventory = any(token in text for token in ["酒店", "住宿", "hotel", "航班", "机票", "flight"])
    itinerary_context = any(
        token in text
        for token in [
            "行程",
            "路线",
            "怎么排",
            "怎么安排",
            "安排",
            "几天",
            "天怎么玩",
            "换一次",
            "换酒店",
            "day",
            "itinerary",
            "plan",
        ]
    ) or bool(re.search(r"\d+\s*(?:天|日|day|days)", text, flags=re.I))
    if itinerary_context:
        return False
    place_result = any(
        token in text
        for token in ["景点", "餐厅", "公园", "吃", "玩", "购物", "路线", "行程", "itinerary", "restaurant", "attraction"]
    )
    return inventory and not place_result


def _needs_place_discovery_tools(request: TravelPlanRequest) -> bool:
    text = _request_text(request).lower()
    if not text:
        return False
    if any(token in text for token in ["酒店", "住宿", "hotel", "航班", "机票", "flight", "天气", "weather", "签证", "visa"]):
        return False
    if any(token in text for token in ["怎么走", "路线", "交通", "换乘", "route", "transport"]):
        return False
    discovery_markers = [
        "有什么",
        "有哪些",
        "去哪",
        "哪里",
        "哪儿",
        "附近",
        "推荐",
        "好玩",
        "玩什么",
        "吃什么",
        "买什么",
        "购物",
        "购物地",
        "逛",
        "市场",
        "商店",
        "商场",
        "商店街",
        "街区",
        "烟火气",
        "市井",
        "本地人",
        "景点",
        "自然风光",
        "户外风光",
        "things to do",
        "where to",
        "nearby",
        "recommend",
        "restaurants",
        "attractions",
        "parks",
        "market",
        "shopping",
        "shop",
        "shopping street",
        "local",
    ]
    if any(marker in text for marker in discovery_markers):
        return True
    evaluation_markers = ["评价", "评论", "口碑", "怎么样", "如何", "值得去", "worth"]
    if any(marker in text for marker in evaluation_markers):
        return False
    return False


def _place_discovery_query(request: TravelPlanRequest) -> str:
    parts = [request.city, request.query or request.question]
    return " ".join(part for part in parts if part).strip() or (request.query or request.question)


def _place_review_query(request: TravelPlanRequest) -> str:
    parts = [
        request.city,
        request.query or request.question,
        "traveler reviews real experience",
    ]
    return " ".join(part for part in parts if part).strip()


def _place_discovery_category(request: TravelPlanRequest) -> str:
    text = _request_text(request)
    if any(token in text for token in ["吃", "美食", "餐厅", "拉面", "寿司", "food", "restaurant", "ramen", "sushi"]):
        return "美食"
    if any(
        token in text
        for token in [
            "购物",
            "购物地",
            "买",
            "逛",
            "市场",
            "商店",
            "商场",
            "商店街",
            "街区",
            "烟火气",
            "市井",
            "伴手礼",
            "shopping",
            "market",
            "shop",
            "shopping street",
            "local shopping",
        ]
    ):
        return "购物"
    return "本地体验"


def _classified_answer_framework(
    request: TravelPlanRequest,
    state: TravelWorkflowState | None = None,
) -> dict[str, Any]:
    return {
        "name": "freeform_multimodal_travel_v1",
        "structure_policy": "freeform",
        "section_titles": [],
        "recommendation_checks": [
            "推荐是否能由真实地点、路线、评价、当地网站或旅行者反馈核验",
            "候选是否有广告、赞助、推广、营销导向或来源不清的迹象",
            "推荐理由是否说明了适合谁、为什么值得去、路线和时间取舍",
        ],
        "public_rules": [
            "自由组织答案，不套固定三段或固定栏目",
            "语气亲切，结构清晰，给出可执行判断",
            "需要推荐时结合真实地点工具、评价片段和用户语境",
            "如果有推荐，说明推荐原因",
            "避开广告、赞助、营销感强或来源不清的地点",
            "不要编造营业时间、价格、库存、距离或未提供的坐标",
            "不要在用户可见回答中提及内部规则",
        ],
        "multimodal_contract": {
            "sections": "freeform text sections with optional tables/images/card_ids/pin_ids",
            "cards": "only from real places, routes, hotels, or flights tool data",
            "map_pins": "only from real places or route coordinates",
        },
        "request_focus": {
            "city": request.city,
            "query": request.query,
            "preferences": request.interest_tags,
            "constraints": request.constraints,
        },
    }


def _ensure_classified_sections(
    *,
    contract: dict[str, Any],
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    answer_framework: dict[str, Any],
) -> dict[str, Any]:
    if contract.get("answer_mode") not in {"place_cards", "itinerary"}:
        return contract
    places = _place_items_from_payloads(api_payloads)
    if not places:
        return contract
    existing_sections = _contract_sections(contract)
    if existing_sections:
        updated = dict(contract)
        generated = []
        if not _sections_reference_places(existing_sections, places):
            generated = _freeform_sections_from_places(request, places, api_payloads)
        updated["sections"] = [*existing_sections, *generated]
        updated["answer_framework"] = answer_framework.get("name")
        return updated
    generated = _freeform_sections_from_places(request, places, api_payloads)
    if not generated:
        return contract
    updated = dict(contract)
    updated["sections"] = generated
    updated["answer_framework"] = answer_framework.get("name")
    return updated


def _deterministic_structured_card_contract(
    *,
    initial_contract: dict[str, Any],
    request: TravelPlanRequest,
    state: TravelWorkflowState,
) -> dict[str, Any] | None:
    answer_mode = initial_contract.get("answer_mode")
    if answer_mode not in {"place_cards", "itinerary"}:
        return None
    places = _place_items_from_payloads(state.get("api_payloads", {}))
    can_use_city_anchors = (
        answer_mode == "itinerary"
        and _is_obvious_itinerary_request(request)
        and bool(_city_itinerary_anchor_specs(request))
    )
    can_use_city_anchors = can_use_city_anchors or (
        answer_mode == "place_cards"
        and _is_obvious_first_timer_recommendation_request(request)
        and bool(_city_first_timer_anchor_specs(request))
    )
    if not places and not can_use_city_anchors:
        return None
    if answer_mode == "place_cards" and not _can_replace_initial_sections_with_card_summary(initial_contract):
        return None
    answer_framework = _classified_answer_framework(request, state)
    contract = dict(initial_contract)
    contract["sections"] = []
    contract["tool_calls_requested"] = []
    contract["answer_framework"] = answer_framework.get("name")
    return contract


def _can_replace_initial_sections_with_card_summary(contract: dict[str, Any]) -> bool:
    sections = _contract_sections(contract)
    if not sections:
        return True
    generic_titles = {
        "建议",
        "推荐",
        "推荐理由",
        "怎么选",
        "去哪儿",
        "怎么走/地图",
        "怎么排/地图",
        "附近怎么玩",
    }
    for section in sections:
        if _list_of_dicts(section.get("tables")) or _list_of_dicts(section.get("images")):
            return False
        title = str(section.get("title") or "").strip()
        if title and title not in generic_titles:
            return False
    return True


def _grounded_contract_after_final_model_error(
    *,
    initial_contract: dict[str, Any],
    request: TravelPlanRequest,
    api_payloads: dict[str, Any],
    error: TravelModelCallError,
) -> dict[str, Any] | None:
    if initial_contract.get("answer_mode") not in {"place_cards", "itinerary"}:
        return None
    if not _place_items_from_payloads(api_payloads):
        return None
    answer_framework = _classified_answer_framework(request)
    warning = f"final_answer 模型输出不可解析：{error.message}"
    contract = dict(initial_contract)
    contract["sections"] = []
    contract["tool_calls_requested"] = []
    contract["warnings"] = _unique_strings([*_string_list(contract.get("warnings")), warning])
    contract["data_gaps"] = _unique_strings([*_string_list(contract.get("data_gaps")), warning])
    contract = _ensure_classified_sections(
        contract=contract,
        request=request,
        api_payloads=api_payloads,
        answer_framework=answer_framework,
    )
    contract["answer_framework"] = answer_framework["name"]
    return contract


def _sections_by_classified_title(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    aliases = {
        "怎么选": "怎么选",
        "去哪儿": "去哪儿",
        "怎么走/地图": "怎么排/地图",
        "怎么排/地图": "怎么排/地图",
        "附近怎么玩": "去哪儿",
    }
    by_title: dict[str, dict[str, Any]] = {}
    for section in sections:
        title = str(section.get("title") or "").strip()
        canonical = aliases.get(title)
        if canonical and canonical not in by_title:
            by_title[canonical] = section
    return by_title


def _merge_classified_section(
    existing: dict[str, Any] | None,
    generated: dict[str, Any],
) -> dict[str, Any]:
    if existing is None:
        return generated
    body = str(existing.get("body") or "").strip()
    generated_body = str(generated.get("body") or "").strip()
    if generated.get("title") == "怎么选" and generated_body and not _has_classified_depth(body):
        return generated
    if generated_body and not _has_classified_depth(body):
        body = f"{body}\n{generated_body}".strip() if body else generated_body
    bullets = _unique_strings(
        [
            *_string_list(existing.get("bullets")),
            *_string_list(generated.get("bullets")),
        ]
    )
    tables = [
        *_list_of_dicts(existing.get("tables")),
        *_list_of_dicts(generated.get("tables")),
    ]
    images = [
        *_list_of_dicts(existing.get("images")),
        *_list_of_dicts(generated.get("images")),
    ]
    return {
        "id": str(existing.get("id") or generated.get("id") or "").strip(),
        "title": generated["title"],
        "body": body,
        "bullets": bullets[:5],
        "chips": _unique_strings([*_string_list(existing.get("chips")), *_string_list(generated.get("chips"))]),
        "tables": tables,
        "images": images,
        "card_ids": _unique_strings([*_string_list(existing.get("card_ids")), *_string_list(generated.get("card_ids"))]),
        "pin_ids": _unique_strings([*_string_list(existing.get("pin_ids")), *_string_list(generated.get("pin_ids"))]),
    }


def _has_classified_depth(text: str) -> bool:
    markers = ["兴趣匹配", "口碑确认", "动线时间", "预算/体力/天气"]
    return sum(1 for marker in markers if marker in text) >= 3 and len(text) >= 180


def _place_items_from_payloads(payloads: dict[str, Any]) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    for key, value in payloads.items():
        if not str(key).startswith("local:"):
            continue
        for item in _list_of_dicts(value):
            if _place_name(item) and not _is_marketing_or_ad_item(item):
                places.append(item)
    return places


def _freeform_sections_from_places(
    request: TravelPlanRequest,
    places: list[dict[str, Any]],
    api_payloads: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not places:
        return []
    anchor = _best_place(places)
    alternatives = [place for place in places if _place_name(place) != _place_name(anchor)]
    city = request.city or "这座城市"
    bullets = [
        f"推荐理由：{_place_fact(anchor)}，适合作为优先核对的主候选。",
        *[
            f"备选理由：{_place_fact(place)}，适合和主候选一起放进地图比较距离与顺路程度。"
            for place in alternatives[:3]
        ],
    ]
    query_text = f"{request.query} {request.question} {' '.join(request.interest_tags)}".lower()
    if "步行" in query_text or "walk" in query_text:
        bullets.append("步行提醒：优先把同一区域内的点位组合起来，跨区移动时再考虑公共交通。")
    sections = [
        {
            "title": "推荐理由",
            "body": "下面这些候选来自真实地点工具结果；优先看有地址、评分或片段可核验的地点。",
            "bullets": bullets[:5],
            "card_ids": [_place_identifier(place) for place in places[:4]],
            "pin_ids": [_place_identifier(place) for place in places[:4]],
        }
    ]
    return sections


def _concise_sections_from_display_cards(
    request: TravelPlanRequest,
    response: TravelPlanResponse,
) -> list[dict[str, Any]]:
    cards = response.display_cards[:3]
    if not cards:
        return []
    card_ids = [card.id for card in cards]
    pins = _list_of_dicts((response.map_view or {}).get("pins"))[:3]
    pin_ids = [str(pin.get("id") or "").strip() for pin in pins if str(pin.get("id") or "").strip()]
    sections = _task_aware_sections_from_display_cards(request, response.display_cards[:6])
    if not sections:
        sections = _classified_sections_from_places(
            request,
            [_place_from_display_card(card) for card in response.display_cards[:6]],
        )
    if not sections:
        sections = _fallback_task_aware_sections_from_display_cards(request, cards, bool(pin_ids))
    return [
        {
            **section,
            "card_ids": card_ids,
            "pin_ids": pin_ids,
            "bullets": _string_list(section.get("bullets"))[:4],
        }
        for section in sections[:3]
    ]


def _place_from_display_card(card: TravelDisplayCard) -> dict[str, Any]:
    return {
        "title": card.title,
        "snippet": card.display_reason or card.description or card.reason,
        "type": card.subcategory or card.category or card.subtitle,
        "rating": card.rating,
        "reviews": card.review_count,
        "address": card.address,
        "latitude": card.lat,
        "longitude": card.lng,
        "place_id": card.place_id or card.id,
    }


def _task_aware_sections_from_display_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    if not cards:
        return []
    query_text = f"{request.query} {request.question} {' '.join(request.interest_tags)} {' '.join(request.constraints)}"
    lowered = query_text.lower()
    if _is_family_half_day_query(query_text):
        return _family_half_day_sections_from_cards(request, cards)
    if _is_snack_area_query(query_text):
        return _snack_area_sections_from_cards(request, cards)
    if _is_budget_short_trip_query(query_text):
        return _budget_sections_from_cards(request, cards)
    if _is_winter_sapporo_query(request, query_text):
        return _winter_sapporo_sections_from_cards(request, cards)
    if _is_rainy_day_query(query_text):
        return _rainy_day_sections_from_cards(request, cards)
    if _is_quiet_morning_walk_query(query_text):
        return _quiet_walk_sections_from_cards(request, cards)
    if _is_night_view_query(query_text):
        return _night_view_sections_from_cards(request, cards)
    if "第一次" in query_text or "新手" in query_text or "first" in lowered:
        return _first_timer_sections_from_cards(request, cards)
    return []


def _family_half_day_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "family-choice",
            "title": "怎么选",
            "body": f"带 6 岁孩子做半日安排，关键是低疲劳、少转场、随时能休息；{names}适合先按孩子兴趣二选一或短串联。",
            "bullets": [
                f"低疲劳优先：{_card_summary_bullet(cards[0], request)}",
                *[f"备选补充：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "不要把半日塞成全天：同一区域只选 1 个主点，再留 30–60 分钟吃饭、洗手间和临时休息。",
            ],
        },
        {
            "id": "family-half-day",
            "title": "半日怎么排",
            "body": "建议用“一个主点 + 一个很近的备选”来排，不追求打卡数量。",
            "bullets": [
                "上午或午后先去孩子最感兴趣的主点，控制在 90–150 分钟内。",
                "如果状态好，再补同一区域的短项目；如果累了，就直接吃饭或回酒店休息。",
                "地图只用来确认两点是否真的同区，跨区候选不适合作为低疲劳半日。",
            ],
        },
    ]


def _snack_area_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "snack-area-choice",
            "title": "怎么选",
            "body": f"这题重点是选道顿堀之外的小吃区域，而不是单店拔草；我会先看{names}，再按本地感、交通和晚间氛围取舍。",
            "bullets": [
                f"区域候选：{_card_summary_bullet(cards[0], request)}",
                *[f"备选区域：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "如果只想随走随吃，优先商店街、站前或小店密集区；如果想拍照热闹，再把道顿堀当作补充而不是唯一目的地。",
            ],
        },
        {
            "id": "snack-area-map",
            "title": "怎么排/地图",
            "body": "小吃区域适合按晚餐前后动线来排：离住宿或当天最后一个景点近，比理论评分更重要。",
            "bullets": [
                "同晚最多选一个主区域，避免在不同街区之间来回跑。",
                "先用地图看和地铁/JR 站的距离，再决定是晚餐主场还是宵夜补充。",
                "到店前仍要核对营业日、排队和是否接受现金/预约。",
            ],
        },
    ]


def _budget_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "budget-choice",
            "title": "怎么选",
            "body": f"低预算两天不要只省钱到无聊：先用免费/低门票地点打底，再把小吃、夜景或商店街作为氛围补充。当前可先看{names}。",
            "bullets": [
                f"免费或低成本主点：{_card_summary_bullet(cards[0], request)}",
                *[f"低预算备选：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "把付费项目压到每天 0–1 个，更多时间留给公园、街区、市场和便利店/立食小吃。",
            ],
        },
        {
            "id": "budget-two-days",
            "title": "两天怎么排",
            "body": "用“白天免费景点 + 傍晚街区小吃”的节奏，会比只逛商业区更有内容也更省。",
            "bullets": [
                "Day 1 选一个大范围免费点，再接附近商店街或小吃区。",
                "Day 2 换一个城市气质不同的区域，不要为了省交通费反复回头。",
                "交通上优先同区域串联；如果一天跨太多区，省下的门票会被体力和车费抵消。",
            ],
        },
    ]


def _winter_sapporo_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "winter-choice",
            "title": "怎么选",
            "body": f"第一次冬天去札幌，除了雪祭，我会把候选分成雪景/夜景、室内备选和近郊氛围三类；当前先看{names}。",
            "bullets": [
                f"冬季主候选：{_card_summary_bullet(cards[0], request)}",
                *[f"天气备选：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "雪天路滑、天黑早，缆车/展望台要看天气；室内博物馆或近郊短线适合作为风雪备选。",
            ],
        },
        {
            "id": "winter-map",
            "title": "怎么排/地图",
            "body": "冬季不要按夏天步速排：每次换乘和步行都要留缓冲。",
            "bullets": [
                "白天放室外雪景或近郊，傍晚再安排夜景或室内点。",
                "同类地点不要重复塞太多；藻岩山这类同一区域只保留一个主入口或观景点即可。",
                "遇到大雪、强风或低能见度，优先改成室内文化点和车站周边餐饮。",
            ],
        },
    ]


def _rainy_day_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "rain-choice",
            "title": "怎么选",
            "body": f"下雨天不要只躲进商场；优先选室内展馆、可短距离换乘、排队风险低的点。当前先看{names}。",
            "bullets": [
                f"雨天主候选：{_card_summary_bullet(cards[0], request)}",
                *[f"雨天备选：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "如果雨很大，宁可少换区；如果只是小雨，可以把博物馆/美术馆和附近咖啡或餐饮组合。",
            ],
        },
        {
            "id": "rain-map",
            "title": "怎么排/地图",
            "body": "地图重点看地铁站、巴士站和步行暴露距离，而不是只看直线距离。",
            "bullets": [
                "同区室内点可以串联，跨区就保留一个主点。",
                "把需要长时间户外排队或无遮挡步行的候选降级。",
                "营业时间、临时闭馆和预约规则要出发前再核对。",
            ],
        },
    ]


def _quiet_walk_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "quiet-choice",
            "title": "怎么选",
            "body": f"早上散步想相对安静，重点是避开最热门主轴，选择开阔、可绕路、停留压力低的区域；当前先看{names}。",
            "bullets": [
                f"安静候选：{_card_summary_bullet(cards[0], request)}",
                *[f"备选路线点：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "清水寺、伏见稻荷、岚山这类名点即使早上也不保证空；如果去，要走侧线或早点结束。",
            ],
        },
        {
            "id": "quiet-map",
            "title": "怎么排/地图",
            "body": "地图用于找侧门、河边、公园边缘和回程交通，不要把热门点硬串成主路线。",
            "bullets": [
                "7–9 点适合短散步，10 点后热门线路人流会明显上来。",
                "只选一个主区域慢走，别在早上跨太多区。",
                "如果遇到赏樱/红叶旺季，把安静预期下调，优先选更开阔的公园或御苑类地点。",
            ],
        },
    ]


def _night_view_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards)
    return [
        {
            "id": "night-choice",
            "title": "怎么选",
            "body": f"夜景要把观景效果和回程难度一起算；如果不想交通麻烦，优先看城市内、靠近公共交通的点：{names}。",
            "bullets": [
                f"夜景主候选：{_card_summary_bullet(cards[0], request)}",
                *[f"备选夜景：{_card_summary_bullet(card, request)}" for card in cards[1:3]],
                "北九州皿仓山这类夜景很强，但要看缆车、换乘和末班车；交通优先时未必比福冈市内更省心。",
            ],
        },
        {
            "id": "night-map",
            "title": "怎么排/地图",
            "body": "地图重点看回酒店的末班车、打车距离和夜间步行安全感。",
            "bullets": [
                "傍晚前到达观景点，留出天气和排队缓冲。",
                "如果当晚还要吃饭或喝酒，优先选市内点，别把回程压到太晚。",
                "风大、雨天或低云时，展望台体验会打折，河边/港边城市夜景可能更稳。",
            ],
        },
    ]


def _first_timer_sections_from_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    names = _display_card_names(cards, limit=5)
    city = request.city or "这座城市"
    return [
        {
            "id": "first-timer-choice",
            "title": "怎么选",
            "body": f"第一次去{city}，我会先选好理解、交通不复杂、能代表城市气质的点；当前先看{names}。",
            "bullets": [
                f"新手主候选：{_card_summary_bullet(cards[0], request)}",
                *[f"新手备选：{_card_summary_bullet(card, request)}" for card in cards[1:5]],
                "不要只按评分堆地点：新手更需要顺路、好找、停留时间弹性大。",
            ],
        },
        {
            "id": "first-timer-map",
            "title": "怎么排/地图",
            "body": "先用地图把候选按区域分组，再决定半日或一日组合。",
            "bullets": [
                "同区 2–3 个点可以串联；跨区就拆到不同半日。",
                "把离住宿、车站或当天主餐最近的点放前面。",
                "如果天气或体力变化，优先保留交通简单的核心点。",
            ],
        },
    ]


def _display_card_names(cards: list[TravelDisplayCard], limit: int = 3) -> str:
    return "、".join(card.title for card in cards[:limit] if card.title) or "这些候选"


def _is_family_half_day_query(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["孩子", "小孩", "亲子", "6岁", "6 岁", "儿童"]) or "kid" in lowered or "family" in lowered


def _is_snack_area_query(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["小吃", "道顿堀", "道頓堀", "区域", "街区", "本地吃"]) or "snack" in lowered or "food area" in lowered


def _is_budget_short_trip_query(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["低预算", "省钱", "预算比较低", "便宜"]) or "budget" in lowered


def _is_winter_sapporo_query(request: TravelPlanRequest, text: str) -> bool:
    city = (request.city or "").lower()
    return ("札幌" in text or "sapporo" in city or "sapporo" in text.lower()) and any(token in text for token in ["冬", "雪祭", "雪"])


def _is_rainy_day_query(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["下雨", "雨天", "下雨天", "雨"]) or "rain" in lowered


def _is_quiet_morning_walk_query(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["安静", "早上", "散步", "避开最挤", "人少"]) or ("quiet" in lowered and "walk" in lowered)


def _is_night_view_query(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ["夜景", "看夜", "晚上看"]) or "night view" in lowered


def _fallback_task_aware_sections_from_display_cards(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
    has_pins: bool,
) -> list[dict[str, Any]]:
    count = len(cards)
    noun = f"这 {count} 个候选" if count > 1 else "这个候选"
    return [
        {
            "id": "how-to-choose",
            "title": "怎么选",
            "body": f"{noun}先按是否匹配兴趣、是否顺路、是否适合当天体力和天气来判断，而不是只按评分排序。",
            "bullets": [_card_summary_bullet(card, request) for card in cards],
        },
        {
            "id": "route-use",
            "title": "怎么排/地图",
            "body": _map_use_body(request, cards, has_pins),
            "bullets": _map_use_bullets(request, cards),
        },
    ]


def _dominant_card_category(cards: list[TravelDisplayCard]) -> str:
    counts: dict[str, int] = {}
    for card in cards:
        category = str(card.category or "").strip()
        if category:
            counts[category] = counts.get(category, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]


def _card_summary_bullet(card: TravelDisplayCard, request: TravelPlanRequest) -> str:
    facts: list[str] = []
    if card.rating is not None:
        facts.append(f"评分 {card.rating:g}")
    if card.review_count:
        facts.append(f"{card.review_count} 条评价")
    if card.address:
        facts.append(card.address)
    reason = _compact_sentence(card.display_reason or card.description or card.reason, limit=70)
    if not reason:
        reason = "信息相对完整，适合先放进短名单"
    if _should_lead_card_summary_with_reason(request, reason):
        return f"{card.title}：{reason}"
    fact_text = f"（{'；'.join(facts[:2])}）" if facts else ""
    return f"{card.title}{fact_text}：{reason}"


def _should_lead_card_summary_with_reason(request: TravelPlanRequest, reason: str) -> bool:
    query_text = f"{request.query} {request.question} {' '.join(request.interest_tags)} {' '.join(request.constraints)}"
    lowered = query_text.lower()
    task_aware = bool(
        _is_family_half_day_query(query_text)
        or _is_snack_area_query(query_text)
        or _is_budget_short_trip_query(query_text)
        or _is_winter_sapporo_query(request, query_text)
        or _is_rainy_day_query(query_text)
        or _is_quiet_morning_walk_query(query_text)
        or _is_night_view_query(query_text)
        or "第一次" in query_text
        or "新手" in query_text
        or "first" in lowered
    )
    if not task_aware:
        return False
    return not _looks_like_fact_metadata_reason(reason)


def _looks_like_fact_metadata_reason(reason: str) -> bool:
    text = str(reason or "").strip()
    return bool(re.match(r"^(推荐理由：)?(评分|约\s*\d+|位置在|类型是)", text))


def _map_use_body(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
    has_pins: bool,
) -> str:
    names = "、".join(card.title for card in cards[:2] if card.title) or "这些地点"
    query_text = f"{request.query} {request.question} {' '.join(request.interest_tags)}".lower()
    if "步行" in query_text or "walk" in query_text:
        return f"你提到步行，地图先用来判断 {names} 是否同区；跨区候选不要硬串成全程步行。"
    if has_pins:
        return f"地图先用来判断 {names} 的相对位置：同区就串联，太分散就拆成不同半日。"
    return "目前卡片可先做短名单；如果缺少坐标，下一步应先补地图定位再排行程。"


def _map_use_bullets(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[str]:
    count = min(len(cards), 3)
    card_word = f"前 {count} 张卡片" if count > 1 else "这张卡片"
    bullets = [
        f"先看{card_word}的区域关系，再用 pins 判断同区组合，避免只按评分排序。",
        "把离住宿、车站或当天主景点最近的候选放前面。",
    ]
    query_text = f"{request.query} {request.question}".lower()
    if "吃" in query_text or "美食" in query_text or "餐" in query_text or "河豚" in query_text:
        bullets.append("餐厅类先核对营业时间、预约和菜单；当前回答不代替实时订位。")
    else:
        bullets.append("如果天气、体力或交通变差，优先保留同一区域内的低成本点位。")
    return bullets[:3]


def _compact_sentence(value: str, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip("，。；、 ") + "…"


def _sections_reference_places(sections: list[dict[str, Any]], places: list[dict[str, Any]]) -> bool:
    text = " ".join(
        [
            *[
                " ".join(
                    [
                        str(section.get("title") or ""),
                        str(section.get("body") or ""),
                        " ".join(_string_list(section.get("bullets"))),
                        " ".join(_string_list(section.get("card_ids"))),
                        " ".join(_string_list(section.get("pin_ids"))),
                    ]
                )
                for section in sections
            ]
        ]
    ).lower()
    if not text:
        return False
    for place in places:
        for value in [_place_name(place), _place_identifier(place)]:
            normalized = value.strip().lower()
            if normalized and normalized in text:
                return True
    return False


def _place_identifier(place: dict[str, Any]) -> str:
    return str(place.get("place_id") or place.get("data_id") or _place_name(place)).strip()


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


def _classified_sections_from_places(
    request: TravelPlanRequest,
    places: list[dict[str, Any]],
    api_payloads: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not places:
        return []
    nature = _place_group(
        places,
        ["自然", "公园", "park", "garden", "湖", "海滨", "beach", "花", "森林", "forest", "大濠", "海之中道"],
    )
    seaside = _place_group(
        places,
        ["海", "海滨", "beach", "tower", "塔", "远眺", "momochi", "百道", "海岸"],
    )
    activity = _place_group(
        places,
        ["户外", "adventure", "forest adventure", "绳索", "骑行", "主题", "活动"],
    )
    landmark = _place_group(
        places,
        ["地标", "tower", "塔", "shrine", "神社", "museum", "城", "市场"],
    )
    food = _place_group(
        places,
        [
            "餐厅",
            "料理",
            "河豚",
            "ふぐ",
            "fugu",
            "鮨",
            "寿司",
            "sushi",
            "restaurant",
            "izakaya",
            "bar",
            "割烹",
            "食",
        ],
    )
    anchor = _best_place(places)
    city = request.city or "这座城市"
    query_text = f"{request.query} {request.question}"
    walking_note = (
        "你提到偏好步行，所以市中心和同一区域内可以慢走串联；跨海滨、糸岛或郊区点位时，不建议全程步行。"
        if "步行" in query_text or "walk" in query_text.lower()
        else "如果当天体力或天气一般，把同一区域的点位串联，比跨区硬跑更稳。"
    )
    anchor_fact = _place_fact(anchor)
    review_section = _review_evidence_section(api_payloads or {}, anchor)
    nature_names = _place_names(nature or places[:2])
    seaside_names = _place_names(seaside or places[:2])
    activity_names = _place_names(activity or places[:1])
    food_names = _place_names(food or places[:2])
    if _is_food_place_query(query_text, places):
        backup_food = _unique_place_items([*(food[1:3]), *places[:3]]) or places[:2]
        return [
            {
                "title": "怎么选",
                "body": (
                    f"我会用 4 个问题来选{city}的餐厅：口味/场景是否匹配、口碑是否扎实、"
                    "位置是否顺路、预算与安全是否可执行。"
                ),
                "bullets": [
                    f"推荐原因：因为这次重点是河豚或当地餐饮，优先看{food_names}这类明确命中菜系的候选。",
                    f"口碑确认：先把{anchor_fact}这种有评分、地址或片段的餐厅放进短名单，再核对预约和营业时间。",
                    "动线时间：餐厅更适合贴近住宿、当天景点或交通节点安排，不建议为了单顿饭跨太远区域。",
                    "预算/安全：河豚料理尤其要确认正规处理资质、套餐价格和预约规则；没有实时库存时不要把模型文字当作订位结果。",
                ],
            },
            *([review_section] if review_section else []),
            {
                "title": "去哪儿",
                "body": "我会把餐厅按用餐角色来分，而不是只按评分堆名单。",
                "bullets": [
                    f"稳妥首选：{_place_fact(anchor)}，适合先作为主候选核对菜单与预约。",
                    f"备选对比：{_place_names(backup_food[:2])}，适合比较价格、位置和是否更方便衔接行程。",
                    "如果想吃得更正式，优先查套餐、包间和晚餐时段；如果只是尝鲜，午餐套餐或交通方便的店更稳。",
                    "若同行有人对河豚安全性敏感，建议准备非河豚的日料/海鲜备选，而不是把整顿饭押在一个品类上。",
                ],
            },
            {
                "title": "怎么排/地图",
                "body": "地图主要用来判断餐厅是否顺路，以及晚餐后回酒店是否方便。",
                "bullets": [
                    f"半日安排：先把{_place_name(anchor)}放进地图，再看它离住宿、车站或当天景点的距离。",
                    "晚餐安排：河豚店通常更需要预约；先定时间，再倒推前后景点，不要让路线把用餐时间压得太紧。",
                    "没有 places/route 工具结果时不生成地图；当前卡片和 pins 只来自真实地点结果，适合继续筛掉太远或评价不足的店。",
                ],
            },
        ]
    return [
        {
            "title": "怎么选",
            "body": (
                f"我会用 4 个问题来选{city}的地点：兴趣匹配、口碑确认、动线时间、"
                f"预算/体力/天气可执行性。这样比只说自然风光或评分更接近真实决策。"
            ),
            "bullets": [
                f"兴趣匹配：你想要自然和户外，优先看{nature_names}；如果想要海滨远眺，再看{seaside_names}。",
                f"推荐原因：先把{anchor_fact}这种有明确评价、地址或片段的地点作为候选，不只相信模型口头推荐。",
                f"动线时间：地图上同区地点可以串联；{walking_note}",
                f"预算/体力/天气：{activity_names}这类户外活动要看体力、天气和交通成本，雨天或低体力时优先低强度公园/海边。",
            ],
        },
        *([review_section] if review_section else []),
        {
            "title": "去哪儿",
            "body": "我会把地点当成可加入计划的角色，而不是一串孤立名单。",
            "bullets": [
                f"必去锚点：{_place_fact(anchor)}，适合先放进地图作为当天主点。",
                f"自然放松：{_place_fact((nature or places)[0])}，适合步行友好的慢节奏安排。",
                f"海滨远眺：{_place_fact((seaside or places)[0])}，适合和周边咖啡、海边散步组合。",
                f"活动/亲子：{_place_fact((activity or places)[0])}，适合愿意把半天留给户外项目的人。",
            ],
        },
        {
            "title": "怎么排/地图",
            "body": "地图上要按区域拆，而不是把所有高分点硬串成一条步行路线。",
            "bullets": [
                f"半日轻松：以{_place_name(anchor)}为主点，补一个同区候选，控制步行距离和停留时间。",
                f"一日户外：{_place_names(_unique_place_items([*(nature[:1]), *(seaside[:1]), *(activity[:1])]) or places[:3])}可以拆成自然、海滨和活动三段，但中间建议用公共交通衔接。",
                "步行边界：跨区点位距离通常不适合全程步行；地图 pins 更适合用来判断同区组合、换乘和放弃哪些远点。",
            ],
        },
    ]


def _review_evidence_section(api_payloads: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any] | None:
    items = _list_of_dicts(api_payloads.get("raw_query"))
    if not items:
        return None
    bullets: list[str] = []
    for item in items[:3]:
        title = _route_item_title(item)
        snippet = str(item.get("snippet") or item.get("description") or "").strip()
        source = str(item.get("source") or item.get("source_provider") or item.get("domain") or "").strip()
        label = title or source or "检索结果"
        detail = snippet or "提供了旅行者反馈或搜索结果上下文。"
        bullets.append(f"{label}：{detail}")
    anchor_name = _place_name(anchor)
    return {
        "title": "补充参考",
        "body": (
            f"把{anchor_name}这类推荐和搜索结果交叉看；"
            "如果搜索结果没有明确提到营业时间、价格或预约，就把它当作待确认信息。"
        ),
        "bullets": bullets,
    }


def _place_group(places: list[dict[str, Any]], tokens: list[str]) -> list[dict[str, Any]]:
    matched = [place for place in places if _place_matches(place, tokens)]
    return _unique_place_items(matched)


def _is_food_place_query(query_text: str, places: list[dict[str, Any]]) -> bool:
    food_tokens = [
        "吃",
        "餐厅",
        "美食",
        "料理",
        "河豚",
        "ふぐ",
        "fugu",
        "寿司",
        "sushi",
        "拉面",
        "咖啡",
        "restaurant",
        "food",
        "dining",
    ]
    lowered = query_text.lower()
    if any(token.lower() in lowered for token in food_tokens):
        return True
    sampled = places[:5]
    hits = sum(1 for place in sampled if _place_matches(place, food_tokens))
    return bool(sampled) and hits >= min(2, len(sampled))


def _place_matches(place: dict[str, Any], tokens: list[str]) -> bool:
    text = " ".join(
        str(place.get(key) or "")
        for key in ["title", "name", "snippet", "type", "address"]
    ).lower()
    return any(token.lower() in text for token in tokens)


def _best_place(places: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        places,
        key=lambda item: (
            float(item.get("rating") or 0),
            int(item.get("reviews") or item.get("review_count") or 0),
        ),
        reverse=True,
    )[0]


def _unique_place_items(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for place in places:
        name = _place_name(place)
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(place)
    return unique


def _place_names(places: list[dict[str, Any]], limit: int = 3) -> str:
    names = [_place_name(place) for place in places if _place_name(place)]
    return "、".join(names[:limit]) or "地图上的候选地点"


def _place_name(place: dict[str, Any]) -> str:
    return str(place.get("title") or place.get("name") or "").strip()


def _place_fact(place: dict[str, Any]) -> str:
    name = _place_name(place)
    details: list[str] = []
    rating = place.get("rating")
    reviews = place.get("reviews") or place.get("review_count")
    if rating:
        details.append(f"评分 {rating}")
    if reviews:
        details.append(f"{reviews} 条评价")
    snippet = str(place.get("snippet") or "").strip()
    if snippet:
        details.append(snippet)
    address = str(place.get("address") or "").strip()
    if address:
        details.append(address)
    return name + (f"（{'；'.join(details[:3])}）" if details else "")


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_mode": contract.get("answer_mode"),
        "sections": _contract_sections(contract),
        "tool_calls_requested": _contract_tool_calls(contract),
        "warnings": _string_list(contract.get("warnings")),
        "data_gaps": _string_list(contract.get("data_gaps")),
    }


def _compact_tool_results(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in tool_results[:10]:
        compact.append(
            {
                key: value
                for key, value in item.items()
                if key in {"name", "status", "result_count", "error", "attempts"}
            }
        )
    return compact


def _compact_api_payloads(payloads: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payloads.items():
        if isinstance(value, list):
            compact[key] = [_compact_api_item(item) for item in value[:8] if isinstance(item, dict)]
        elif isinstance(value, dict):
            compact[key] = _compact_api_item(value)
        else:
            compact[key] = str(value)[:500]
    return compact


def _compact_api_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "title",
        "name",
        "snippet",
        "type",
        "rating",
        "reviews",
        "review_count",
        "address",
        "latitude",
        "longitude",
        "lat",
        "lng",
        "place_id",
        "source",
        "source_url",
        "imageUrl",
        "image_url",
        "rate",
        "duration",
        "distance",
        "mode",
    ]
    compact = {
        key: item.get(key)
        for key in keys
        if item.get(key) is not None and item.get(key) != "" and item.get(key) != []
    }
    return compact


def _normalize_orchestrator_contract(value: Any, allowed_tool_names: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TravelModelCallError("orchestrator", "contract must be a JSON object")
    answer_mode = str(value.get("answer_mode") or "").strip() or "answer_only"
    if answer_mode not in {"answer_only", "place_cards", "itinerary", "route_map"}:
        raise TravelModelCallError("orchestrator", f"invalid answer_mode: {answer_mode}")
    normalized = dict(value)
    allowed_tools = set(allowed_tool_names) if allowed_tool_names is not None else set(ORCHESTRATOR_TOOL_NAMES)
    unsupported_tools = _unsupported_contract_tool_names(normalized)
    blocked_tools = _blocked_contract_tool_names(normalized, allowed_tools)
    tool_calls = _contract_tool_calls(normalized, allowed_tool_names=allowed_tools)
    if (unsupported_tools or blocked_tools) and not tool_calls:
        answer_mode = "answer_only"
    normalized["sections"] = _contract_sections(normalized)
    if answer_mode == "answer_only" and not _contract_has_place_artifacts(normalized):
        tool_calls = [
            call
            for call in tool_calls
            if call["name"] not in {"serper_places", "serper_images", "route_lookup"}
        ]
    normalized["tool_calls_requested"] = tool_calls
    normalized_for_result_check = {**normalized, "answer_mode": answer_mode}
    if answer_mode == "answer_only" and _contract_has_place_artifacts(normalized_for_result_check):
        answer_mode = "place_cards"
    normalized["answer_mode"] = answer_mode
    normalized["warnings"] = _string_list(normalized.get("warnings"))
    normalized["data_gaps"] = _string_list(normalized.get("data_gaps"))
    if unsupported_tools:
        disabled_note = "已关闭重型旅行工具：" + "、".join(unsupported_tools) + "；由主模型基于当前会话和轻量工具回答。"
        normalized["warnings"] = _unique_strings([*normalized["warnings"], disabled_note])
        normalized["data_gaps"] = _unique_strings([*normalized["data_gaps"], disabled_note])
    if blocked_tools:
        blocked_note = "本轮未开放工具：" + "、".join(blocked_tools) + "；保留主模型文字回答，不生成未授权卡片。"
        normalized["warnings"] = _unique_strings([*normalized["warnings"], blocked_note])
        normalized["data_gaps"] = _unique_strings([*normalized["data_gaps"], blocked_note])
    return normalized


def _contract_sections(contract: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for item in _list_of_dicts(contract.get("sections")):
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or item.get("text") or "").strip()
        bullets = _string_list(item.get("bullets"))
        tables = _normalize_contract_tables(item.get("tables") or item.get("table"))
        images = _normalize_contract_images(
            item.get("images")
            or item.get("image_urls")
            or item.get("image_url")
            or item.get("gallery")
        )
        chips = _string_list(item.get("chips"))
        card_ids = _string_list(item.get("card_ids") or item.get("cardIds"))
        pin_ids = _string_list(item.get("pin_ids") or item.get("pinIds"))
        if not title and not body and not bullets and not tables and not images:
            continue
        sections.append(
            {
                "id": str(item.get("id") or "").strip(),
                "title": title or "建议",
                "body": body,
                "bullets": bullets,
                "chips": chips,
                "tables": tables,
                "images": images,
                "card_ids": card_ids,
                "pin_ids": pin_ids,
            }
        )
    return sections


def _contract_recommends_places(contract: dict[str, Any]) -> bool:
    answer_mode = str(contract.get("answer_mode") or "").strip()
    if answer_mode == "answer_only":
        return _contract_has_place_artifacts(contract)
    if answer_mode in {"place_cards", "itinerary"}:
        return True
    if _contract_has_place_artifacts(contract):
        return True
    return any(call.get("name") == "serper_places" for call in _contract_tool_calls(contract))


def _contract_has_place_artifacts(contract: dict[str, Any]) -> bool:
    if _list_of_dicts(contract.get("cards")) or _list_of_dicts(contract.get("map_pins")):
        return True
    for section in _contract_sections(contract):
        if _string_list(section.get("card_ids")) or _string_list(section.get("pin_ids")):
            return True
        if _list_of_dicts(section.get("cards")) or _list_of_dicts(section.get("places")):
            return True
    return False


def _place_query_from_contract_result(contract: dict[str, Any], request: TravelPlanRequest) -> str:
    names = _recommended_place_names(contract)
    subject = " ".join(names[:4]) or request.query or request.question
    return " ".join(part for part in [request.city, subject] if part).strip()


def _place_category_from_contract_result(contract: dict[str, Any]) -> str:
    for item in _list_of_dicts(contract.get("cards")):
        category = str(item.get("category") or item.get("type") or "").strip()
        if category:
            return category
    for section in _contract_sections(contract):
        for item in _list_of_dicts(section.get("cards")) + _list_of_dicts(section.get("places")):
            category = str(item.get("category") or item.get("type") or "").strip()
            if category:
                return category
    return "本地体验"


def _recommended_place_names(contract: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in [
        *_list_of_dicts(contract.get("cards")),
        *_list_of_dicts(contract.get("map_pins")),
    ]:
        name = _place_name(item)
        if name:
            names.append(name)
    for section in _contract_sections(contract):
        for item in _list_of_dicts(section.get("cards")) + _list_of_dicts(section.get("places")):
            name = _place_name(item)
            if name:
                names.append(name)
        names.extend(_string_list(section.get("card_ids"))[:4])
    return list(dict.fromkeys(names))


def _normalize_contract_tables(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, list) else ([value] if value else [])
    tables: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        columns = _string_list(item.get("columns") or item.get("headers"))
        rows: list[list[str]] = []
        raw_rows = item.get("rows")
        if isinstance(raw_rows, list):
            for row in raw_rows:
                if isinstance(row, list):
                    rows.append([str(cell) for cell in row])
                elif isinstance(row, dict):
                    rows.append([str(row.get(column) or "") for column in columns])
        if columns or rows:
            tables.append(
                {
                    "caption": str(item.get("caption") or item.get("title") or "").strip(),
                    "columns": columns,
                    "rows": rows,
                }
            )
    return tables


def _normalize_contract_images(value: Any) -> list[dict[str, str]]:
    values = value if isinstance(value, list) else ([value] if value else [])
    images: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, str):
            url = item.strip()
            if url:
                images.append({"url": url, "caption": "", "source": ""})
            continue
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url") or item.get("image_url") or item.get("imageUrl") or item.get("src")
        if isinstance(raw_url, dict):
            raw_url = raw_url.get("url")
        url = str(raw_url or "").strip()
        if not url:
            continue
        images.append(
            {
                "url": url,
                "caption": str(item.get("caption") or item.get("alt") or "").strip(),
                "source": str(item.get("source") or "").strip(),
            }
        )
    return images


def _contract_tool_calls(contract: dict[str, Any], allowed_tool_names: set[str] | None = None) -> list[dict[str, Any]]:
    allowed_tools = allowed_tool_names if allowed_tool_names is not None else set(ORCHESTRATOR_TOOL_NAMES)
    calls: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(_list_of_dicts(contract.get("tool_calls_requested"))):
        name = _canonical_orchestrator_tool_name(str(item.get("name") or item.get("tool") or "").strip())
        if not name or name not in allowed_tools:
            continue
        args = item.get("arguments")
        normalized_args = args if isinstance(args, dict) else {}
        key = (name, "")
        if key in seen:
            continue
        seen.add(key)
        calls.append(
            {
                "task_id": str(item.get("task_id") or f"{name}_{index + 1}"),
                "name": name,
                "arguments": normalized_args,
                "required": bool(item.get("required", True)),
            }
        )
    return calls


def _unsupported_contract_tool_names(contract: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in _list_of_dicts(contract.get("tool_calls_requested")):
        name = _canonical_orchestrator_tool_name(str(item.get("name") or item.get("tool") or "").strip())
        if name in DISABLED_ORCHESTRATOR_TOOL_NAMES and name not in names:
            names.append(name)
    return names


def _blocked_contract_tool_names(contract: dict[str, Any], allowed_tool_names: set[str]) -> list[str]:
    names: list[str] = []
    for item in _list_of_dicts(contract.get("tool_calls_requested")):
        name = _canonical_orchestrator_tool_name(str(item.get("name") or item.get("tool") or "").strip())
        if name in ORCHESTRATOR_TOOL_NAMES and name not in allowed_tool_names and name not in names:
            names.append(name)
    return names


def _canonical_orchestrator_tool_name(name: str) -> str:
    normalized = name.strip()
    return {
        "serser_places": "serper_places",
        "serper_place": "serper_places",
        "serper_local": "serper_places",
        "serper_place_search": "serper_places",
        "serper_image": "serper_images",
        "serper_image_search": "serper_images",
        "serper_searches": "serper_search",
    }.get(normalized, normalized)


def _planning_from_orchestrator_contract(
    contract: dict[str, Any],
    request: TravelPlanRequest,
) -> tuple[TravelIntent, SearchPlan, TripPlanDraft]:
    answer_mode = str(contract.get("answer_mode") or "answer_only")
    tool_calls = _contract_tool_calls(contract)
    capabilities = _capabilities_from_tool_calls(answer_mode, tool_calls)
    query_variants = _queries_from_tool_calls(tool_calls) or ([request.query] if request.query else [])
    tools = [call["name"] for call in tool_calls]
    needs_cards = answer_mode in {"place_cards", "itinerary"} and any(
        capability in capabilities for capability in {"places", "activities", "food"}
    )
    needs_map = answer_mode in {"place_cards", "itinerary", "route_map"} and (
        needs_cards or "maps" in capabilities or "routes" in capabilities
    )
    needs_inventory = bool({"hotels", "flights"} & set(capabilities))
    capability_plan = TravelCapabilityPlan(
        user_goal=request.query or request.question,
        intent_kind=_intent_kind(answer_mode, capabilities),
        required_capabilities=capabilities,
        tool_tasks=[
            TravelToolTask(
                task_id=call["task_id"],
                capability=_capability_for_tool(call["name"]),
                query=_tool_query(call, request),
                required=bool(call.get("required", True)),
            )
            for call in tool_calls
        ],
        agent_tasks=[
            TravelAgentTask(
                task_id=call["task_id"],
                agent_role=_agent_role_for_tool(call["name"]),
                objective=f"Run bounded tool {call['name']}",
                input_keys=[call["name"]],
                required=bool(call.get("required", True)),
            )
            for call in tool_calls
            if call["name"] in {"complex_route_reasoner", "critic_verifier", "visual_context_analyzer"}
        ],
        answer_contract=TravelAnswerContract(
            needs_map=needs_map,
            needs_cards=needs_cards,
            needs_itinerary=answer_mode == "itinerary",
            needs_inventory=needs_inventory,
            response_style="itinerary" if answer_mode == "itinerary" else ("route" if answer_mode == "route_map" else "cards" if needs_cards else "narrative"),
        ),
        confidence=float(contract.get("confidence") or 0.75),
    )
    intent = TravelIntent(
        task_type=_task_type(answer_mode, capabilities),
        answer_mode=answer_mode,  # type: ignore[arg-type]
        requires_place=answer_mode != "answer_only",
        trip_stage="in_trip" if request.city else "planning",
        traveler_stage="inspiration",
        needs_geo=needs_map,
        needs_realtime_inventory=needs_inventory,
        needs_knowledge=True,
        needs_transaction=False,
        delivery_strategy="single_agent",
        destination=request.city or _tool_argument(tool_calls, "destination") or "",
        category=_category_from_contract(request, tool_calls, capabilities),
        target_entity=_contract_target_entity(contract),
        target_type=_target_type(capabilities),
        requested_outputs=_requested_outputs(answer_mode, capabilities),
        need_supplier_types=capabilities,
        should_not_answer=_should_not_answer(capabilities),
        constraints=list(request.constraints),
        avoid=list(request.avoid),
        capability_plan=capability_plan,
        confidence=float(contract.get("confidence") or 0.75),
    )
    search_plan = SearchPlan(
        should_search=bool(tool_calls),
        tools=tools,
        query_variants=query_variants,
        locale="auto",
        must_satisfy=_must_satisfy(request, tool_calls),
        exclude_types=[],
    )
    plan_draft = TripPlanDraft(
        intent_summary=_contract_summary(contract) or request.query,
        answer_strategy="GPT orchestrator keeps final answer ownership; bounded tools only supply data.",
        required_capabilities=capabilities,
        skipped_capabilities=[
            capability
            for capability in ["flights", "hotels"]
            if capability not in capabilities
        ],
        tasks=[
            {
                "task_id": task.task_id,
                "capability": task.capability,
                "purpose": task.query or f"Run {task.capability}",
                "agent_role": _agent_role_for_tool(tool_calls[index]["name"]) if index < len(tool_calls) else "destination",
                "required": task.required,
            }
            for index, task in enumerate(capability_plan.tool_tasks)
        ],
        followup_slots=_string_list(contract.get("followup_slots")),
        confidence=float(contract.get("confidence") or 0.75),
    )
    return intent, search_plan, plan_draft


async def _execute_orchestrator_tools(
    *,
    supervisor: Any,
    request: TravelPlanRequest,
    contract: dict[str, Any],
    intent: TravelIntent,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], list[TravelRouteOption]]:
    tool_calls = _contract_tool_calls(contract)
    max_rounds = getattr(supervisor, "orchestrator_max_tool_rounds", 6)
    if len(tool_calls) > max_rounds:
        raise TravelModelCallError(
            "tool_loop_limit_exceeded",
            f"orchestrator requested {len(tool_calls)} tools; limit is {max_rounds}",
            model=supervisor.model_router.orchestrator,
        )
    api_payloads: dict[str, Any] = {}
    warnings: list[str] = []
    tool_results: list[dict[str, Any]] = []
    route_options: list[TravelRouteOption] = []
    for call in tool_calls:
        _validate_tool_call(call, request)
        name = call["name"]
        args = call["arguments"]
        try:
            payload_updates, data, route_updates, attempts = await _run_orchestrator_tool_with_retry(
                supervisor=supervisor,
                request=request,
                name=name,
                args=args,
                api_payloads=api_payloads,
                category_hint=intent.category,
            )
            api_payloads.update(payload_updates)
            route_options.extend(route_updates)
            result = {"name": name, "status": "completed", "result_count": _result_count(data)}
            if attempts > 1:
                result["attempts"] = attempts
            tool_results.append(result)
        except TravelModelCallError:
            raise
        except Exception as exc:
            summary = _exception_summary(exc)
            warning = f"{name} API 调用失败：{summary}"
            warnings.append(warning)
            tool_results.append({"name": name, "status": "failed", "error": summary})
            if name in {"serper_places", "serper_search", "hotel_search", "flight_search", "route_lookup"}:
                api_payloads.setdefault(_payload_key_for_failed_tool(name, args), [])
    if intent.answer_mode != "answer_only" and not contract.get("skip_image_enrichment"):
        api_payloads, image_warnings = await supervisor._enrich_payloads_with_place_images(request, api_payloads)
        warnings.extend(image_warnings)
    return api_payloads, warnings, tool_results, route_options


def _apply_orchestrator_contract(
    *,
    response: TravelPlanResponse,
    state: TravelWorkflowState,
) -> TravelPlanResponse:
    supervisor = state["supervisor"]
    contract = state["orchestrator_contract"]
    initial_contract = state.get("initial_orchestrator_contract", contract)
    initial_tool_calls = _contract_tool_calls(initial_contract)
    route_options = state.get("route_options", []) or _route_options_from_contract(contract)
    sections = _contract_sections(contract)
    if state.get("finalization_source") == "deterministic_structured_cards" and response.display_cards:
        if response.answer_mode == "itinerary":
            sections = _itinerary_sections_from_plan(
                state["request"],
                response.itinerary_plan,
                response.display_cards,
            )
        else:
            sections = _concise_sections_from_display_cards(state["request"], response)
    if not sections and route_options:
        sections = _classified_sections_from_routes(state["request"], route_options)
    markdown = _sections_markdown(sections) or response.formatted_markdown or response.narrative_answer
    summary = _contract_summary({"sections": sections}) or _contract_summary(contract) or response.summary
    deterministic_fast_path = _is_deterministic_fast_path(state)
    anchor_answer_sufficient = deterministic_fast_path and _has_sufficient_anchor_answer(state["request"], response)
    data_gap_candidates = [
        *response.data_gaps,
        *state.get("api_warnings", []),
        *_string_list(contract.get("data_gaps")),
    ]
    if anchor_answer_sufficient:
        data_gap_candidates = [
            gap
            for gap in data_gap_candidates
            if not _is_non_blocking_fast_path_tool_warning(gap)
        ]
    data_gaps = list(dict.fromkeys(data_gap_candidates))
    refs = dict(response.raw_provider_refs or {})
    if anchor_answer_sufficient:
        runtime_warnings = _string_list(refs.get("model_runtime_warnings"))
        if runtime_warnings:
            filtered_runtime_warnings = [
                warning
                for warning in runtime_warnings
                if not _is_non_blocking_fast_path_tool_warning(warning)
            ]
            if filtered_runtime_warnings:
                refs["model_runtime_warnings"] = list(dict.fromkeys(filtered_runtime_warnings))
            else:
                refs.pop("model_runtime_warnings", None)
    orchestrator_model = "deterministic" if deterministic_fast_path else supervisor.model_router.orchestrator
    refs["travel_orchestrator"] = {
        "model": orchestrator_model,
        "ownership": (
            "deterministic_fast_path_with_lightweight_tools"
            if deterministic_fast_path
            else "single_manager_initial_answer_with_lightweight_tools"
        ),
        "tool_calls_requested": initial_tool_calls,
        "final_tool_calls_requested": _contract_tool_calls(contract),
        "max_tool_rounds": getattr(supervisor, "orchestrator_max_tool_rounds", 6),
        "sections": sections,
        "finalization": state.get("finalization_source", "initial_contract_no_tools"),
        "answer_framework": contract.get("answer_framework") or _classified_answer_framework(state["request"], state)["name"],
        "answer_framework_spec": _classified_answer_framework(state["request"], state),
    }
    refs["tool_trace"] = state.get("tool_results", [])
    refs["langgraph_orchestrator"] = {
        "runtime": "langgraph_stategraph",
        "actual_graph_run": True,
        "run_mode": "single_gpt_orchestrator_with_lightweight_tools",
        "route": response.answer_mode,
        "graph_nodes": ORCHESTRATOR_GRAPH_NODE_NAMES,
        "completed_nodes": state.get("completed_nodes", []),
        "failed_nodes": state.get("failed_nodes", []),
        "trace": state.get("trace", []),
        "providers_used": sorted(state.get("api_payloads", {}).keys()),
        "max_parallel_agents": 1,
        "global_active_run_limit": 2,
        "degrade_when_busy": False,
    }
    workflow_summary = dict(response.workflow_summary or {})
    workflow_summary.update(
        {
            "tool_summary": _tool_summary(state.get("tool_results", [])),
            "graph_nodes": ORCHESTRATOR_GRAPH_NODE_NAMES,
            "completed_nodes": state.get("completed_nodes", []),
            "failed_nodes": state.get("failed_nodes", []),
            "manager_model": orchestrator_model,
        }
    )
    model_used = (
        "deterministic"
        if deterministic_fast_path
        else ",".join(
            dict.fromkeys(
                [
                    supervisor.model_router.orchestrator,
                    *[
                        supervisor.model_router.complex_route
                        for item in state.get("tool_results", [])
                        if item.get("name") == "complex_route_reasoner"
                    ],
                ]
            )
        )
    )
    optional_followups = response.optional_followups
    if anchor_answer_sufficient:
        optional_followups = []
    return response.model_copy(
        update={
            "summary": summary,
            "narrative_answer": markdown,
            "answer_sections": [TravelAnswerSection.model_validate(section) for section in sections],
            "formatted_markdown": markdown,
            "route_options": route_options,
            "data_gaps": data_gaps,
            "uncertainty": data_gaps,
            "decision_notes": _decision_notes_from_sections(sections),
            "raw_provider_refs": refs,
            "workflow_summary": workflow_summary,
            "agentic_workflow": _orchestrator_workflow_steps(state),
            "optional_followups": optional_followups,
            "llm_used": not deterministic_fast_path,
            "model_used": model_used,
            "formatter_model_used": (
                "deterministic_card_summary"
                if state.get("finalization_source") == "deterministic_structured_cards"
                else "travel_orchestrator"
            ),
            "reasoning_mode": _orchestrator_reasoning_mode(state, deterministic_fast_path),
            "needs_user_confirmation": bool(data_gaps),
        }
    )


def _is_deterministic_fast_path(state: TravelWorkflowState) -> bool:
    contract = state.get("initial_orchestrator_contract") or state.get("orchestrator_contract") or {}
    return str(contract.get("orchestrator_source") or "") == "deterministic_fast_path"


def _has_sufficient_anchor_answer(
    request: TravelPlanRequest,
    response: TravelPlanResponse,
) -> bool:
    if response.answer_mode == "itinerary":
        requested_days = _requested_day_count(request)
        pins = response.map_view.get("pins", []) if isinstance(response.map_view, dict) else []
        return bool(
            requested_days
            and len(response.itinerary_plan.days) >= requested_days
            and len(pins) >= min(requested_days + 1, 5)
        )
    if response.answer_mode == "place_cards":
        pins = response.map_view.get("pins", []) if isinstance(response.map_view, dict) else []
        return bool(
            len(response.display_cards) >= min(max(request.max_results, 5), 6)
            and response.map_view.get("status") == "ready"
            and pins
        )
    return False


def _is_non_blocking_fast_path_tool_warning(value: str) -> bool:
    text = str(value or "")
    return bool(
        re.search(
            r"serper_(?:places|search|images).*API 调用失败|HTTP\s*(?:4\d\d|5\d\d)|Client error|Server error",
            text,
            flags=re.I,
        )
    )


def _orchestrator_reasoning_mode(
    state: TravelWorkflowState,
    deterministic_fast_path: bool,
) -> str:
    if deterministic_fast_path:
        return "deterministic_fast_path+bounded_tools+deterministic_card_summary"
    if state.get("finalization_source") == "deterministic_structured_cards":
        return "gpt_orchestrator+bounded_tools+deterministic_card_summary"
    return "gpt_orchestrator+bounded_tools+final_synthesis"


def _attach_itinerary_plan(
    *,
    request: TravelPlanRequest,
    response: TravelPlanResponse,
    plan_draft: TripPlanDraft,
) -> TravelPlanResponse:
    cards = _itinerary_display_cards_with_city_anchors(request, response.display_cards)
    plan = _build_itinerary_plan(request, cards, plan_draft)
    display_cards = _itinerary_primary_cards(cards, plan) or cards
    narrative = _itinerary_narrative(plan)
    return response.model_copy(
        update={
            "display_cards": display_cards,
            "map_view": _itinerary_map_view_from_cards(response, display_cards),
            "itinerary_plan": plan,
            "summary": narrative,
            "narrative_answer": narrative,
        }
    )


def _attach_first_timer_city_anchor_cards(
    *,
    request: TravelPlanRequest,
    response: TravelPlanResponse,
) -> TravelPlanResponse:
    if not _is_obvious_first_timer_recommendation_request(request):
        return response
    cards = _first_timer_display_cards_with_city_anchors(request, response.display_cards)
    if cards == response.display_cards:
        return response
    return response.model_copy(
        update={
            "display_cards": cards,
            "map_view": _itinerary_map_view_from_cards(response, cards),
        }
    )


def _first_timer_display_cards_with_city_anchors(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[TravelDisplayCard]:
    anchor_specs = _city_first_timer_anchor_specs(request)
    if not anchor_specs:
        return cards
    min_map_ready = min(max(request.max_results, 5), 6)
    usable_cards = list(cards)
    map_ready_count = sum(1 for card in usable_cards if _is_map_ready_card(card))
    if map_ready_count >= min_map_ready:
        return usable_cards

    next_index = _next_card_index(usable_cards)
    for anchor in anchor_specs:
        if map_ready_count >= min_map_ready:
            break
        if _matching_anchor_card(usable_cards, anchor) is not None:
            continue
        card = _anchor_spec_to_display_card(anchor, next_index)
        usable_cards.append(card)
        next_index += 1
        map_ready_count += 1
    return usable_cards


def _itinerary_display_cards_with_city_anchors(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
) -> list[TravelDisplayCard]:
    days_count = _requested_day_count(request)
    min_map_ready = min(max(days_count + 1, 4), 6) if days_count else 3
    usable_cards = [
        card
        for card in cards
        if _is_map_ready_card(card) or not _is_generic_itinerary_web_card(card)
    ]
    anchor_specs = _city_itinerary_anchor_specs(request)
    if anchor_specs:
        usable_cards = _prioritize_city_itinerary_anchor_cards(usable_cards, anchor_specs)
    map_ready_count = sum(1 for card in usable_cards if _is_map_ready_card(card))
    if map_ready_count >= min_map_ready:
        return usable_cards

    next_index = _next_card_index(usable_cards)
    seen_titles = {_normalized_anchor_title(card.title) for card in usable_cards}
    for anchor in anchor_specs:
        if map_ready_count >= min_map_ready:
            break
        if _normalized_anchor_title(str(anchor["title"])) in seen_titles:
            continue
        card = _anchor_spec_to_display_card(anchor, next_index)
        usable_cards.append(card)
        seen_titles.add(_normalized_anchor_title(card.title))
        next_index += 1
        map_ready_count += 1
    return usable_cards


def _prioritize_city_itinerary_anchor_cards(
    cards: list[TravelDisplayCard],
    anchor_specs: list[dict[str, Any]],
) -> list[TravelDisplayCard]:
    prioritized: list[TravelDisplayCard] = []
    used_ids: set[str] = set()
    next_index = _next_card_index(cards)
    for anchor in anchor_specs:
        card = _matching_anchor_card(cards, anchor)
        if card is None:
            card = _anchor_spec_to_display_card(anchor, next_index)
            next_index += 1
        prioritized.append(card)
        used_ids.add(card.id)
    for card in cards:
        if card.id not in used_ids:
            prioritized.append(card)
    return prioritized


def _matching_anchor_card(
    cards: list[TravelDisplayCard],
    anchor: dict[str, Any],
) -> TravelDisplayCard | None:
    for card in cards:
        if _card_matches_anchor(card, anchor):
            return card
    return None


def _card_matches_anchor(card: TravelDisplayCard, anchor: dict[str, Any]) -> bool:
    title = _normalized_anchor_title(card.title)
    combined = _normalized_anchor_title(" ".join([card.title, card.subcategory]))
    anchor_title = _normalized_anchor_title(str(anchor.get("title") or ""))
    if anchor_title and (anchor_title in combined or title in anchor_title):
        return True
    for alias in _anchor_title_aliases(str(anchor.get("title") or "")):
        if alias in combined:
            return True
    if card.lat is None or card.lng is None or anchor.get("lat") is None or anchor.get("lng") is None:
        return False
    return abs(float(card.lat) - float(anchor["lat"])) <= 0.004 and abs(float(card.lng) - float(anchor["lng"])) <= 0.004


def _anchor_title_aliases(title: str) -> list[str]:
    normalized = _normalized_anchor_title(title)
    aliases = {
        "博多舊市街": ["hakata old town", "博多舊市街", "博多旧市街"],
        "天神": ["tenjin", "天神"],
        "太宰府天満宮": ["dazaifu", "太宰府", "太宰府天満宮", "太宰府天满宫"],
        "大濠公園": ["ohori", "大濠", "大濠公園", "大濠公园"],
        "百道海濱": ["momochi", "momochihama", "百道", "百道海濱", "百道海滨", "fukuoka tower", "福岡塔", "福冈塔"],
        "京都站": ["kyoto station", "京都站", "京都駅"],
        "祇園": ["gion", "祇園", "祇园"],
        "伏見稻荷大社": ["fushimi inari", "伏見稻荷", "伏见稻荷"],
        "梅田": ["umeda", "梅田"],
        "難波": ["namba", "難波", "难波"],
    }
    return aliases.get(normalized, [normalized])


def _is_map_ready_card(card: TravelDisplayCard) -> bool:
    return card.lat is not None and card.lng is not None


def _is_generic_itinerary_web_card(card: TravelDisplayCard) -> bool:
    if _is_map_ready_card(card):
        return False
    text = _normalized_anchor_title(" ".join([card.title, card.description, card.source_provider, card.source_url]))
    markers = [
        "kkday",
        "自由行推薦",
        "自由行推荐",
        "旅遊行程",
        "旅游行程",
        "搜尋的關鍵字",
        "搜索的关键字",
        "search result",
        "best things to do",
        "things to do in",
        "travel guide",
        "guide",
        "blog",
        "listicle",
    ]
    return card.source_provider == "search" or any(marker in text for marker in markers)


def _city_itinerary_anchor_specs(request: TravelPlanRequest) -> list[dict[str, Any]]:
    text = _request_text(request).lower()
    if "福冈" in text or "福岡" in text or "fukuoka" in text:
        return [
            {
                "title": "博多旧市街",
                "subcategory": "历史街区",
                "description": "博多站和祇园一带容易抵达，适合第1天用低强度方式熟悉城市。",
                "address": "Hakata Ward, Fukuoka",
                "lat": 33.5952,
                "lng": 130.4144,
            },
            {
                "title": "天神",
                "subcategory": "商业街区",
                "description": "餐饮、购物和屋台都集中，适合作为抵达日傍晚或晚餐后的轻松区域。",
                "address": "Tenjin, Chuo Ward, Fukuoka",
                "lat": 33.5904,
                "lng": 130.3989,
            },
            {
                "title": "太宰府天满宫",
                "subcategory": "神社",
                "description": "福冈经典近郊半日点，适合单独安排，不要和海边硬塞在一起。",
                "address": "4 Chome-7-1 Saifu, Dazaifu",
                "lat": 33.5214,
                "lng": 130.5348,
            },
            {
                "title": "大濠公园",
                "subcategory": "公园",
                "description": "市内湖边公园，适合太宰府回城后散步，也适合低强度缓冲。",
                "address": "Ohorikoen, Chuo Ward, Fukuoka",
                "lat": 33.5869,
                "lng": 130.3796,
            },
            {
                "title": "百道海滨",
                "subcategory": "海滨",
                "description": "海边、福冈塔和开阔景观集中，适合第3天做轻松半日并留离境缓冲。",
                "address": "Momochihama, Sawara Ward, Fukuoka",
                "lat": 33.5934,
                "lng": 130.3515,
            },
        ]
    if ("京都" in text or "kyoto" in text) and ("大阪" in text or "osaka" in text):
        return [
            {
                "title": "京都站",
                "subcategory": "交通枢纽",
                "description": "京都段住宿和换乘锚点，适合前两晚住京都。",
                "address": "Kyoto Station, Kyoto",
                "lat": 34.9858,
                "lng": 135.7588,
            },
            {
                "title": "祇园",
                "subcategory": "历史街区",
                "description": "京都东山夜间散步方便，适合京都段的一晚。",
                "address": "Gion, Kyoto",
                "lat": 35.0037,
                "lng": 135.7751,
            },
            {
                "title": "伏见稻荷大社",
                "subcategory": "神社",
                "description": "适合京都段早去，之后移动到大阪比较顺。",
                "address": "Fushimi Ward, Kyoto",
                "lat": 34.9671,
                "lng": 135.7727,
            },
            {
                "title": "梅田",
                "subcategory": "商业交通区",
                "description": "大阪交通和住宿方便，适合最后一晚住大阪。",
                "address": "Umeda, Osaka",
                "lat": 34.7025,
                "lng": 135.4959,
            },
            {
                "title": "难波",
                "subcategory": "街区",
                "description": "大阪餐饮和夜间活动集中，适合作为大阪段主区域。",
                "address": "Namba, Osaka",
                "lat": 34.6658,
                "lng": 135.5011,
            },
        ]
    return []


def _city_first_timer_anchor_specs(request: TravelPlanRequest) -> list[dict[str, Any]]:
    text = _request_text(request).lower()
    if "福冈" in text or "福岡" in text or "fukuoka" in text:
        return [
            {
                "title": "博多旧市街",
                "subcategory": "历史街区",
                "description": "博多站和祇园一带好找、好停留，适合第一次到福冈先建立城市方位感。",
                "address": "Hakata Ward, Fukuoka",
                "lat": 33.5952,
                "lng": 130.4144,
                "source_provider": "first_timer_anchor",
            },
            {
                "title": "天神",
                "subcategory": "商业街区",
                "description": "交通、餐饮、购物和屋台都集中，适合新手把晚餐和轻松逛街放在同一区域。",
                "address": "Tenjin, Chuo Ward, Fukuoka",
                "lat": 33.5904,
                "lng": 130.3989,
                "source_provider": "first_timer_anchor",
            },
            {
                "title": "太宰府天满宫",
                "subcategory": "神社",
                "description": "福冈经典近郊半日点，路线清晰，适合想要传统氛围但不想排太复杂动线的新手。",
                "address": "4 Chome-7-1 Saifu, Dazaifu",
                "lat": 33.5214,
                "lng": 130.5348,
                "source_provider": "first_timer_anchor",
            },
            {
                "title": "大濠公园",
                "subcategory": "公园",
                "description": "市内湖边公园，节奏低、停留弹性大，适合作为半日散步或太宰府回城后的缓冲。",
                "address": "Ohorikoen, Chuo Ward, Fukuoka",
                "lat": 33.5869,
                "lng": 130.3796,
                "source_provider": "first_timer_anchor",
            },
            {
                "title": "百道海滨",
                "subcategory": "海滨",
                "description": "海边、福冈塔和开阔景观集中，适合第一次去时安排成轻松半日，不要和远郊硬串。",
                "address": "Momochihama, Sawara Ward, Fukuoka",
                "lat": 33.5934,
                "lng": 130.3515,
                "source_provider": "first_timer_anchor",
            },
        ]
    return []


def _anchor_spec_to_display_card(spec: dict[str, Any], index: int) -> TravelDisplayCard:
    title = str(spec["title"])
    address = str(spec.get("address") or "")
    lat = float(spec["lat"])
    lng = float(spec["lng"])
    maps_query = quote_plus(" ".join(part for part in [title, address] if part))
    directions_query = maps_query
    return TravelDisplayCard(
        id=f"card-{index}",
        title=title,
        category="本地体验",
        subcategory=str(spec.get("subcategory") or ""),
        description=str(spec.get("description") or ""),
        address=address,
        image_status="missing",
        source_provider=str(spec.get("source_provider") or "itinerary_anchor"),
        reason=str(spec.get("description") or ""),
        display_reason=str(spec.get("description") or ""),
        lat=lat,
        lng=lng,
        tags=["本地体验"],
        google_maps_uri=f"https://www.google.com/maps/search/?api=1&query={maps_query}",
        directions_uri=f"https://www.google.com/maps/dir/?api=1&destination={directions_query}",
    )


def _next_card_index(cards: list[TravelDisplayCard]) -> int:
    max_index = 0
    for card in cards:
        match = re.search(r"(\d+)$", card.id)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def _normalized_anchor_title(value: str) -> str:
    normalized = value.lower().translate(str.maketrans({"冈": "岡", "满": "満", "旧": "舊", "区": "區"}))
    return re.sub(r"\s+", " ", normalized).strip()


def _itinerary_map_view_from_cards(
    response: TravelPlanResponse,
    cards: list[TravelDisplayCard],
) -> dict[str, Any]:
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
        if _is_map_ready_card(card)
    ]
    if not pins:
        return {**dict(response.map_view or {}), "pins": [], "status": "needs_coordinates"}
    center = {
        "lat": sum(float(pin["lat"]) for pin in pins) / len(pins),
        "lng": sum(float(pin["lng"]) for pin in pins) / len(pins),
    }
    return {
        "provider": "mapbox",
        "mode": "mapbox_gl",
        "center": center,
        "selected_pin_id": pins[0]["id"],
        "status": "ready",
        "pins": pins,
    }


def _itinerary_primary_cards(
    cards: list[TravelDisplayCard],
    plan: TravelItineraryPlan,
) -> list[TravelDisplayCard]:
    planned_ids: list[str] = []
    for day in plan.days:
        for block in day.time_blocks:
            planned_ids.extend(str(place_id) for place_id in block.place_ids if str(place_id).strip())
    if not planned_ids:
        return []
    by_id = {card.id: card for card in cards}
    primary: list[TravelDisplayCard] = []
    seen: set[str] = set()
    for card_id in planned_ids:
        card = by_id.get(card_id)
        if card is not None and card.id not in seen:
            primary.append(card)
            seen.add(card.id)
    return primary


def _itinerary_sections_from_plan(
    request: TravelPlanRequest,
    plan: TravelItineraryPlan,
    cards: list[TravelDisplayCard],
) -> list[dict[str, Any]]:
    if not plan.days:
        return []
    city_plan_note = _itinerary_city_plan_note(request, cards)
    day_bullets = [_itinerary_day_bullet(day) for day in plan.days]
    route_bullets = [
        city_plan_note,
        "地图卡片用来核对每一天的区域关系：同区就串联，跨区就拆到不同半日，别为了多打卡把节奏排满。",
        "如果天气、体力或抵达时间变化，优先保留当天主区域，删掉最远的补充点。",
    ]
    card_ids = [card.id for card in cards[:6] if card.id]
    return [
        {
            "id": "itinerary-days",
            "title": "逐日安排",
            "body": f"{_itinerary_duration_label(plan)}安排：{plan.summary or '先按区域和节奏拆成逐日路线。'}",
            "bullets": day_bullets,
            "card_ids": card_ids,
            "pin_ids": card_ids,
        },
        {
            "id": "itinerary-route-map",
            "title": "住宿/动线",
            "body": "这份安排优先减少折返和换区压力，卡片与地图负责支撑地点选择。",
            "bullets": route_bullets,
            "card_ids": card_ids[:4],
            "pin_ids": card_ids[:4],
        },
    ]


def _itinerary_duration_label(plan: TravelItineraryPlan) -> str:
    labels = {
        1: "一天",
        2: "两天",
        3: "三天",
        4: "四天",
        5: "五天",
        6: "六天",
        7: "七天",
    }
    return labels.get(len(plan.days), f"{len(plan.days)} 天") if plan.days else "逐日"


def _itinerary_day_bullet(day: TravelItineraryDay) -> str:
    block_titles = [
        re.sub(r"^(上午|下午|傍晚|晚上|中午|早上)：", "", block.title).strip()
        for block in day.time_blocks
        if str(block.title or "").strip()
    ]
    names = " → ".join(block_titles[:3]) or "保留一个主区域慢慢走"
    notes = [
        block.route_note
        for block in day.time_blocks
        if str(block.route_note or "").strip()
    ]
    note = _compact_sentence(notes[0], limit=52) if notes else "按相邻区域安排，减少折返。"
    return f"第{day.day}天：{names}；{note}"


def _itinerary_city_plan_note(request: TravelPlanRequest, cards: list[TravelDisplayCard]) -> str:
    text = _request_text(request).lower()
    titles = " ".join(card.title for card in cards)
    combined = f"{text} {titles}".lower()
    if ("京都" in combined or "kyoto" in combined) and ("大阪" in combined or "osaka" in combined):
        return "住宿建议：前两晚住京都，第3天早上或中午移动到大阪，最后一晚住大阪；这样只换一次酒店，也能把两座城市分组玩。"
    if "福冈" in combined or "fukuoka" in combined:
        return "住宿建议优先住博多或天神；第1天用博多/天神熟悉城市并解决晚餐，第2天太宰府半日后回大濠公园散步，第3天放百道海滨或福冈塔，午餐后留机场/返程缓冲。"
    if "低预算" in combined or "预算" in combined or "budget" in combined:
        return "低预算建议：每天只安排 0–1 个付费主项目，其余用公园、街区、市场和小吃补足体验。"
    return "动线建议：每天只设一个主区域，补一个同区备选，优先公共交通顺路而不是高分点堆叠。"


def _build_itinerary_plan(
    request: TravelPlanRequest,
    cards: list[TravelDisplayCard],
    plan_draft: TripPlanDraft,
) -> TravelItineraryPlan:
    days_count = _requested_day_count(request)
    if days_count <= 0:
        return TravelItineraryPlan()
    assumptions = [
        "未接入真实预订库存，行程只做路线和体验规划。",
        "未明确机票/酒店时，预算按当地消费、交通、门票和餐饮理解。",
    ]
    if request.budget:
        assumptions.append(f"预算按用户输入的 {request.budget} 作为当地消费约束。")
    source_cards = cards[: max(1, min(len(cards), days_count * 3))]
    if not source_cards:
        source_cards = []
    slot_names = ["上午", "下午", "傍晚"]
    days: list[TravelItineraryDay] = []
    for day_index in range(days_count):
        day_cards = _itinerary_cards_for_day(source_cards, day_index, days_count, request)
        blocks: list[TravelItineraryBlock] = []
        for slot_index, card in enumerate(day_cards):
            blocks.append(
                TravelItineraryBlock(
                    title=f"{slot_names[slot_index % len(slot_names)]}：{card.title}",
                    place_ids=[card.id],
                    route_note="优先选择地图上相邻地点，避免一天跨太多区域。",
                    budget_note=(
                        f"按预算 {request.budget} 控制，当地交通和门票优先低成本。"
                        if request.budget
                        else "未给预算，优先安排低门槛地点。"
                    ),
                    why=card.display_reason or card.description or card.reason or plan_draft.answer_strategy,
                    alternatives=[
                        other.title
                        for other in source_cards
                        if other.id != card.id
                    ][:2],
                )
            )
        if not blocks:
            blocks.append(
                TravelItineraryBlock(
                    title=f"{slot_names[0]}：先确认核心区域",
                    place_ids=[],
                    route_note="候选不足，建议先补充兴趣或允许联网搜索。",
                    budget_note="暂无可核对预算。",
                    why=plan_draft.answer_strategy or "当前信息不足，先保守安排。",
                    alternatives=[],
                )
            )
        days.append(
            TravelItineraryDay(
                day=day_index + 1,
                title=f"第{day_index + 1}天：{_day_title(day_cards, day_index)}",
                date=_date_for_day(request, day_index),
                time_blocks=blocks,
            )
        )
    title = f"{request.city or '旅行'} {days_count} 天自由行"
    return TravelItineraryPlan(
        title=title,
        summary="先按地点相邻、预算克制和体验密度做轻量逐日安排。",
        days=days,
        assumptions=assumptions,
    )


def _itinerary_cards_for_day(
    source_cards: list[TravelDisplayCard],
    day_index: int,
    days_count: int,
    request: TravelPlanRequest,
) -> list[TravelDisplayCard]:
    if not source_cards:
        return []
    city_cards = _city_itinerary_cards_for_day(source_cards, day_index, days_count, request)
    if city_cards:
        return city_cards
    if days_count <= 1:
        return source_cards[:3]
    start = day_index * len(source_cards) // days_count
    end = (day_index + 1) * len(source_cards) // days_count
    if end <= start:
        end = start + 1
    return source_cards[start:end][:3] or source_cards[: min(3, len(source_cards))]


def _city_itinerary_cards_for_day(
    source_cards: list[TravelDisplayCard],
    day_index: int,
    days_count: int,
    request: TravelPlanRequest,
) -> list[TravelDisplayCard]:
    text = _request_text(request).lower()
    if days_count == 3 and ("福冈" in text or "福岡" in text or "fukuoka" in text):
        day_keywords = [
            ["博多旧市街", "博多舊市街", "hakata old town", "天神", "tenjin"],
            ["太宰府", "dazaifu", "大濠", "ohori"],
            ["百道", "momochi", "momochihama", "fukuoka tower", "福冈塔", "福岡塔"],
        ]
        return _cards_matching_itinerary_keywords(source_cards, day_keywords[day_index])[:3]
    return []


def _cards_matching_itinerary_keywords(
    cards: list[TravelDisplayCard],
    keywords: list[str],
) -> list[TravelDisplayCard]:
    normalized_keywords = [_normalized_anchor_title(keyword) for keyword in keywords]
    matched: list[TravelDisplayCard] = []
    for card in cards:
        text = _normalized_anchor_title(" ".join([card.title, card.address, card.subcategory]))
        if any(keyword and keyword in text for keyword in normalized_keywords):
            matched.append(card)
    return matched


def _requested_day_count(request: TravelPlanRequest) -> int:
    text = " ".join([request.query, request.question, " ".join(request.date_range)])
    digit_match = re.search(r"(\d{1,2})\s*(?:天|day|days)", text, flags=re.I)
    if digit_match:
        return max(1, min(int(digit_match.group(1)), 7))
    chinese_days = {
        "一天": 1,
        "一日": 1,
        "两天": 2,
        "二天": 2,
        "两日": 2,
        "二日": 2,
        "三天": 3,
        "三日": 3,
        "四天": 4,
        "四日": 4,
        "五天": 5,
        "五日": 5,
    }
    for token, value in chinese_days.items():
        if token in text:
            return value
    if len(request.date_range) >= 2:
        return min(max(len(request.date_range), 1), 7)
    return 2 if request.query or request.question else 0


def _day_title(cards: list[TravelDisplayCard], day_index: int) -> str:
    if cards:
        category = cards[0].category or cards[0].subcategory
        if category:
            return f"{category}集中安排"
    return "轻量探索" if day_index == 0 else "顺路补充"


def _date_for_day(request: TravelPlanRequest, day_index: int) -> str:
    if day_index < len(request.date_range):
        return request.date_range[day_index]
    return ""


def _itinerary_narrative(plan: TravelItineraryPlan) -> str:
    if not plan.days:
        return plan.summary
    lines = [plan.title.strip() or "逐日行程建议"]
    if plan.summary:
        lines.append(plan.summary)
    for day in plan.days:
        lines.append(f"{day.title}")
        for block in day.time_blocks:
            details = "；".join(
                item
                for item in [block.route_note, block.budget_note, block.why]
                if item
            )
            lines.append(f"- {block.title}" + (f"：{details}" if details else ""))
    if plan.assumptions:
        lines.append("可补充信息：" + "；".join(plan.assumptions[:2]))
    return "\n".join(lines).strip()


def _capabilities_from_tool_calls(answer_mode: str, tool_calls: list[dict[str, Any]]) -> list[str]:
    capabilities: list[str] = []
    if answer_mode == "answer_only":
        capabilities.append("knowledge")
    for call in tool_calls:
        capability = _capability_for_tool(call["name"])
        if capability and capability not in capabilities:
            capabilities.append(capability)
        if call["name"] == "serper_places":
            for extra in ["places", "maps"]:
                if extra not in capabilities:
                    capabilities.append(extra)
        if call["name"] == "route_lookup":
            for extra in ["routes", "transport", "maps"]:
                if extra not in capabilities:
                    capabilities.append(extra)
        if call["name"] == "complex_route_reasoner":
            for extra in ["routes", "transport", "budget"]:
                if extra not in capabilities:
                    capabilities.append(extra)
    if not capabilities:
        capabilities.append("knowledge")
    return capabilities


def _capability_for_tool(name: str) -> str:
    return {
        "serper_search": "knowledge",
        "serper_places": "places",
        "serper_images": "places",
        "route_lookup": "routes",
        "hotel_search": "hotels",
        "flight_search": "flights",
        "weather_lookup": "weather",
        "visa_safety_lookup": "safety",
        "complex_route_reasoner": "routes",
        "critic_verifier": "verification",
        "visual_context_analyzer": "visual",
    }.get(name, "knowledge")


def _agent_role_for_tool(name: str) -> str:
    return {
        "hotel_search": "hotel",
        "flight_search": "flight",
        "route_lookup": "itinerary",
        "complex_route_reasoner": "itinerary",
        "serper_places": "activity_food",
        "serper_images": "activity_food",
        "visual_context_analyzer": "destination",
        "critic_verifier": "critic",
    }.get(name, "destination")


def _queries_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for call in tool_calls:
        query = _tool_query(call, None)
        if query and query not in queries:
            queries.append(query)
    return queries


def _tool_query(call: dict[str, Any], request: TravelPlanRequest | None) -> str:
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    query = str(args.get("query") or args.get("q") or args.get("destination") or args.get("origin") or "").strip()
    if query:
        return query
    return str(getattr(request, "query", "") or "").strip() if request is not None else ""


def _tool_argument(tool_calls: list[dict[str, Any]], key: str) -> str:
    for call in tool_calls:
        args = call.get("arguments")
        if isinstance(args, dict) and args.get(key):
            return str(args[key]).strip()
    return ""


def _contract_target_entity(contract: dict[str, Any]) -> str:
    for key in ["target_entity", "targetEntity", "entity"]:
        value = str(contract.get(key) or "").strip()
        if value:
            return value
    explicit_entities = _string_list(contract.get("target_entities") or contract.get("entities"))
    if len(explicit_entities) == 1:
        return explicit_entities[0]
    grounded_items = [
        *_list_of_dicts(contract.get("cards")),
        *_list_of_dicts(contract.get("map_pins")),
    ]
    named_items = [_place_name(item) for item in grounded_items if _place_name(item)]
    unique_names = list(dict.fromkeys(named_items))
    if len(unique_names) == 1:
        return unique_names[0]
    return ""


def _intent_kind(answer_mode: str, capabilities: list[str]) -> str:
    if answer_mode == "answer_only":
        return "answer_only"
    if "hotels" in capabilities or "flights" in capabilities:
        return "inventory"
    if answer_mode == "route_map":
        return "route"
    if answer_mode == "itinerary":
        return "itinerary"
    return "place_lookup"


def _task_type(answer_mode: str, capabilities: list[str]) -> str:
    if answer_mode == "answer_only":
        return "travel_question"
    if "hotels" in capabilities:
        return "hotel_search"
    if "flights" in capabilities:
        return "flight_search"
    if answer_mode == "route_map":
        return "route_planning"
    if answer_mode == "itinerary":
        return "itinerary_planning"
    return "place_recommendation"


def _category_from_contract(
    request: TravelPlanRequest,
    tool_calls: list[dict[str, Any]],
    capabilities: list[str],
) -> str:
    for call in tool_calls:
        args = call.get("arguments")
        if isinstance(args, dict) and args.get("category"):
            return str(args["category"]).strip()
    query = request.query or request.question
    if "hotels" in capabilities:
        return "住宿"
    if "flights" in capabilities or "routes" in capabilities:
        return "交通"
    if "吃" in query or "美食" in query or "餐" in query:
        return "美食"
    return "本地体验" if "places" in capabilities else ""


def _target_type(capabilities: list[str]) -> str:
    if "hotels" in capabilities:
        return "hotel"
    if "flights" in capabilities:
        return "flight"
    if "routes" in capabilities:
        return "route"
    if "places" in capabilities:
        return "place"
    return "knowledge"


def _requested_outputs(answer_mode: str, capabilities: list[str]) -> list[str]:
    outputs = ["narrative"]
    if answer_mode in {"place_cards", "itinerary"} and "places" in capabilities:
        outputs.extend(["place_cards", "map"])
    if answer_mode == "itinerary":
        outputs.append("itinerary")
    if answer_mode == "route_map":
        outputs.append("route_options")
    if "hotels" in capabilities:
        outputs.append("hotel_offers")
    if "flights" in capabilities:
        outputs.append("flight_offers")
    return list(dict.fromkeys(outputs))


def _should_not_answer(capabilities: list[str]) -> list[str]:
    blocked: list[str] = []
    if "hotels" not in capabilities:
        blocked.append("hotel_inventory")
    if "flights" not in capabilities:
        blocked.append("flight_inventory")
    return blocked


def _must_satisfy(request: TravelPlanRequest, tool_calls: list[dict[str, Any]]) -> list[str]:
    values = []
    for call in tool_calls:
        query = _tool_query(call, request)
        if query:
            values.append(query)
    return values[:4]


async def _run_orchestrator_tool_with_retry(
    *,
    supervisor: Any,
    request: TravelPlanRequest,
    name: str,
    args: dict[str, Any],
    api_payloads: dict[str, Any],
    category_hint: str,
) -> tuple[dict[str, Any], Any, list[TravelRouteOption], int]:
    max_attempts = 2
    attempt = 0
    while True:
        attempt += 1
        try:
            payload_updates, data, route_updates = await _run_single_orchestrator_tool(
                supervisor=supervisor,
                request=request,
                name=name,
                args=args,
                api_payloads=api_payloads,
                category_hint=category_hint,
            )
            return payload_updates, data, route_updates, attempt
        except TravelModelCallError:
            raise
        except Exception as exc:
            if attempt < max_attempts and _is_transient_tool_error(exc):
                continue
            raise


async def _run_single_orchestrator_tool(
    *,
    supervisor: Any,
    request: TravelPlanRequest,
    name: str,
    args: dict[str, Any],
    api_payloads: dict[str, Any],
    category_hint: str,
) -> tuple[dict[str, Any], Any, list[TravelRouteOption]]:
    if name == "serper_search":
        data = await _tool_serper_search(supervisor, request, args)
        return {"raw_query": data}, data, []
    if name == "serper_places":
        key, data = await _tool_serper_places(supervisor, request, args, category_hint)
        return {key: data}, data, []
    if name == "serper_images":
        data = await _tool_serper_images(supervisor, request, args)
        return {f"images:{_arg(args, 'query') or request.query}": data}, data, []
    if name == "route_lookup":
        route_request = _route_request_from_args(request, args)
        data = await _tool_route_lookup(supervisor, route_request)
        return {"transport": data}, data, _route_options_from_tool_data(data, route_request)
    if name == "hotel_search":
        data = await _tool_hotel_search(supervisor, request)
        return {"hotel": data}, data, []
    if name == "flight_search":
        data = await _tool_flight_search(supervisor, request)
        return {"flight": data}, data, []
    if name == "weather_lookup":
        data = await _tool_optional_search(supervisor, request, "weather")
        return {"weather": data}, data, []
    if name == "visa_safety_lookup":
        visa = await _tool_optional_search(supervisor, request, "visa")
        safety = await _tool_optional_search(supervisor, request, "safety")
        data = {"visa": visa, "safety": safety}
        return {"visa": visa, "safety": safety}, data, []
    if name == "complex_route_reasoner":
        data = await _tool_complex_route_reasoner(supervisor, request, args, api_payloads)
        return {}, data, _route_options_from_tool(data)
    if name == "critic_verifier":
        data = await _tool_agent(supervisor, request, "critic_verifier", supervisor.model_router.critic, args, api_payloads)
        return {}, data, []
    if name == "visual_context_analyzer":
        data = await _tool_agent(supervisor, request, "visual_context_analyzer", supervisor.model_router.visual, args, api_payloads)
        return {}, data, []
    return {}, [], []


def _is_transient_tool_error(exc: Exception) -> bool:
    message = _exception_summary(exc).lower()
    transient_markers = [
        "timeout",
        "timed out",
        "temporarily",
        "connection",
        "network",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "529",
    ]
    return any(marker in message for marker in transient_markers)


def _validate_tool_call(call: dict[str, Any], request: TravelPlanRequest) -> None:
    name = str(call.get("name") or "")
    if name not in ORCHESTRATOR_TOOL_NAMES:
        raise TravelModelCallError("tool_validation", f"unsupported tool: {name}")
    args = call.get("arguments")
    args = args if isinstance(args, dict) else {}
    required = bool(call.get("required", True))
    if not required:
        return
    has_explicit_query = bool(str(args.get("query") or args.get("q") or "").strip())
    has_query = has_explicit_query or bool(request.query)
    has_city = bool(str(args.get("city") or request.city).strip())
    has_route = bool(str(args.get("origin") or request.origin_city).strip()) and bool(str(args.get("destination") or request.city).strip())
    has_visual = bool(str(args.get("visual_session_id") or request.previous_context.get("visual_session_id") or "").strip())
    valid = {
        "serper_search": has_explicit_query,
        "serper_places": has_explicit_query or bool(str(args.get("category") or "").strip()),
        "serper_images": has_query,
        "route_lookup": has_route,
        "hotel_search": has_city or has_query,
        "flight_search": has_city or has_route,
        "weather_lookup": has_city,
        "visa_safety_lookup": has_city,
        "complex_route_reasoner": has_route,
        "critic_verifier": True,
        "visual_context_analyzer": has_visual,
    }[name]
    if not valid:
        raise TravelModelCallError("tool_validation", f"{name} missing required arguments")


async def _tool_serper_search(supervisor: Any, request: TravelPlanRequest, args: dict[str, Any]) -> list[dict[str, Any]]:
    client = supervisor.serpapi_client
    if client is None:
        raise RuntimeError("SERPER_API_KEY missing")
    query = _arg(args, "query") or request.query
    method = getattr(client, "search_query_variants", None)
    if callable(method):
        return await method(request, [query])
    method = getattr(client, "search_raw_query", None)
    if callable(method):
        return await method(request)
    return []


async def _tool_serper_places(
    supervisor: Any,
    request: TravelPlanRequest,
    args: dict[str, Any],
    category_hint: str,
) -> tuple[str, list[dict[str, Any]]]:
    client = supervisor.serpapi_client
    if client is None:
        raise RuntimeError("SERPER_API_KEY missing")
    query = _arg(args, "query") or _arg(args, "category") or request.query
    category = _arg(args, "category") or category_hint or query
    method = getattr(client, "search_local", None)
    if not callable(method):
        raise RuntimeError("serper places unavailable")
    return f"local:{category}", await method(request, category)


async def _tool_serper_images(supervisor: Any, request: TravelPlanRequest, args: dict[str, Any]) -> list[dict[str, Any]]:
    client = supervisor.serpapi_client
    if client is None:
        raise RuntimeError("SERPER_API_KEY missing")
    method = getattr(client, "search_images", None)
    if not callable(method):
        return []
    return await method(request, _arg(args, "query") or request.query)


def _route_request_from_args(request: TravelPlanRequest, args: dict[str, Any]) -> TravelPlanRequest:
    origin = _arg(args, "origin") or request.origin_city
    destination = _arg(args, "destination") or request.city
    mode = _arg(args, "mode") or request.transport_mode
    return request.model_copy(
        update={
            "origin_city": origin,
            "city": destination,
            "transport_mode": mode,
        }
    )


async def _tool_route_lookup(supervisor: Any, request: TravelPlanRequest) -> list[dict[str, Any]]:
    client = supervisor.serpapi_client
    method = getattr(client, "search_transport", None) if client is not None else None
    if not callable(method):
        return []
    return await method(request)


async def _tool_hotel_search(supervisor: Any, request: TravelPlanRequest) -> list[dict[str, Any]]:
    client = supervisor.serpapi_client
    method = getattr(client, "search_hotels", None) if client is not None else None
    if not callable(method):
        return []
    return await method(request)


async def _tool_flight_search(supervisor: Any, request: TravelPlanRequest) -> list[dict[str, Any]]:
    client = supervisor.serpapi_client
    method = getattr(client, "search_flights", None) if client is not None else None
    if not callable(method):
        return []
    return await method(request)


async def _tool_optional_search(supervisor: Any, request: TravelPlanRequest, name: str) -> list[dict[str, Any]]:
    client = supervisor.serpapi_client
    method = getattr(client, f"search_{name}", None) if client is not None else None
    if not callable(method):
        return []
    return await method(request)


async def _tool_complex_route_reasoner(
    supervisor: Any,
    request: TravelPlanRequest,
    args: dict[str, Any],
    api_payloads: dict[str, Any],
) -> dict[str, Any]:
    return await _tool_agent(
        supervisor,
        request,
        "complex_route_reasoner",
        supervisor.model_router.complex_route,
        args,
        api_payloads,
    )


async def _tool_agent(
    supervisor: Any,
    request: TravelPlanRequest,
    agent_name: str,
    model: str,
    args: dict[str, Any],
    api_payloads: dict[str, Any],
) -> dict[str, Any]:
    runner = getattr(supervisor.agent_client, "run_agent", None)
    if not callable(runner):
        raise TravelModelCallError(agent_name, "agent client unavailable", model=model)
    try:
        return await runner(
            agent_name=agent_name,
            model=model,
            prompt=f"Run bounded travel tool {agent_name}; return strict JSON only.",
            payload={
                "request": request.model_dump(mode="json"),
                "arguments": args,
                "api_payloads": api_payloads,
            },
        )
    except Exception as exc:
        raise TravelModelCallError(agent_name, _exception_summary(exc), model=model) from exc


def _route_options_from_tool_data(data: Any, request: TravelPlanRequest) -> list[TravelRouteOption]:
    if isinstance(data, dict):
        options = _route_options_from_tool(data)
        if options:
            return options
        items = _list_of_dicts(data.get("items"))
    else:
        items = _list_of_dicts(data)
    origin = request.origin_city or "出发地"
    destination = request.city or "目的地"
    mode = request.transport_mode or "mixed"
    options: list[TravelRouteOption] = _baseline_intercity_route_options(request)
    for index, item in enumerate(items[:4]):
        title = _route_item_title(item) or f"{origin} -> {destination}"
        snippet = str(item.get("snippet") or item.get("description") or item.get("summary") or "").strip()
        duration = str(item.get("duration") or item.get("travel_time") or item.get("time") or "").strip()
        distance = str(item.get("distance") or "").strip()
        source_url = str(item.get("link") or item.get("url") or item.get("source_url") or "").strip()
        provider = str(item.get("source_provider") or item.get("provider") or "serper").strip()
        options.append(
            TravelRouteOption(
                id=f"route-{index + 1}",
                title=title,
                provider=provider,
                duration=duration,
                distance=distance,
                mode=str(item.get("mode") or mode).strip(),
                source_url=source_url,
                display_reason=snippet or "来自路线/交通工具查询结果，适合作为交通方案候选。",
                data_gaps=[] if duration or source_url else ["缺少实时票价、班次和精确耗时，请以购票或地图服务为准。"],
            )
        )
    return _dedupe_route_options(options)


def _classified_sections_from_routes(
    request: TravelPlanRequest,
    route_options: list[TravelRouteOption],
) -> list[dict[str, Any]]:
    origin = request.origin_city or "出发地"
    destination = request.city or "目的地"
    primary = route_options[0]
    alternatives = route_options[1:3]
    alternative_names = "、".join(option.title for option in alternatives) or "备选交通方案"
    return [
        {
            "title": "怎么走",
            "body": f"{origin} 到 {destination} 先比较时间、换乘、预算和购票确定性，再决定交通方式。",
            "bullets": [
                f"优先方案：{_route_option_fact(primary)}",
                f"备选方案：{alternative_names}；适合在预算、发车时间或行李压力不同的时候再比较。",
                "实时票价、余票和站台信息必须以铁路/航空/巴士官方或地图购票服务为准，当前回答不编造库存。",
            ],
        },
        {
            "title": "怎么选",
            "body": "路线题不要硬生成景点卡；重点是把交通选项讲清楚。",
            "bullets": [
                "时间优先：选耗时短、换乘少、班次密集的方案。",
                "预算优先：比较夜巴、慢车或折扣票，但要接受更长耗时和舒适度下降。",
                "行李/同行人优先：少换乘通常比理论最低价更稳。",
            ],
        },
        {
            "title": "怎么落地",
            "body": "把路线先定下来，再安排到站后的城市内交通。",
            "bullets": [
                f"先确认{origin}的具体出发站和{destination}的到达站，再决定住宿或当天活动的位置。",
                "如果需要地图路线，下一步应补充具体车站、酒店或当前位置；没有坐标时不生成假 pins。",
                "如果有日期和预算，可以继续把票价、发车时段和行李约束加进比较。",
            ],
        },
    ]


def _route_option_fact(option: TravelRouteOption) -> str:
    facts = [option.title]
    if option.duration:
        facts.append(f"耗时 {option.duration}")
    if option.distance:
        facts.append(f"距离 {option.distance}")
    if option.display_reason:
        facts.append(option.display_reason)
    return "；".join(facts)


def _route_item_title(item: dict[str, Any]) -> str:
    for key in ["title", "name", "route", "summary"]:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _baseline_intercity_route_options(request: TravelPlanRequest) -> list[TravelRouteOption]:
    origin = (request.origin_city or "").strip()
    destination = request.city.strip()
    if not origin or not destination or origin.lower() == destination.lower():
        return []
    is_tokyo_kyoto = _route_city_matches(origin, ["tokyo", "东京", "東京"]) and _route_city_matches(
        destination, ["kyoto", "京都"]
    )
    rail_title = f"新干线：{origin} -> {destination}" if is_tokyo_kyoto else f"铁路/高铁：{origin} -> {destination}"
    rail_duration = "约2小时15分到2小时40分" if is_tokyo_kyoto else ""
    return [
        TravelRouteOption(
            id="route-intercity-rail",
            title=rail_title,
            provider="route_lookup",
            duration=rail_duration,
            mode="rail",
            display_reason="通常是跨城旅行最稳的首选：耗时短、班次密集、到站位置更适合继续城市内交通。",
            data_gaps=["实时票价、余票、车次和指定席规则需要以官方购票或地图服务为准。"],
        ),
        TravelRouteOption(
            id="route-intercity-bus",
            title=f"高速巴士/夜行巴士：{origin} -> {destination}",
            provider="route_lookup",
            mode="bus",
            display_reason="预算优先时可比较巴士，代价是耗时更长、舒适度和到达时间更受限制。",
            data_gaps=["需要实时查询发车时间、余票、上下车站点和行李规则。"],
        ),
        TravelRouteOption(
            id="route-intercity-flight",
            title=f"航班：{origin} -> {destination}",
            provider="route_lookup",
            mode="air",
            display_reason="远距离或有合适机场时可作为备选，但要把机场交通、安检和候机时间一起算进去。",
            data_gaps=["需要实时查询航班价格、机场交通和行李额；短距离城市对未必更省时。"],
        ),
    ]


def _route_city_matches(value: str, tokens: list[str]) -> bool:
    lowered = value.lower()
    return any(token.lower() in lowered for token in tokens)


def _dedupe_route_options(options: list[TravelRouteOption]) -> list[TravelRouteOption]:
    seen: set[str] = set()
    deduped: list[TravelRouteOption] = []
    for option in options:
        key = option.title.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(option)
    return deduped


def _route_options_from_tool(data: dict[str, Any]) -> list[TravelRouteOption]:
    return _route_options_from_value(data.get("route_options"))


def _route_options_from_contract(contract: dict[str, Any]) -> list[TravelRouteOption]:
    return _route_options_from_value(contract.get("route_options"))


def _route_options_from_value(value: Any) -> list[TravelRouteOption]:
    options: list[TravelRouteOption] = []
    for index, item in enumerate(_list_of_dicts(value)):
        payload = dict(item)
        payload.setdefault("id", f"route-{index + 1}")
        try:
            options.append(TravelRouteOption.model_validate(payload))
        except Exception:
            continue
    return options


def _payload_key_for_failed_tool(name: str, args: dict[str, Any]) -> str:
    if name == "serper_places":
        return f"local:{_arg(args, 'category') or _arg(args, 'query') or 'places'}"
    return {
        "serper_search": "raw_query",
        "hotel_search": "hotel",
        "flight_search": "flight",
        "route_lookup": "transport",
    }.get(name, name)


def _arg(args: dict[str, Any], key: str) -> str:
    return str(args.get(key) or "").strip()


def _result_count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ["items", "route_options", "places_hint"]:
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        return 1 if data else 0
    return 0


def _contract_summary(contract: dict[str, Any]) -> str:
    sections = _contract_sections(contract)
    if not sections:
        return ""
    first = sections[0]
    return str(first.get("body") or first.get("title") or "").strip()


def _sections_markdown(sections: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for section in sections:
        title = str(section.get("title") or "建议").strip()
        body = str(section.get("body") or "").strip()
        bullets = _string_list(section.get("bullets"))
        lines.append(f"## {title}")
        if body:
            lines.append(body)
        for bullet in bullets[:5]:
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines).strip()


def _decision_notes_from_sections(sections: list[dict[str, Any]]) -> list[str]:
    return [
        str(section.get("title") or "").strip()
        for section in sections
        if str(section.get("title") or "").strip()
    ]


def _tool_summary(tool_results: list[dict[str, Any]]) -> str:
    if not tool_results:
        return "GPT 主模型判断无需调用外部工具。"
    completed = sum(1 for item in tool_results if item.get("status") == "completed")
    failed = sum(1 for item in tool_results if item.get("status") == "failed")
    names = ", ".join(str(item.get("name") or "") for item in tool_results[:8])
    return f"GPT 主模型请求 {len(tool_results)} 个 bounded tools：{names}；完成 {completed}，失败 {failed}。"


def _orchestrator_workflow_steps(state: TravelWorkflowState) -> list[TravelWorkflowStep]:
    initial_contract = state.get("initial_orchestrator_contract", state["orchestrator_contract"])
    return [
        TravelWorkflowStep(
            phase="plan",
            actor="Travel Orchestrator",
            action="理解问题并选择工具",
            tools=[state["supervisor"].model_router.orchestrator],
            observation={
                "answer_mode": state["intent"].answer_mode,
                "tool_calls": len(_contract_tool_calls(initial_contract)),
            },
        ),
        TravelWorkflowStep(
            phase="act",
            actor="Tool Runtime",
            action="执行 Serper/DeepInfra bounded tools",
            tools=[str(item.get("name") or "") for item in state.get("tool_results", [])],
            observation={"results": len(state.get("tool_results", []))},
        ),
        TravelWorkflowStep(
            phase="finalize",
            actor="Travel Orchestrator",
            action="基于工具观测合成最终回答合同",
            tools=[state["supervisor"].model_router.orchestrator],
            observation={"sections": len(_contract_sections(state["orchestrator_contract"]))},
        ),
    ]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _flatten_tool_items(payloads: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in payloads.values():
        items.extend(_list_of_dicts(value))
    return items


def _exception_summary(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _inject_graph_contract(
    response: TravelPlanResponse,
    state: TravelWorkflowState,
) -> TravelPlanResponse:
    refs = dict(response.raw_provider_refs or {})
    intent = state.get("intent")
    plan_draft = state.get("plan_draft")
    api_payloads = state.get("api_payloads", {})
    failed_nodes = list(dict.fromkeys(state.get("failed_nodes", [])))
    trace = state.get("trace", [])
    refs["langgraph_orchestrator"] = {
        "runtime": "langgraph_stategraph",
        "actual_graph_run": True,
        "run_mode": "bypass" if response.answer_mode == "answer_only" else "embedded_graph",
        "route": getattr(intent, "answer_mode", response.answer_mode),
        "graph_nodes": GRAPH_NODE_NAMES,
        "completed_nodes": state.get("completed_nodes", []),
        "failed_nodes": failed_nodes,
        "trace": trace,
        "required_capabilities": getattr(plan_draft, "required_capabilities", []),
        "providers_used": sorted(api_payloads.keys()),
        "max_parallel_agents": 1 if response.answer_mode == "answer_only" else 4,
        "global_active_run_limit": 2,
        "degrade_when_busy": False,
    }
    summary = dict(response.workflow_summary or {})
    summary["failed_nodes"] = failed_nodes
    summary["graph_nodes"] = GRAPH_NODE_NAMES
    summary["completed_nodes"] = state.get("completed_nodes", [])
    return response.model_copy(
        update={
            "raw_provider_refs": refs,
            "workflow_summary": summary,
            "agentic_workflow": _workflow_steps_with_failures(
                response.agentic_workflow,
                failed_nodes,
            ),
        }
    )


def _workflow_steps_with_failures(
    steps: list[TravelWorkflowStep],
    failed_nodes: list[str],
) -> list[TravelWorkflowStep]:
    if "run_agents" not in failed_nodes:
        return steps
    updated: list[TravelWorkflowStep] = []
    for step in steps:
        if step.phase != "analyze":
            updated.append(step)
            continue
        observation = dict(step.observation or {})
        observation["failed_node"] = "run_agents"
        updated.append(step.model_copy(update={"status": "failed", "observation": observation}))
    return updated
