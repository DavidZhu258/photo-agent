from __future__ import annotations

from app.schemas.visual import EvidenceCard, PlaceCandidate, RankedPlace


class RecommendationRanker:
    """Deterministic place ranking tuned for transparent, non-sponsored results."""

    def rank(
        self,
        candidates: list[PlaceCandidate],
        *,
        evidence_by_place_id: dict[int | None, list[EvidenceCard]],
        interest_tags: list[str],
    ) -> list[RankedPlace]:
        ranked = [
            self._score_candidate(candidate, evidence_by_place_id, interest_tags)
            for candidate in candidates
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    def _score_candidate(
        self,
        candidate: PlaceCandidate,
        evidence_by_place_id: dict[int | None, list[EvidenceCard]],
        interest_tags: list[str],
    ) -> RankedPlace:
        evidence = evidence_by_place_id.get(candidate.place_id, [])
        avg_evidence = _average([card.score for card in evidence])
        avg_local = _average([card.local_signal for card in evidence])
        avg_tourist = _average([card.tourist_signal for card in evidence])
        avg_ad_risk = _average([card.ad_risk for card in evidence])
        interest_score = self._interest_score(candidate.tags, interest_tags)
        distance_penalty = min((candidate.distance_meters or 0) / 5000, 1.0) * 0.05

        score = (
            candidate.confidence * 0.25
            + avg_evidence * 0.25
            + avg_local * 0.15
            + candidate.photo_potential * 0.15
            + interest_score * 0.25
            - avg_ad_risk * 0.15
            - distance_penalty
        )

        reasons: list[str] = []
        penalties: list[str] = []
        if interest_score > 0:
            reasons.append("interest_match")
        if avg_evidence >= 0.75:
            reasons.append("strong_evidence")
        if avg_local >= 0.6:
            reasons.append("local_signal")
        if candidate.photo_potential >= 0.75:
            reasons.append("photo_potential")
        if avg_tourist >= 0.75:
            score -= (avg_tourist - 0.75) * 0.25
            penalties.append("tourist_overheat_penalty")
        if avg_ad_risk >= 0.3:
            penalties.append("ad_risk_penalty")
        if distance_penalty > 0.03:
            penalties.append("distance_penalty")

        return RankedPlace(
            place=candidate,
            score=round(max(score, 0.0), 4),
            reasons=reasons,
            penalties=penalties,
        )

    @staticmethod
    def _interest_score(candidate_tags: list[str], interest_tags: list[str]) -> float:
        if not candidate_tags or not interest_tags:
            return 0.0
        candidate_set = {tag.lower() for tag in candidate_tags}
        interests = {tag.lower() for tag in interest_tags}
        return len(candidate_set & interests) / len(interests)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)

