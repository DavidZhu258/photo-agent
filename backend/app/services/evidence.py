from __future__ import annotations

from app.schemas.visual import EvidenceCard, PlaceCandidate, VisualExploreInput


class SeedEvidenceStore:
    """Small deterministic evidence set for local P0 and tests without MySQL."""

    _EVIDENCE = {
        1: [
            EvidenceCard(
                source_type="official",
                title="青蓮院門跡 official history",
                snippet="Known for calm gardens and historic temple buildings in Higashiyama.",
                url="https://www.shorenin.com/",
                score=0.88,
                ad_risk=0.0,
                local_signal=0.72,
                tourist_signal=0.25,
            ),
            EvidenceCard(
                source_type="community",
                title="Quiet Kyoto temple discussion",
                snippet="Travelers mention it as calmer than major Kyoto crowd routes.",
                score=0.8,
                ad_risk=0.05,
                local_signal=0.64,
                tourist_signal=0.32,
            ),
        ],
        2: [
            EvidenceCard(
                source_type="community",
                title="Kiyomizu crowd warning",
                snippet="Worth visiting, but many travelers recommend going very early.",
                score=0.76,
                ad_risk=0.1,
                local_signal=0.34,
                tourist_signal=0.9,
            )
        ],
    }

    async def search(
        self, request: VisualExploreInput, candidates: list[PlaceCandidate]
    ) -> dict[int | None, list[EvidenceCard]]:
        return {
            candidate.place_id: self._EVIDENCE.get(candidate.place_id, [])
            for candidate in candidates
        }

