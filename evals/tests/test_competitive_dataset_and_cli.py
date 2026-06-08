from evals.mira_eval.compare import build_arg_parser
from evals.mira_eval.runner import load_jsonl_cases


def test_competitive_dataset_has_enough_representative_product_cases():
    cases = load_jsonl_cases("evals/datasets/mira_competitive.jsonl")
    suites = {case.suite for case in cases}

    assert len(cases) >= 30
    assert {
        "travel_answer",
        "travel_recommendation",
        "travel_planning",
        "travel_constraints",
        "safety_regression",
        "visual_discovery",
    }.issubset(suites)
    assert all(case.judge and "rubric" in case.judge for case in cases if case.method != "GET")
    assert any(case.judge and float(case.judge.get("weight", 1.0)) > 1.0 for case in cases)


def test_compare_cli_parses_targets_and_outputs():
    parser = build_arg_parser()

    args = parser.parse_args(
        [
            "--dataset",
            "evals/datasets/mira_competitive.jsonl",
            "--base-url",
            "https://mira.example",
            "--targets",
            "mira,generic_gpt,travel_gpt",
            "--output-json",
            "reports/evals/compare.json",
            "--output-md",
            "reports/evals/compare.md",
            "--limit",
            "3",
        ]
    )

    assert args.dataset == "evals/datasets/mira_competitive.jsonl"
    assert args.base_url == "https://mira.example"
    assert args.targets == "mira,generic_gpt,travel_gpt"
    assert args.output_json == "reports/evals/compare.json"
    assert args.output_md == "reports/evals/compare.md"
    assert args.limit == 3
