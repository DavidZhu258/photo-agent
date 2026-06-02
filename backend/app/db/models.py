from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ja: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")
    city: Mapped[str | None] = mapped_column(String(120))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    photo_potential: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    aliases: Mapped[list["PlaceAlias"]] = relationship(
        back_populates="place", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list["PlaceEvidence"]] = relationship(
        back_populates="place", cascade="all, delete-orphan"
    )


class PlaceAlias(Base):
    __tablename__ = "place_aliases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str | None] = mapped_column(String(24))

    place: Mapped[Place] = relationship(back_populates="aliases")

    __table_args__ = (
        Index("ix_place_aliases_place_alias", "place_id", "alias", unique=True),
    )


class SourceReputation(Base):
    __tablename__ = "source_reputation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    ad_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_user_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str | None] = mapped_column(String(24))
    source_platform: Mapped[str | None] = mapped_column(String(120))
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    ad_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    local_signal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tourist_signal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    controversy_signal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    positive_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    negative_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    place_links: Mapped[list["PlaceEvidence"]] = relationship(
        back_populates="evidence", cascade="all, delete-orphan"
    )


class PlaceEvidence(Base):
    __tablename__ = "place_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id"), nullable=False)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False
    )

    place: Mapped[Place] = relationship(back_populates="evidence_links")
    evidence: Mapped[EvidenceItem] = relationship(back_populates="place_links")

    __table_args__ = (
        Index("ix_place_evidence_unique", "place_id", "evidence_id", unique=True),
    )


class SnapSession(Base):
    __tablename__ = "snap_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    image_sha256: Mapped[str | None] = mapped_column(String(128))
    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lng: Mapped[float | None] = mapped_column(Float)
    heading_degrees: Mapped[float | None] = mapped_column(Float)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    user_context_text: Mapped[str | None] = mapped_column(Text)
    exploration_focus: Mapped[str] = mapped_column(
        String(40), nullable=False, default="auto"
    )
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    results: Mapped[list["SnapResult"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SnapResult(Base):
    __tablename__ = "snap_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("snap_sessions.id"))
    cache_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    visual_reasoning_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=dict
    )
    narrative_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=dict
    )
    resolved_entity_type: Mapped[str | None] = mapped_column(String(80))
    map_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="discovered"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[SnapSession] = relationship(back_populates="results")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    profile_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    avoid_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EvidenceSearchRun(Base):
    __tablename__ = "evidence_search_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(1000), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    trigger_reason: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="exa")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
