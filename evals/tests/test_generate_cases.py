import json

from evals.mira_eval.generate_cases import parse_generated_cases


def test_parse_generated_cases_filters_cases_missing_required_fields():
    raw = json.dumps({
        "cases": [
            {"id": "ok-1", "suite": "travel_answer", "endpoint": "/api/travel/chat", "method": "POST", "body": {}, "checks": []},
            {"id": "bad-1", "suite": "travel_answer"},
        ]
    })

    cases = parse_generated_cases(raw)

    assert [case.id for case in cases] == ["ok-1"]
