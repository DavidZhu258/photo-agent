from app.schemas.visual import EvidenceCard, PlaceCandidate
from app.services.ranking import RecommendationRanker


def test_ranker_prefers_interest_matched_quiet_place_over_tourist_hotspot():
    ranker = RecommendationRanker()
    quiet_temple = PlaceCandidate(
        place_id=1,
        name="Shoren-in Monzeki",
        name_ja="青蓮院門跡",
        category="temple",
        lat=35.0076,
        lng=135.7825,
        confidence=0.82,
        match_reason="OCR and nearby aliases matched",
        distance_meters=120.0,
        tags=["quiet", "garden", "history"],
        photo_potential=0.86,
    )
    tourist_hotspot = PlaceCandidate(
        place_id=2,
        name="Kiyomizu-dera",
        name_ja="清水寺",
        category="temple",
        lat=34.9949,
        lng=135.7850,
        confidence=0.91,
        match_reason="popular nearby result",
        distance_meters=950.0,
        tags=["crowded", "classic", "tourist"],
        photo_potential=0.9,
    )
    evidence = {
        1: [
            EvidenceCard(
                source_type="reddit",
                title="Quiet garden recommendation",
                snippet="Repeatedly praised by travelers looking for calm gardens.",
                url="https://reddit.com/example",
                score=0.88,
                ad_risk=0.05,
                local_signal=0.72,
                tourist_signal=0.28,
            )
        ],
        2: [
            EvidenceCard(
                source_type="blog",
                title="Top Kyoto sights",
                snippet="Very famous, but comments warn about crowding.",
                url="https://blog.example/kyoto",
                score=0.72,
                ad_risk=0.35,
                local_signal=0.24,
                tourist_signal=0.95,
            )
        ],
    }

    ranked = ranker.rank(
        [tourist_hotspot, quiet_temple],
        evidence_by_place_id=evidence,
        interest_tags=["quiet", "garden", "history"],
    )

    assert [item.place.place_id for item in ranked] == [1, 2]
    assert ranked[0].score > ranked[1].score
    assert "interest_match" in ranked[0].reasons
    assert "tourist_overheat_penalty" in ranked[1].penalties
