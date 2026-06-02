from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.db.models import EvidenceItem, Place, PlaceAlias, PlaceEvidence
from app.schemas.visual import EvidenceCard, PlaceCandidate


class SeedPlaceCatalog:
    """Shared P0 place/evidence catalog for API, web companion, and tests."""

    def __init__(self) -> None:
        self._places = [
            PlaceCandidate(
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
            PlaceCandidate(
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
        ]
        self._evidence = {
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

    async def list_places(
        self, city: str | None = None, query: str | None = None
    ) -> list[PlaceCandidate]:
        if city and city.strip().lower() not in {"kyoto", "京都"}:
            return []
        query_text = (query or "").strip().lower()
        return [
            place
            for place in self._places
            if self._matches_query(place, query_text)
        ]

    async def get_place(self, place_id: int) -> PlaceCandidate | None:
        return next((place for place in self._places if place.place_id == place_id), None)

    async def evidence_for(self, place_id: int | None) -> list[EvidenceCard]:
        return self._evidence.get(place_id, [])

    async def search(
        self,
        query: str = "",
        city: str | None = None,
        interest_tags: list[str] | None = None,
    ) -> list[PlaceCandidate]:
        places = await self.list_places(city=city, query=query)
        if places:
            return places
        if interest_tags:
            wanted = {tag.strip().lower() for tag in interest_tags if tag.strip()}
            matched = [
                place
                for place in self._places
                if wanted.intersection({tag.lower() for tag in place.tags})
            ]
            if matched:
                return matched
        return list(self._places)

    @staticmethod
    def _matches_query(place: PlaceCandidate, query: str) -> bool:
        if not query:
            return True
        haystack = " ".join(
            [
                place.name,
                place.name_ja or "",
                place.category,
                " ".join(place.tags),
            ]
        ).lower()
        return query in haystack


class MySqlPlaceCatalog:
    """MySQL-backed POI/evidence catalog with seed fallback for local P0."""

    def __init__(
        self,
        session: Session,
        fallback: SeedPlaceCatalog | None = None,
    ) -> None:
        self.session = session
        self.fallback = fallback or SeedPlaceCatalog()

    async def list_places(
        self,
        city: str | None = None,
        query: str | None = None,
    ) -> list[PlaceCandidate]:
        try:
            statement = select(Place).options(selectinload(Place.aliases)).limit(50)
            filters = []
            if city:
                filters.append(Place.city == city)
            if query:
                like = f"%{query}%"
                filters.append(
                    or_(
                        Place.name.like(like),
                        Place.name_ja.like(like),
                        Place.name_en.like(like),
                        Place.aliases.any(PlaceAlias.alias.like(like)),
                    )
                )
            if filters:
                statement = statement.where(*filters)
            rows = list(self.session.scalars(statement).unique())
            if rows:
                return [self._to_candidate(row) for row in rows]
        except SQLAlchemyError:
            self.session.rollback()
        return await self.fallback.list_places(city=city, query=query)

    async def get_place(self, place_id: int) -> PlaceCandidate | None:
        try:
            row = self.session.get(Place, place_id)
            if row is not None:
                return self._to_candidate(row)
        except SQLAlchemyError:
            self.session.rollback()
        return await self.fallback.get_place(place_id)

    async def evidence_for(self, place_id: int | None) -> list[EvidenceCard]:
        if place_id is None:
            return []
        try:
            statement = (
                select(EvidenceItem)
                .join(PlaceEvidence, PlaceEvidence.evidence_id == EvidenceItem.id)
                .where(PlaceEvidence.place_id == place_id)
                .limit(12)
            )
            rows = list(self.session.scalars(statement))
            if rows:
                return [self._to_evidence(row) for row in rows]
        except SQLAlchemyError:
            self.session.rollback()
        return await self.fallback.evidence_for(place_id)

    async def search(
        self,
        query: str = "",
        city: str | None = None,
        interest_tags: list[str] | None = None,
    ) -> list[PlaceCandidate]:
        places = await self.list_places(city=city, query=query)
        if places:
            return places
        if interest_tags:
            wanted = {tag.strip().lower() for tag in interest_tags if tag.strip()}
            all_places = await self.list_places(city=city)
            matched = [
                place
                for place in all_places
                if wanted.intersection({tag.lower() for tag in place.tags})
            ]
            if matched:
                return matched
        return await self.fallback.search(
            query=query,
            city=city,
            interest_tags=interest_tags,
        )

    @staticmethod
    def _to_candidate(row: Place) -> PlaceCandidate:
        return PlaceCandidate(
            place_id=row.id,
            name=row.name,
            name_ja=row.name_ja,
            category=row.category,
            lat=row.lat,
            lng=row.lng,
            confidence=0.72,
            match_reason="mysql evidence catalog",
            tags=row.tags or [],
            photo_potential=row.photo_potential,
        )

    @staticmethod
    def _to_evidence(row: EvidenceItem) -> EvidenceCard:
        return EvidenceCard(
            source_type=row.source_type,
            title=row.title,
            snippet=row.snippet,
            url=row.url,
            score=row.score,
            ad_risk=row.ad_risk,
            local_signal=row.local_signal,
            tourist_signal=row.tourist_signal,
            metadata=row.metadata_json or {},
        )
