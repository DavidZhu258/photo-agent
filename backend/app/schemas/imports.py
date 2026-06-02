from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceImportItem(BaseModel):
    place_name: str
    place_name_ja: str | None = None
    place_name_en: str | None = None
    city: str | None = None
    category: str = "unknown"
    lat: float | None = None
    lng: float | None = None
    source_type: str
    source_name: str
    title: str
    snippet: str
    url: str | None = None
    source_score: float = 0.5
    ad_risk: float = 0.0
    local_signal: float = 0.0
    tourist_signal: float = 0.0
    tags: list[str] = Field(default_factory=list)


class EvidenceImportSummary(BaseModel):
    places_upserted: int
    aliases_created: int
    evidence_created: int

