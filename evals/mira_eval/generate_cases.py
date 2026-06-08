from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from evals.mira_eval.newapi_client import NewApiChatClient
from evals.mira_eval.schemas import EvalCase


REQUIRED_CASE_FIELDS = {"id", "suite", "endpoint", "method", "body", "checks"}


def parse_generated_cases(content: str) -> list[EvalCase]:
    """Parse GPT-generated cases and keep only complete, reviewable cases."""
    parsed = json.loads(_extract_json_text(content))
    raw_cases = parsed.get("cases") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_cases, list):
        return []

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            continue
        if not REQUIRED_CASE_FIELDS.issubset(raw_case):
            continue
        try:
            case = EvalCase.from_dict(raw_case)
        except (KeyError, TypeError, ValueError):
            continue
        if case.id in seen:
            continue
        seen.add(case.id)
        cases.append(case)
    return cases


async def generate_cases(
    *,
    output_path: str | Path,
    count: int = 10,
    model: str = "gpt-5.5",
    client: NewApiChatClient | None = None,
) -> list[EvalCase]:
    """Ask GPT to draft additional eval cases and write them as JSONL."""
    prompt = _generation_prompt(count)
    chat_client = client or NewApiChatClient()
    content = await chat_client.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate practical product evaluation cases for Mira. "
                    "Return only JSON. Do not include secrets or live credentials."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        model=model,
        temperature=0.4,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    cases = parse_generated_cases(content)
    _write_jsonl(output_path, cases)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reviewable Mira eval cases using NewAPI GPT.")
    parser.add_argument("--output", default="evals/datasets/generated_mira_cases.jsonl")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    cases = asyncio.run(generate_cases(output_path=args.output, count=args.count, model=args.model))
    print(f"Generated {len(cases)} cases into {args.output}. Review before using as a gate.")


def _generation_prompt(count: int) -> str:
    return f"""
Generate {count} JSON eval cases for Mira, an AI travel and visual discovery product.

Return this exact top-level JSON shape:
{{
  "cases": [
    {{
      "id": "unique-short-id",
      "suite": "travel_answer|travel_recommendation|visual_discovery|mobile_job|safety_regression",
      "endpoint": "/api/travel/chat",
      "method": "POST",
      "body": {{}},
      "checks": [],
      "judge": {{"rubric": "one clear effectiveness criterion", "threshold": 0.8}}
    }}
  ]
}}

Use these endpoint patterns:
- Travel chat: endpoint "/api/travel/chat", body {{"messages":[{{"role":"user","content":"..."}}],"context":{{}}}}
- Visual GET contract: endpoint "/api-backend/v1/visual/discover", method "GET", body {{}}

Use deterministic checks from this list only:
- {{"type":"status_code","expected":200}}
- {{"type":"assistant_text_contains_any","terms":["term1","term2"]}}
- {{"type":"no_trip_cards"}}
- {{"type":"has_trip_cards","min_count":1}}
- {{"type":"has_ready_trip_map"}}
- {{"type":"json_path_present","path":"status"}}
- {{"type":"no_raw_error_terms"}}

Prefer realistic Chinese and English user questions. Include adversarial cases, but never include real API keys.
""".strip()


def _write_jsonl(output_path: str | Path, cases: list[EvalCase]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True) for case in cases]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _extract_json_text(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


if __name__ == "__main__":
    main()
