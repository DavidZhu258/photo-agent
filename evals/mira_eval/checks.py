from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from evals.mira_eval.schemas import CheckResult, EvalCase


DEFAULT_RAW_ERROR_TERMS = [
    "Traceback",
    "Authorization",
    "Bearer ",
    "sk-",
    "api_key",
    "stack trace",
    "Internal Server Error",
]


def run_deterministic_checks(case: EvalCase, response: dict[str, Any]) -> list[CheckResult]:
    return [_run_one_check(check, response) for check in case.checks]


def _run_one_check(check: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    check_type = str(check.get("type") or "").strip()
    if check_type == "status_code":
        return _check_status_code(check, response)
    if check_type == "assistant_text_contains_any":
        return _check_assistant_text_contains_any(check, response)
    if check_type == "no_trip_cards":
        return _check_no_trip_cards(response)
    if check_type == "has_trip_cards":
        return _check_has_trip_cards(check, response)
    if check_type == "has_ready_trip_map":
        return _check_has_ready_trip_map(response)
    if check_type == "json_path_present":
        return _check_json_path_present(check, response)
    if check_type == "no_raw_error_terms":
        return _check_no_raw_error_terms(check, response)
    return CheckResult(check_type or "unknown", False, f"Unsupported check type: {check_type}")


def _check_status_code(check: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected = int(check.get("expected", 200))
    actual = response.get("status_code")
    passed = actual == expected
    return CheckResult(
        "status_code",
        passed,
        f"Expected HTTP {expected}, got HTTP {actual}.",
    )


def _check_assistant_text_contains_any(check: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    terms = [str(term) for term in check.get("terms", [])]
    text = assistant_text(response.get("json"))
    matched = [term for term in terms if term and term in text]
    return CheckResult(
        "assistant_text_contains_any",
        bool(matched),
        f"Matched terms: {matched}" if matched else f"No required terms found in assistant text: {terms}",
    )


def _check_no_trip_cards(response: dict[str, Any]) -> CheckResult:
    cards = trip_cards(response.get("json"))
    return CheckResult(
        "no_trip_cards",
        len(cards) == 0,
        "No trip cards found." if not cards else f"Unexpected trip cards count: {len(cards)}.",
    )


def _check_has_trip_cards(check: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    min_count = int(check.get("min_count", 1))
    cards = trip_cards(response.get("json"))
    return CheckResult(
        "has_trip_cards",
        len(cards) >= min_count,
        f"Trip cards count: {len(cards)}, required: {min_count}.",
    )


def _check_has_ready_trip_map(response: dict[str, Any]) -> CheckResult:
    maps = [
        part.get("map")
        for part in _message_parts(response.get("json"))
        if isinstance(part, Mapping) and part.get("type") == "trip-map" and isinstance(part.get("map"), Mapping)
    ]
    ready_maps = [item for item in maps if item.get("status") == "ready" and _count_sequence(item.get("pins")) > 0]
    return CheckResult(
        "has_ready_trip_map",
        bool(ready_maps),
        "Ready trip map found." if ready_maps else "No ready trip map with pins found.",
    )


def _check_json_path_present(check: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    path = str(check.get("path") or "")
    value = _get_json_path(response.get("json"), path)
    return CheckResult(
        f"json_path_present:{path}",
        value is not None,
        f"Path {path} is present." if value is not None else f"Path {path} is missing.",
    )


def _check_no_raw_error_terms(check: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    terms = [str(term) for term in check.get("terms", DEFAULT_RAW_ERROR_TERMS)]
    text = json.dumps(response.get("json"), ensure_ascii=False, sort_keys=True)
    found = [term for term in terms if term and term in text]
    return CheckResult(
        "no_raw_error_terms",
        not found,
        "No raw error terms found." if not found else f"Raw error terms found: {found}",
    )


def assistant_text(body: object) -> str:
    texts = [
        str(part.get("text"))
        for part in _message_parts(body)
        if isinstance(part, Mapping) and part.get("type") == "text" and isinstance(part.get("text"), str)
    ]
    if texts:
        return "\n".join(texts)
    if isinstance(body, Mapping):
        message = body.get("message")
        if isinstance(message, str):
            return message
    return ""


def trip_cards(body: object) -> list[object]:
    cards: list[object] = []
    for part in _message_parts(body):
        if isinstance(part, Mapping) and part.get("type") == "trip-cards":
            raw_cards = part.get("cards")
            if isinstance(raw_cards, Sequence) and not isinstance(raw_cards, (str, bytes)):
                cards.extend(list(raw_cards))
    return cards


def _message_parts(body: object) -> list[object]:
    if not isinstance(body, Mapping):
        return []
    message = body.get("message")
    if not isinstance(message, Mapping):
        return []
    parts = message.get("parts")
    if isinstance(parts, Sequence) and not isinstance(parts, (str, bytes)):
        return list(parts)
    return []


def _get_json_path(body: object, path: str) -> object | None:
    current = body
    for segment in path.split("."):
        if not segment:
            continue
        if isinstance(current, Mapping):
            current = current.get(segment)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)) and segment.isdigit():
            index = int(segment)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _count_sequence(value: object) -> int:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    return 0
