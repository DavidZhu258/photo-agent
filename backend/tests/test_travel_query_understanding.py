from app.services.travel_query_understanding import (
    CandidateDocument,
    CandidateVerdict,
    SearchPlan,
    TravelIntent,
    _validated_intent,
    _stabilize_verdicts,
)
from app.schemas.travel import TravelPlanRequest


def test_candidate_verifier_accepts_cross_language_surface_matches_for_fugu_places():
    candidates = [
        CandidateDocument(
            candidate_id="raw_query:0",
            title="Bote",
            type="Japanese fugu restaurant",
            category="Puffer fish restaurant",
            address="Fukuoka",
        )
    ]
    verdicts = [
        CandidateVerdict(
            candidate_id="raw_query:0",
            is_relevant=True,
            relevance_score=74,
            matched_requirements=["fugu restaurant"],
            missing_requirements=[],
            match_reason="The place is a fugu restaurant in Fukuoka.",
        )
    ]
    search_plan = SearchPlan(
        tools=["places"],
        query_variants=["福冈 河豚 餐厅 推荐"],
        must_satisfy=["河豚", "福冈", "餐厅"],
    )

    stabilized = _stabilize_verdicts(candidates, verdicts, search_plan)

    assert stabilized[0].is_relevant
    assert stabilized[0].relevance_score >= 80
    assert "fugu" in " ".join(stabilized[0].matched_requirements).lower()


def test_candidate_verifier_accepts_generic_attraction_surface_matches():
    candidates = [
        CandidateDocument(
            candidate_id="local:本地体验:0",
            title="Fukuoka Tower",
            type="Tourist attraction",
            category="",
            address="2 Chome-3-26 Momochihama, Fukuoka",
            raw={"latitude": 33.593285, "longitude": 130.35152},
        )
    ]
    verdicts = [
        CandidateVerdict(
            candidate_id="local:本地体验:0",
            is_relevant=False,
            relevance_score=12,
            matched_requirements=[],
            missing_requirements=["attractions", "local_experiences"],
            match_reason="模型没有识别通用景点词。",
        )
    ]
    search_plan = SearchPlan(
        tools=["serper_search"],
        query_variants=["福冈有什么好玩的？"],
        must_satisfy=["attractions", "local_experiences"],
    )

    stabilized = _stabilize_verdicts(candidates, verdicts, search_plan)

    assert stabilized[0].is_relevant
    assert stabilized[0].relevance_score >= 80
    assert "attraction" in " ".join(stabilized[0].matched_requirements).lower()


def test_query_understanding_accepts_gemini_null_clarifying_question():
    result = {
        "task_type": "travel_question",
        "answer_mode": "answer_only",
        "requires_place": False,
        "destination": "福冈",
        "category": "food_knowledge",
        "target_entity": "河豚",
        "target_type": "fish",
        "requested_outputs": ["explanation of danger"],
        "need_supplier_types": [],
        "must_answer": ["Why pufferfish is dangerous"],
        "should_not_answer": [],
        "constraints": [],
        "capability_plan": {
            "user_goal": "Understand pufferfish risk.",
            "intent_kind": "answer_only",
            "required_capabilities": ["knowledge"],
            "tool_tasks": [
                {
                    "task_id": "knowledge_search",
                    "capability": "knowledge",
                    "query": "河豚 危险原因",
                    "required": True,
                }
            ],
            "agent_tasks": [
                {
                    "task_id": "answer_generation",
                    "agent_role": "destination",
                    "objective": "Explain toxicity.",
                    "input_keys": ["knowledge_search"],
                    "required": True,
                }
            ],
            "answer_contract": {
                "needs_map": False,
                "needs_cards": False,
                "needs_itinerary": False,
                "needs_inventory": False,
                "response_style": "narrative",
            },
            "confidence": 0.99,
        },
        "confidence": 0.99,
        "clarifying_question": None,
    }

    intent = _validated_intent(
        result,
        TravelPlanRequest(city="福冈", query="河豚为什么危险？它是什么鱼？", allow_web_search=False),
    )

    assert isinstance(intent, TravelIntent)
    assert intent.answer_mode == "answer_only"
    assert intent.clarifying_question == ""
