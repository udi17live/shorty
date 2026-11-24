"""Add projects, run-to-project relation, connected channels, and OAuth credential tables.

Revision ID: 0002_projects_channels
Revises: 0001_initial
Create Date: 2026-11-25 00:10:00
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0002_projects_channels"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("projects"):
        op.create_table(
            "projects",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("slug", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("owner_id", sa.String(64), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)
        op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    # Seed default project so existing runs can always belong to a Project.
    now_dt = datetime.now(UTC).replace(microsecond=0)
    now_val = now_dt.isoformat(timespec="seconds") if bind.dialect.name == "sqlite" else now_dt
    existing_default = bind.execute(sa.text("SELECT id FROM projects WHERE id = 'default'")).fetchone()
    if existing_default is None:
        bind.execute(
            sa.text(
                "INSERT INTO projects (id, name, slug, description, owner_id, is_default, created_at, updated_at) "
                "VALUES (:id, :name, :slug, :description, :owner_id, :is_default, :created_at, :updated_at)"
            ),
            {
                "id": "default",
                "name": "Default Project",
                "slug": "default",
                "description": "Default project for clips and connected channels",
                "owner_id": None,
                "is_default": True,
                "created_at": now_val,
                "updated_at": now_val,
            },
        )

    run_columns = {c["name"] for c in inspector.get_columns("runs")}
    if "project_id" not in run_columns:
        with op.batch_alter_table("runs") as batch_op:
            batch_op.add_column(sa.Column("project_id", sa.String(32), nullable=True))

        bind.execute(sa.text("UPDATE runs SET project_id = 'default' WHERE project_id IS NULL"))

        with op.batch_alter_table("runs") as batch_op:
            batch_op.alter_column("project_id", existing_type=sa.String(32), nullable=False)
            batch_op.create_foreign_key(
                "fk_runs_project_id", "projects", ["project_id"], ["id"], ondelete="CASCADE"
            )
            batch_op.create_index("ix_runs_project_id", ["project_id"])

    run_indexes = {idx["name"] for idx in inspector.get_indexes("runs")}
    if "ix_runs_status" not in run_indexes:
        op.create_index("ix_runs_status", "runs", ["status"])
    if "ix_runs_created_at" not in run_indexes:
        op.create_index("ix_runs_created_at", "runs", ["created_at"])

    if not inspector.has_table("connected_channels"):
        op.create_table(
            "connected_channels",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("external_account_id", sa.String(255), nullable=True),
            sa.Column("external_channel_id", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("handle", sa.String(255), nullable=True),
            sa.Column("avatar_url", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="connected"),
            sa.Column("status_message", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("owner_id", sa.String(64), nullable=True),
            sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "project_id",
                "platform",
                "external_channel_id",
                name="uq_connected_channels_project_platform_channel",
            ),
        )
        op.create_index("ix_connected_channels_project_platform", "connected_channels", ["project_id", "platform"])
        op.create_index("ix_connected_channels_owner_id", "connected_channels", ["owner_id"])

    if not inspector.has_table("oauth_credentials"):
        op.create_table(
            "oauth_credentials",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "connected_channel_id",
                sa.String(32),
                sa.ForeignKey("connected_channels.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("owner_id", sa.String(64), nullable=True),
            sa.Column("encrypted_access_token", sa.Text(), nullable=True),
            sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
            sa.Column("token_type", sa.String(32), nullable=False, server_default="Bearer"),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_oauth_credentials_platform", "oauth_credentials", ["platform"])
        op.create_index("ix_oauth_credentials_owner_id", "oauth_credentials", ["owner_id"])

    if not inspector.has_table("oauth_states"):
        op.create_table(
            "oauth_states",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("state_hash", sa.String(64), nullable=False),
            sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("owner_id", sa.String(64), nullable=True),
            sa.Column("binding_hash", sa.String(64), nullable=False),
            sa.Column("encrypted_pkce_verifier", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_oauth_states_state_hash", "oauth_states", ["state_hash"], unique=True)
        op.create_index("ix_oauth_states_project_id", "oauth_states", ["project_id"])
        op.create_index("ix_oauth_states_expires_at", "oauth_states", ["expires_at"])

    if not inspector.has_table("oauth_pending_selections"):
        op.create_table(
            "oauth_pending_selections",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("owner_id", sa.String(64), nullable=True),
            sa.Column("binding_hash", sa.String(64), nullable=False),
            sa.Column("encrypted_tokens", sa.Text(), nullable=False),
            sa.Column("channels_json", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_oauth_pending_selections_project_id", "oauth_pending_selections", ["project_id"])
        op.create_index("ix_oauth_pending_selections_expires_at", "oauth_pending_selections", ["expires_at"])


def downgrade() -> None:
    op.drop_table("oauth_pending_selections")
    op.drop_table("oauth_states")
    op.drop_table("oauth_credentials")
    op.drop_table("connected_channels")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_project_id")
        batch_op.drop_constraint("fk_runs_project_id", type_="foreignkey")
        batch_op.drop_column("project_id")
    op.drop_table("projects")
