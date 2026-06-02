from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_visual_meaning_memory"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snap_sessions",
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("snap_sessions", sa.Column("user_context_text", sa.Text()))
    op.add_column(
        "snap_sessions",
        sa.Column(
            "exploration_focus",
            sa.String(length=40),
            nullable=False,
            server_default="auto",
        ),
    )
    op.add_column(
        "snap_results",
        sa.Column("visual_reasoning_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "snap_results",
        sa.Column("narrative_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "snap_results",
        sa.Column("resolved_entity_type", sa.String(length=80)),
    )
    op.add_column(
        "snap_results",
        sa.Column(
            "map_status",
            sa.String(length=40),
            nullable=False,
            server_default="discovered",
        ),
    )


def downgrade() -> None:
    op.drop_column("snap_results", "map_status")
    op.drop_column("snap_results", "resolved_entity_type")
    op.drop_column("snap_results", "narrative_json")
    op.drop_column("snap_results", "visual_reasoning_json")
    op.drop_column("snap_sessions", "exploration_focus")
    op.drop_column("snap_sessions", "user_context_text")
    op.drop_column("snap_sessions", "image_count")
