from __future__ import annotations

from typing import Any

from app.schemas.travel import TravelPlanRequest
from app.services.grounded_answer.schemas import (
    EvidenceCandidate,
    ExtractedCandidate,
    GroundedAnswerResult,
    SearchResultDocument,
)


class SerperSearchResultAdapter:
    """Convert Serper Search/Places records into Pydantic grounding documents."""

    def to_documents(self, raw_results: list[dict[str, Any]]) -> list[SearchResultDocument]:
        documents = []
        for index, item in enumerate(raw_results):
            title = _text(item.get("title") or item.get("name"))
            address = _text(item.get("address"))
            snippet = _text(item.get("snippet") or item.get("description"))
            link = _text(item.get("link") or item.get("website"))
            content = " ".join(part for part in [title, address, snippet, link] if part)
            documents.append(
                SearchResultDocument(
                    content=content,
                    title=title,
                    address=address,
                    snippet=snippet,
                    link=link,
                    endpoint=_text(item.get("serper_endpoint")) or "raw_query",
                    query_variant=_text(item.get("query_variant")),
                    source_rank=index,
                    raw=dict(item),
                )
            )
        return documents


class CandidateExtractor:
    """Pydantic structured extraction layer.

    This is deterministic for P0, but the input/output contract mirrors a
    PydanticAI extractor agent with a typed output model.
    """

    def extract(self, documents: list[SearchResultDocument]) -> list[ExtractedCandidate]:
        candidates = []
        for document in documents:
            name = document.title or "未命名候选"
            excerpt = document.address or document.snippet or document.link or "Serper 返回候选，缺少地址/摘要。"
            candidates.append(
                ExtractedCandidate(
                    name=name,
                    address=document.address,
                    evidence_excerpt=excerpt,
                    source_endpoint=document.endpoint,
                    source_query=document.query_variant,
                    source_url=document.link,
                    raw_text=document.content,
                    source_rank=document.source_rank,
                )
            )
        return candidates


class CandidateVerifier:
    """Typed verifier/reranker for grounded candidates."""

    def verify(
        self,
        *,
        request: TravelPlanRequest,
        candidates: list[ExtractedCandidate],
    ) -> list[EvidenceCandidate]:
        verified = [self._verify_one(request, candidate) for candidate in candidates]
        return sorted(
            verified,
            key=lambda item: (
                _match_label_rank(item.match_label),
                item.raw_relevance_score,
                -_source_rank(candidates, item),
            ),
            reverse=True,
        )[:6]

    def _verify_one(
        self,
        request: TravelPlanRequest,
        candidate: ExtractedCandidate,
    ) -> EvidenceCandidate:
        match_label = _candidate_match_label(request, candidate)
        evidence_type = _candidate_evidence_type(request, candidate)
        source_display = _source_display(candidate)
        score = _relevance_score(request, candidate)
        return EvidenceCandidate(
            name=candidate.name,
            match_label=match_label,
            evidence_type=evidence_type,
            evidence_excerpt=candidate.evidence_excerpt,
            source_endpoint=candidate.source_endpoint,
            source_query=candidate.source_query,
            source_url=candidate.source_url,
            source_display=source_display,
            relevance_reason=_relevance_reason(match_label),
            raw_relevance_score=score,
        )


class GroundedSynthesizer:
    """Render grounded candidates without adding unsupported facts."""

    def synthesize(
        self,
        *,
        request: TravelPlanRequest,
        candidates: list[EvidenceCandidate],
        optional_followups: list[str] | None = None,
    ) -> GroundedAnswerResult:
        optional_followups = optional_followups or []
        lines = [
            "## 证据候选表",
            "以下按搜索原始字段抽取、分类和排序；只展示可追溯信息，不改写成未验证门店。",
            "",
            "| 候选 | 匹配等级 | 类型 | 地址/摘要 | 来源 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for candidate in candidates[:6]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _table_cell(candidate.name),
                        _table_cell(candidate.match_label),
                        _table_cell(candidate.evidence_type),
                        _table_cell(candidate.evidence_excerpt),
                        _table_cell(candidate.source_display),
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## 判断说明",
                *[f"- {candidate.name}: {candidate.relevance_reason}" for candidate in candidates[:5]],
                "",
                "## 结论",
                _conclusion(request, candidates),
            ]
        )
        if optional_followups:
            lines.extend(["", "## 需要当天确认", *[f"- {item}" for item in optional_followups[:3]]])
        return GroundedAnswerResult(
            candidates=candidates,
            markdown="\n".join(lines),
            short_answer=_conclusion(request, candidates),
            pipeline_meta=grounded_answer_pipeline_meta(),
        )


class GroundedAnswerPipeline:
    """Small Pydantic-first pipeline inspired by PydanticAI structured outputs."""

    def __init__(
        self,
        *,
        extractor: CandidateExtractor | None = None,
        verifier: CandidateVerifier | None = None,
        synthesizer: GroundedSynthesizer | None = None,
    ) -> None:
        self.extractor = extractor or CandidateExtractor()
        self.verifier = verifier or CandidateVerifier()
        self.synthesizer = synthesizer or GroundedSynthesizer()

    def run(
        self,
        *,
        request: TravelPlanRequest,
        documents: list[SearchResultDocument],
        optional_followups: list[str] | None = None,
    ) -> GroundedAnswerResult:
        extracted = self.extractor.extract(documents)
        verified = self.verifier.verify(request=request, candidates=extracted)
        return self.synthesizer.synthesize(
            request=request,
            candidates=verified,
            optional_followups=optional_followups,
        )


