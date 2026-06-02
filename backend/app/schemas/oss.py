from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OpenSourceTraceStep(BaseModel):
    step_id: str
    framework: str
    title: str
    summary: str
    status: str = "completed"
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenSourceApiSource(BaseModel):
    provider: str
    name: str
    source_type: str
    format: str
    commercial: bool = False
    status: str = "configured"
    url: str | None = None
    ad_risk: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenSourceCacheInfo(BaseModel):
    provider: str = "redis"
    key: str = ""
    hit: bool = False
    ttl_seconds: int = 900
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualMatch(BaseModel):
    provider: str
    title: str
    source: str
    url: str | None = None
    thumbnail_url: str | None = None
    match_type: str = "visual_match"
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
