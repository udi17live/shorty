"""Initial schema for runs, stages, clips, posts, and settings.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("runs"):
        op.create_table(
            "runs",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("current_stage", sa.String(64), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("options", sa.Text(), nullable=False),
            sa.Column("claimed_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not inspector.has_table("stages"):
        op.create_table(
            "stages",
            sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("name", sa.String(64), primary_key=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not inspector.has_table("clips"):
        op.create_table(
            "clips",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("start_seconds", sa.Float(), nullable=False),
            sa.Column("end_seconds", sa.Float(), nullable=False),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("post_title", sa.Text(), nullable=False),
            sa.Column("caption", sa.Text(), nullable=False),
            sa.Column("hashtags", sa.Text(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=False),
            sa.Column("file_path", sa.Text(), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_clips_run_id", "clips", ["run_id"])

    if not inspector.has_table("posts"):
        op.create_table(
            "posts",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("clip_id", sa.String(32), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel_id", sa.String(255), nullable=False),
            sa.Column("channel_name", sa.Text(), nullable=True),
            sa.Column("service", sa.String(64), nullable=True),
            sa.Column("mode", sa.String(32), nullable=False),
            sa.Column("scheduled_at", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("buffer_post_id", sa.String(255), nullable=True),
            sa.Column("media_url", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_posts_clip_id", "posts", ["clip_id"])

    if not inspector.has_table("settings"):
        op.create_table(
            "settings",
            sa.Column("key", sa.String(128), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("posts")
    op.drop_table("clips")
    op.drop_table("stages")
    op.drop_table("runs")

