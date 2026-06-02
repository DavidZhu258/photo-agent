from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MatchLabel = Literal[
    "exact_match",
    "likely_match",
    "category_match",
    "category_unconfirmed",
    "weak_match",
    "irrelevant",
]

EvidenceType = Literal[
    "fragrance_store",
    "name_match_other_category",
    "web_result",
    "place_result",
    "unknown",
]


class SearchResultDocument(BaseModel):
    """Normalized search result document used as the grounding unit."""

    content: str = Field(description="Raw searchable text assembled from title, address, snippet, and link.")
    title: str = ""
    address: str = ""
    snippet: str = ""
    link: str = ""
    endpoint: str = "raw_query"
    query_variant: str = ""
    source_rank: int = 0
    raw: dict[str, object] = Field(default_factory=dict)


class ExtractedCandidate(BaseModel):
    """Structured candidate extracted from one search result."""

    name: str
    address: str = ""
    evidence_excerpt: str
    source_endpoint: str = "raw_query"
    source_query: str = ""
    source_url: str = ""
    raw_text: str = ""
    source_rank: int = 0


class EvidenceCandidate(BaseModel):
    """Verified candidate that is safe to render or synthesize from."""

    name: str
    match_label: MatchLabel
    evidence_type: EvidenceType
    evidence_excerpt: str
    source_endpoint: str
    source_query: str = ""
    source_url: str = ""
    source_display: str
    relevance_reason: str
    raw_relevance_score: int = 0


class GroundedAnswerResult(BaseModel):
    """Final grounded answer product with typed intermediate evidence."""

    answer_type: str = "store_lookup"
    candidates: list[EvidenceCandidate] = Field(default_factory=list)
    markdown: str
    short_answer: str
    pipeline_meta: dict[str, object] = Field(default_factory=dict)