def grounded_answer_pipeline_meta() -> dict[str, object]:
    return {
        "framework": "pydantic",
        "pydantic_ai_ready": True,
        "structured_output": "GroundedAnswerResult",
        "components": [
            "SerperSearchResultAdapter",
            "CandidateExtractor",
            "CandidateVerifier",
            "GroundedSynthesizer",
        ],
    }


def _candidate_text(candidate: ExtractedCandidate) -> str:
    return " ".join(
        [
            candidate.name,
            candidate.address,
            candidate.evidence_excerpt,
            candidate.source_url,
            candidate.raw_text,
        ]
    ).lower()


def _candidate_match_label(request: TravelPlanRequest, candidate: ExtractedCandidate) -> str:
    text = _candidate_text(candidate)
    if _is_fragrance_query(request) and _looks_like_non_fragrance_nicolai(candidate):
        return "category_unconfirmed"
    has_nicolai = "nicolai" in text or "ニコライ" in text
    has_fragrance = _has_fragrance_marker(text)
    if "nose shop" in text and _is_fragrance_query(request):
        return "likely_match"
    if has_nicolai and has_fragrance:
        return "exact_match"
    if has_fragrance:
        return "category_match"
    return "weak_match"


def _candidate_evidence_type(request: TravelPlanRequest, candidate: ExtractedCandidate) -> str:
    text = _candidate_text(candidate)
    if _is_fragrance_query(request) and _looks_like_non_fragrance_nicolai(candidate):
        return "name_match_other_category"
    if "nose shop" in text or _has_fragrance_marker(text):
        return "fragrance_store"
    if candidate.source_endpoint == "search":
        return "web_result"
    return "place_result"


def _looks_like_non_fragrance_nicolai(candidate: ExtractedCandidate) -> bool:
    text = _candidate_text(candidate)
    has_nicolai = "nicolai" in text or "ニコライ" in text
    has_fragrance = _has_fragrance_marker(text)
    has_other_category = any(token in text for token in ["flower", "flowers", "花", "フラワー", "design"])
    return has_nicolai and has_other_category and not has_fragrance


def _is_fragrance_query(request: TravelPlanRequest) -> bool:
    text = request.query.lower()
    return any(
        token in text or token in request.query
        for token in ["香水", "perfume", "fragrance", "parfum", "パルファム"]
    )


def _has_fragrance_marker(text: str) -> bool:
    return any(
        token in text
        for token in [
            "香水",
            "perfume",
            "fragrance",
            "parfum",
            "パルファム",
            "フレグランス",
        ]
    )


def _relevance_score(request: TravelPlanRequest, candidate: ExtractedCandidate) -> int:
    text = _candidate_text(candidate)
    query = request.query.lower()
    score = 0
    for token in ["nicolai", "ニコライ"]:
        if token in query and token in text:
            score += 6
    if "nose shop" in text:
        score += 5
    if _has_fragrance_marker(text):
        score += 2
    if "fukuoka" in text or "福岡" in text or "福冈" in text:
        score += 1
    return score


def _relevance_reason(match_label: str) -> str:
    return {
        "exact_match": "名称和香水/香氛线索同时出现在同一候选中，优先核对。",
        "likely_match": "香水集合店或 NOSE SHOP 相关结果，可能可试闻/购买，但库存需当天确认。",
        "category_match": "与香水店类别匹配，但未证明销售目标品牌。",
        "category_unconfirmed": "名称匹配但品类未确认：可能不是香水售卖点。",
        "weak_match": "弱相关候选，只作为搜索备选保留。",
    }.get(match_label, "弱相关候选，只作为搜索备选保留。")


def _source_display(candidate: ExtractedCandidate) -> str:
    pieces = [f"Serper {candidate.source_endpoint}"]
    if candidate.source_query:
        pieces.append(candidate.source_query)
    if candidate.source_url:
        pieces.append(candidate.source_url)
    return " / ".join(pieces)


def _match_label_rank(label: str) -> int:
    return {
        "exact_match": 5,
        "likely_match": 4,
        "category_match": 3,
        "category_unconfirmed": 2,
        "weak_match": 1,
        "irrelevant": 0,
    }.get(label, 0)


def _source_rank(candidates: list[ExtractedCandidate], item: EvidenceCandidate) -> int:
    for candidate in candidates:
        if candidate.name == item.name and candidate.source_query == item.source_query:
            return candidate.source_rank
    return 999


def _conclusion(request: TravelPlanRequest, candidates: list[EvidenceCandidate]) -> str:
    top = candidates[0].name if candidates else ""
    if top:
        return (
            f"当前最接近“{request.query}”的候选是 **{top}**。"
            "这不是自动等同于目标品牌现货；请以店铺页、电话或当天库存为准。"
        )
    return "当前没有足够明确的原始候选；建议换日文/英文品牌词继续搜。"


def _table_cell(value: str) -> str:
    text = str(value).replace("|", "/").replace("\n", " ").strip()
    return text[:220] + ("..." if len(text) > 220 else "")


def _text(value: object) -> str:
    return str(value or "").strip()

