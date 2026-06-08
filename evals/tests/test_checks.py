from evals.mira_eval.checks import run_deterministic_checks
from evals.mira_eval.schemas import EvalCase


def test_answer_only_case_passes_without_trip_cards():
    case = EvalCase.from_dict({
        "id": "travel-answer",
        "suite": "travel_answer",
        "endpoint": "/api/travel/chat",
        "method": "POST",
        "body": {},
        "checks": [
            {"type": "status_code", "expected": 200},
            {"type": "assistant_text_contains_any", "terms": ["河豚", "毒素"]},
            {"type": "no_trip_cards"},
        ],
    })
    response = {
        "status_code": 200,
        "json": {"message": {"parts": [{"type": "text", "text": "河豚含有毒素，需要谨慎。"}]}},
    }

    results = run_deterministic_checks(case, response)

    assert all(result.passed for result in results)


def test_place_card_case_requires_cards_and_ready_map():
    case = EvalCase.from_dict({
        "id": "travel-place",
        "suite": "travel_recommendation",
        "endpoint": "/api/travel/chat",
        "method": "POST",
        "body": {},
        "checks": [
            {"type": "has_trip_cards", "min_count": 1},
            {"type": "has_ready_trip_map"},
        ],
    })
    response = {
        "status_code": 200,
        "json": {
            "message": {
                "parts": [
                    {"type": "trip-cards", "cards": [{"title": "大濠公园"}]},
                    {"type": "trip-map", "map": {"status": "ready", "pins": [{"title": "大濠公园"}]}},
                ]
            }
        },
    }

    results = run_deterministic_checks(case, response)

    assert all(result.passed for result in results)
