from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_travel_decision_search"
down_revision = "0002_visual_meaning_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_items", sa.Column("language", sa.String(length=24)))
    op.add_column("evidence_items", sa.Column("source_platform", sa.String(length=120)))
    op.add_column(
        "evidence_items",
        sa.Column("controversy_signal", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "evidence_items",
        sa.Column("freshness_score", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "evidence_items",
        sa.Column("positive_reasons", sa.JSON(), nullable=True),
    )
    op.add_column(
        "evidence_items",
        sa.Column("negative_reasons", sa.JSON(), nullable=True),
    )
    op.add_column(
        "evidence_items",
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("evidence_items", sa.Column("published_at", sa.DateTime(timezone=True)))

    op.create_table(
        "evidence_search_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("query", sa.String(length=1000), nullable=False),
        sa.Column("city", sa.String(length=120)),
        sa.Column("trigger_reason", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False, server_default="exa"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="running"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_evidence_search_runs_city_status",
        "evidence_search_runs",
        ["city", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_search_runs_city_status", table_name="evidence_search_runs")
    op.drop_table("evidence_search_runs")
    op.drop_column("evidence_items", "published_at")
    op.drop_column("evidence_items", "retrieved_at")
    op.drop_column("evidence_items", "negative_reasons")
    op.drop_column("evidence_items", "positive_reasons")
    op.drop_column("evidence_items", "freshness_score")
    op.drop_column("evidence_items", "controversy_signal")
    op.drop_column("evidence_items", "source_platform")
    op.drop_column("evidence_items", "language")
