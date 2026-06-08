from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    id: str
    suite: str
    endpoint: str
    method: str
    body: dict[str, Any]
    checks: list[dict[str, Any]] = field(default_factory=list)
    judge: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvalCase":
        return cls(
            id=str(value["id"]),
            suite=str(value["suite"]),
            endpoint=str(value["endpoint"]),
            method=str(value.get("method", "POST")).upper(),
            body=dict(value.get("body") or {}),
            checks=[dict(check) for check in value.get("checks", [])],
            judge=dict(value["judge"]) if isinstance(value.get("judge"), dict) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "suite": self.suite,
            "endpoint": self.endpoint,
            "method": self.method,
            "body": self.body,
            "checks": self.checks,
        }
        if self.judge is not None:
            result["judge"] = self.judge
        return result


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "pass": self.passed, "reason": self.reason}


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    suite: str
    passed: bool
    status_code: int | None
    latency_ms: int | None
    checks: list[CheckResult]
    judge: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "case_id": self.case_id,
            "suite": self.suite,
            "pass": self.passed,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.judge is not None:
            result["judge"] = self.judge
        if self.error:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class EvalRunResult:
    summary: dict[str, Any]
    cases: list[CaseResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "cases": [case.to_dict() for case in self.cases],
        }
