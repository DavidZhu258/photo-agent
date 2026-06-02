from __future__ import annotations

from typing import Any

from app.schemas.visual import PlaceCandidate, VisualExploreInput


class HeuristicPlaceResolver:
    """Resolves obvious OCR tokens until MySQL/OSM adapters are configured."""

    _KNOWN = {
        "青蓮院": PlaceCandidate(
            place_id=1,
            name="Shoren-in Monzeki",
            name_ja="青蓮院門跡",
            category="temple",
            lat=35.0076,
            lng=135.7825,
            confidence=0.78,
            match_reason="matched built-in Japan seed alias",
            tags=["quiet", "garden", "history"],
            photo_potential=0.86,
        ),
        "青蓮院門跡": PlaceCandidate(
            place_id=1,
            name="Shoren-in Monzeki",
            name_ja="青蓮院門跡",
            category="temple",
            lat=35.0076,
            lng=135.7825,
            confidence=0.78,
            match_reason="matched built-in Japan seed alias",
            tags=["quiet", "garden", "history"],
            photo_potential=0.86,
        ),
        "清水寺": PlaceCandidate(
            place_id=2,
            name="Kiyomizu-dera",
            name_ja="清水寺",
            category="temple",
            lat=34.9949,
            lng=135.7850,
            confidence=0.8,
            match_reason="matched built-in Japan seed alias",
            tags=["classic", "tourist", "crowded"],
            photo_potential=0.9,
        ),
    }

    async def resolve(
        self, request: VisualExploreInput, vlm_result: dict[str, Any]
    ) -> list[PlaceCandidate]:
        text = request.client_ocr.text
        names = list(vlm_result.get("place_candidates") or [])
        names.extend([name for name in self._KNOWN if name in text])
        resolved: list[PlaceCandidate] = []
        for name in dict.fromkeys(names):
            candidate = self._KNOWN.get(name)
            if candidate is not None:
                resolved.append(candidate)
        if resolved:
            return resolved
        hypotheses = vlm_result.get("cultural_hypotheses") or []
        if isinstance(hypotheses, list) and hypotheses:
            first = hypotheses[0] if isinstance(hypotheses[0], dict) else {}
            name = first.get("name") or vlm_result.get("subject") or "Unknown subject"
            return [
                PlaceCandidate(
                    place_id=None,
                    name=str(name),
                    category=str(first.get("entity_type") or "unknown"),
                    confidence=float(
                        first.get("confidence")
                        or vlm_result.get("confidence")
                        or 0.35
                    ),
                    match_reason="visual hypothesis only; needs user confirmation",
                    tags=[],
                    photo_potential=0.3,
                )
            ]
        return [
            PlaceCandidate(
                place_id=None,
                name=vlm_result.get("subject") or "Unknown place",
                category="unknown",
                confidence=float(vlm_result.get("confidence") or 0.35),
                match_reason="VLM subject only; needs user confirmation",
                tags=[],
                photo_potential=0.3,
            )
        ]
