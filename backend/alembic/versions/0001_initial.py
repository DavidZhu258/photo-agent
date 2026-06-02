from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_ja", sa.String(length=255), nullable=True),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("photo_potential", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "place_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("place_id", sa.Integer(), sa.ForeignKey("places.id"), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=24), nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_place_aliases_place_alias",
        "place_aliases",
        ["place_id", "alias"],
        unique=True,
    )
    op.create_table(
        "source_reputation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("ad_risk", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_user_review", sa.Boolean(), nullable=False, server_default="0"),
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("ad_risk", sa.Float(), nullable=False, server_default="0"),
        sa.Column("local_signal", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tourist_signal", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "place_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("place_id", sa.Integer(), sa.ForeignKey("places.id"), nullable=False),
        sa.Column(
            "evidence_id",
            sa.Integer(),
            sa.ForeignKey("evidence_items.id"),
            nullable=False,
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_place_evidence_unique",
        "place_evidence",
        ["place_id", "evidence_id"],
        unique=True,
    )
    op.create_table(
        "snap_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("image_sha256", sa.String(length=128), nullable=True),
        sa.Column("gps_lat", sa.Float(), nullable=True),
        sa.Column("gps_lng", sa.Float(), nullable=True),
        sa.Column("heading_degrees", sa.Float(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("interest_tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "snap_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("snap_sessions.id")),
        sa.Column("cache_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("profile_name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("interest_tags", sa.JSON(), nullable=False),
        sa.Column("avoid_tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    op.execute(
        "CREATE FULLTEXT INDEX ft_place_aliases_alias "
        "ON place_aliases (alias) WITH PARSER ngram"
    )
    op.execute(
        "CREATE FULLTEXT INDEX ft_evidence_items_text "
        "ON evidence_items (title, snippet) WITH PARSER ngram"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ft_evidence_items_text ON evidence_items")
    op.execute("DROP INDEX ft_place_aliases_alias ON place_aliases")
    op.drop_table("user_preferences")
    op.drop_table("snap_results")
    op.drop_table("snap_sessions")
    op.drop_index("ix_place_evidence_unique", table_name="place_evidence")
    op.drop_table("place_evidence")
    op.drop_table("evidence_items")
    op.drop_table("source_reputation")
    op.drop_index("ix_place_aliases_place_alias", table_name="place_aliases")
    op.drop_table("place_aliases")
    op.drop_table("places")

