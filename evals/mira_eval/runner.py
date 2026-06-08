from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from evals.mira_eval.checks import assistant_text, run_deterministic_checks
from evals.mira_eval.judge import build_judge_messages, parse_judge_verdict
from evals.mira_eval.newapi_client import NewApiChatClient
from evals.mira_eval.schemas import CaseResult, CheckResult, EvalCase, EvalRunResult

JudgeMode = Literal["off", "auto", "required"]


def load_jsonl_cases(dataset_path: str | Path) -> list[EvalCase]:
    path = Path(dataset_path)
    cases: list[EvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            cases.append(EvalCase.from_dict(json.loads(stripped)))
        except Exception as exc:  # noqa: BLE001 - convert malformed fixture into a useful line-level error.
            raise ValueError(f"Invalid eval case at {path}:{line_number}: {exc}") from exc
    return cases


async def run_eval_suite(
    *,
    dataset_path: str | Path,
    base_url: str,
    output_path: str | Path | None = None,
    judge_mode: JudgeMode = "auto",
    model: str = "gpt-5.5",
    http_client: httpx.AsyncClient | None = None,
    judge_client: NewApiChatClient | None = None,
    request_timeout: float = 360.0,
) -> EvalRunResult:
    cases = load_jsonl_cases(dataset_path)
    client = http_client or httpx.AsyncClient(timeout=request_timeout)
    should_close_http = http_client is None
    results: list[CaseResult] = []
    try:
        for case in cases:
            results.append(
                await _run_case(
                    case=case,
                    base_url=base_url,
                    http_client=client,
                    judge_mode=judge_mode,
                    model=model,
                    judge_client=judge_client,
                )
            )
    finally:
        if should_close_http:
            await client.aclose()

    summary = _build_summary(results, judge_mode=judge_mode, dataset_path=dataset_path, base_url=base_url)
    run_result = EvalRunResult(summary=summary, cases=results)
    if output_path is not None:
        _write_json(output_path, run_result.to_dict())
    return run_result


async def _run_case(
    *,
    case: EvalCase,
    base_url: str,
    http_client: httpx.AsyncClient,
    judge_mode: JudgeMode,
    model: str,
    judge_client: NewApiChatClient | None,
) -> CaseResult:
    started = time.perf_counter()
    response_payload: dict[str, Any] = {"status_code": None, "json": None}
    error: str | None = None
    try:
        response = await _send_case_request(http_client, base_url, case)
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_payload = {
            "status_code": response.status_code,
            "json": _response_json_or_text(response),
        }
        checks = run_deterministic_checks(case, response_payload)
    except Exception as exc:  # noqa: BLE001 - product evals should record per-case transport failures.
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = _safe_error_message(exc)
        checks = [CheckResult("request", False, error)]

    judge_result = await _maybe_judge_case(
        case=case,
        response_payload=response_payload,
        judge_mode=judge_mode,
        model=model,
        judge_client=judge_client,
    )
    passed = all(check.passed for check in checks)
    if judge_result is not None:
        passed = passed and bool(judge_result.get("pass"))
    return CaseResult(
        case_id=case.id,
        suite=case.suite,
        passed=passed,
        status_code=response_payload.get("status_code"),
        latency_ms=latency_ms,
        checks=checks,
        judge=judge_result,
        error=error,
    )


async def _send_case_request(http_client: httpx.AsyncClient, base_url: str, case: EvalCase) -> httpx.Response:
    url = f"{base_url.rstrip('/')}/{case.endpoint.lstrip('/')}"
    if case.method == "GET":
        return await http_client.get(url)
    return await http_client.request(case.method, url, json=case.body)


def _response_json_or_text(response: httpx.Response) -> object:
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"text": response.text}


async def _maybe_judge_case(
    *,
    case: EvalCase,
    response_payload: dict[str, Any],
    judge_mode: JudgeMode,
    model: str,
    judge_client: NewApiChatClient | None,
) -> dict[str, Any] | None:
    if judge_mode == "off" or not case.judge:
        return None
    if not os.environ.get("NEWAPI_API_KEY") and judge_client is None:
        if judge_mode == "required":
            return {
                "pass": False,
                "score": 0.0,
                "reason": "NEWAPI_API_KEY is required for judge_mode=required.",
                "failed_dimensions": ["missing_judge_key"],
            }
        return {
            "pass": True,
            "score": None,
            "reason": "Judge skipped because NEWAPI_API_KEY is not set.",
            "failed_dimensions": [],
            "skipped": True,
        }

    rubric = str(case.judge.get("rubric") or "").strip()
    threshold = float(case.judge.get("threshold", 0.0))
    question = _case_question(case)
    candidate_output = _candidate_output(response_payload.get("json"))
    client = judge_client or NewApiChatClient()
    try:
        content = await client.chat(
            messages=build_judge_messages(
                question=question,
                candidate_output=candidate_output,
                rubric=rubric,
            ),
            model=model,
            temperature=0.0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        verdict = parse_judge_verdict(content)
        result = verdict.to_dict()
        result["threshold"] = threshold
        result["pass"] = verdict.passed and verdict.score >= threshold
        return result
    except Exception as exc:  # noqa: BLE001 - record judge failures as case-level quality failures.
        return {
            "pass": judge_mode != "required",
            "score": 0.0,
            "reason": _safe_error_message(exc),
            "failed_dimensions": ["judge_error"],
        }


def _case_question(case: EvalCase) -> str:
    messages = case.body.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content
    return case.id


def _candidate_output(body: object) -> str:
    text = assistant_text(body)
    if text:
        return text
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def _build_summary(
    results: list[CaseResult],
    *,
    judge_mode: JudgeMode,
    dataset_path: str | Path,
    base_url: str,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "base_url": base_url,
        "judge_mode": judge_mode,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / total) if total else 0.0,
    }


def _write_json(output_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    for marker in ("Bearer ", "sk-"):
        if marker in message:
            return exc.__class__.__name__
    return message or exc.__class__.__name__
