from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvidenceItem, Place, PlaceAlias, PlaceEvidence
from app.schemas.imports import EvidenceImportItem


class MySqlEvidenceRepository:
    """SQLAlchemy adapter for the import service."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def upsert_place(self, item: EvidenceImportItem) -> int:
        existing = self.session.scalar(
            select(Place).where(Place.name == item.place_name, Place.city == item.city)
        )
        if existing is not None:
            return existing.id
        place = Place(
            name=item.place_name,
            name_ja=item.place_name_ja,
            name_en=item.place_name_en,
            city=item.city,
            category=item.category,
            lat=item.lat,
            lng=item.lng,
            tags=item.tags,
        )
        self.session.add(place)
        self.session.flush()
        return place.id

    async def upsert_alias(self, place_id: int, alias: str) -> None:
        existing = self.session.scalar(
            select(PlaceAlias).where(
                PlaceAlias.place_id == place_id,
                PlaceAlias.alias == alias,
            )
        )
        if existing is None:
            self.session.add(PlaceAlias(place_id=place_id, alias=alias))

    async def create_evidence(self, place_id: int, item: EvidenceImportItem) -> int:
        evidence = EvidenceItem(
            source_type=item.source_type,
            source_name=item.source_name,
            title=item.title,
            snippet=item.snippet,
            url=item.url,
            score=item.source_score,
            ad_risk=item.ad_risk,
            local_signal=item.local_signal,
            tourist_signal=item.tourist_signal,
            metadata_json={"tags": item.tags},
        )
        self.session.add(evidence)
        self.session.flush()
        self.session.add(PlaceEvidence(place_id=place_id, evidence_id=evidence.id))
        self.session.commit()
        return evidence.id

