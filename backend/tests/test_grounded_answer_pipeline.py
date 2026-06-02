from __future__ import annotations

from app.schemas.travel import TravelPlanRequest
from app.services.grounded_answer import (
    EvidenceCandidate,
    GroundedAnswerPipeline,
    GroundedAnswerResult,
    SerperSearchResultAdapter,
)


def test_pydantic_grounded_answer_pipeline_preserves_sources_and_labels():
    request = TravelPlanRequest(city="Fukuoka", query="福冈 Nicolai 香水，哪里可以买？")
    raw_results = [
        {
            "title": "NOSE SHOP 福岡",
            "address": "天神2丁目5-35 岩田屋本店 新館 1F",
            "serper_endpoint": "places",
            "query_variant": "福冈 Nicolai 香水，哪里可以买？",
        },
        {
            "title": "Nicolai Bergmann Flowers & Design Fukuoka Store",
            "snippet": "Flower and design store in Iwataya Annex.",
            "serper_endpoint": "search",
            "query_variant": "福冈 Nicolai 香水，哪里可以买？",
        },
        {
            "title": "MY ONLY FRAGRANCE HAKATA【博多】",
            "snippet": "Generic fragrance shop in Hakata.",
            "serper_endpoint": "places",
            "query_variant": "Nicolai Parfumeur 福岡",
        },
    ]

    documents = SerperSearchResultAdapter().to_documents(raw_results)
    result = GroundedAnswerPipeline().run(request=request, documents=documents)

    assert isinstance(result, GroundedAnswerResult)
    assert all(isinstance(candidate, EvidenceCandidate) for candidate in result.candidates)
    assert result.candidates[0].name == "NOSE SHOP 福岡"
    assert result.candidates[0].match_label == "likely_match"
    assert result.candidates[0].evidence_type == "fragrance_store"
    assert result.candidates[0].source_query == "福冈 Nicolai 香水，哪里可以买？"
    assert any(
        candidate.name == "Nicolai Bergmann Flowers & Design Fukuoka Store"
        and candidate.match_label == "category_unconfirmed"
        for candidate in result.candidates
    )
    assert "## 证据候选表" in result.markdown
    assert "| 候选 | 匹配等级 | 类型 | 地址/摘要 | 来源 |" in result.markdown
    assert "## 查询变体" not in result.markdown
    assert result.pipeline_meta["framework"] == "pydantic"
    assert result.pipeline_meta["pydantic_ai_ready"] is True
