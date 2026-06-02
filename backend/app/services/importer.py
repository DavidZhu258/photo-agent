from __future__ import annotations

from typing import Protocol

from app.schemas.imports import EvidenceImportItem, EvidenceImportSummary


class EvidenceRepository(Protocol):
    async def upsert_place(self, item: EvidenceImportItem) -> int:
        ...

    async def upsert_alias(self, place_id: int, alias: str) -> None:
        ...

    async def create_evidence(self, place_id: int, item: EvidenceImportItem) -> int:
        ...


class EvidenceImporter:
    def __init__(self, repository: EvidenceRepository) -> None:
        self.repository = repository

    async def import_items(
        self, items: list[EvidenceImportItem]
    ) -> EvidenceImportSummary:
        places = 0
        aliases = 0
        evidence = 0
        for item in items:
            place_id = await self.repository.upsert_place(item)
            places += 1
            for alias in self._aliases_for(item):
                await self.repository.upsert_alias(place_id, alias)
                aliases += 1
            await self.repository.create_evidence(place_id, item)
            evidence += 1
        return EvidenceImportSummary(
            places_upserted=places,
            aliases_created=aliases,
            evidence_created=evidence,
        )

    @staticmethod
    def _aliases_for(item: EvidenceImportItem) -> list[str]:
        aliases = []
        if item.place_name_ja:
            aliases.append(item.place_name_ja)
        aliases.append(item.place_name)
        if item.place_name_en:
            aliases.append(item.place_name_en)
        return list(dict.fromkeys(alias for alias in aliases if alias))


class InMemoryEvidenceRepository:
    """Test/dev repository with the same contract as the MySQL adapter."""

    def __init__(self) -> None:
        self.places: list[dict] = []
        self.aliases: list[dict] = []
        self.evidence: list[dict] = []

    async def upsert_place(self, item: EvidenceImportItem) -> int:
        existing = next(
            (
                place
                for place in self.places
                if place["name"] == item.place_name
                and place.get("city") == item.city
            ),
            None,
        )
        if existing:
            return int(existing["id"])
        place_id = len(self.places) + 1
        self.places.append(
            {
                "id": place_id,
                "name": item.place_name,
                "name_ja": item.place_name_ja,
                "name_en": item.place_name_en,
                "city": item.city,
                "category": item.category,
                "lat": item.lat,
                "lng": item.lng,
                "tags": item.tags,
            }
        )
        return place_id

    async def upsert_alias(self, place_id: int, alias: str) -> None:
        if any(
            row["place_id"] == place_id and row["alias"] == alias
            for row in self.aliases
        ):
            return
        self.aliases.append({"place_id": place_id, "alias": alias})

    async def create_evidence(self, place_id: int, item: EvidenceImportItem) -> int:
        evidence_id = len(self.evidence) + 1
        self.evidence.append(
            {
                "id": evidence_id,
                "place_id": place_id,
                "source_type": item.source_type,
                "source_name": item.source_name,
                "title": item.title,
                "snippet": item.snippet,
                "url": item.url,
                "score": item.source_score,
                "ad_risk": item.ad_risk,
                "local_signal": item.local_signal,
                "tourist_signal": item.tourist_signal,
                "tags": item.tags,
            }
        )
        return evidence_id
