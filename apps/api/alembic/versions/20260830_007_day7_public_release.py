"""Day 7 public accounts, quotas, and release metadata.

Revision ID: 007_day7_public_release
Revises: 006_conversation_first_memory
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_day7_public_release"
down_revision: str | None = "006_conversation_first_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("demo_sessions") as batch_op:
        batch_op.add_column(sa.Column("csrf_token_hash", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column("auth_kind", sa.String(16), nullable=False, server_default="demo")
        )
        batch_op.add_column(sa.Column("revoked_reason", sa.String(32), nullable=True))
        batch_op.create_check_constraint("chk_session_auth_kind", "auth_kind IN ('demo', 'public')")
        batch_op.create_check_constraint(
            "chk_session_revoked_reason",
            "revoked_reason IS NULL OR revoked_reason IN "
            "('logout', 'logout_all', 'password_changed', 'recovered', 'account_deleted')",
        )
        batch_op.create_check_constraint(
            "chk_session_public_csrf",
            "(auth_kind = 'demo' AND csrf_token_hash IS NULL) OR "
            "(auth_kind = 'public' AND csrf_token_hash IS NOT NULL)",
        )

    op.create_table(
        "local_accounts",
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("username_normalized", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("default_memory_mode", sa.String(16), nullable=False, server_default="on"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="chk_local_account_status"),
        sa.CheckConstraint(
            "default_memory_mode IN ('on', 'off')", name="chk_local_account_memory_mode"
        ),
        sa.UniqueConstraint("username_normalized", name="uq_local_accounts_username"),
    )
    op.create_index(
        "ix_local_accounts_username", "local_accounts", ["username_normalized"], unique=True
    )

    op.create_table(
        "registration_invites",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("max_uses >= 1", name="chk_registration_invite_max_uses"),
        sa.CheckConstraint(
            "use_count >= 0 AND use_count <= max_uses",
            name="chk_registration_invite_use_count",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'exhausted', 'revoked', 'expired')",
            name="chk_registration_invite_status",
        ),
        sa.UniqueConstraint("code_hash", name="uq_registration_invites_code_hash"),
    )
    op.create_index(
        "ix_registration_invites_expiry",
        "registration_invites",
        ["status", "expires_at"],
    )

    op.create_table(
        "account_recovery_credentials",
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column(
            "rotated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("code_hash", name="uq_account_recovery_code_hash"),
    )

    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "action IN ('login', 'register', 'recover')", name="chk_auth_rate_action"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="chk_auth_rate_attempt_count"),
        sa.UniqueConstraint("action", "identity_hash", name="uq_auth_rate_action_identity"),
    )
    op.create_index("ix_auth_rate_blocked", "auth_rate_limit_buckets", ["blocked_until"])

    op.create_table(
        "daily_turn_quotas",
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("utc_date", sa.String(10), primary_key=True),
        sa.Column("used_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("used_turns >= 0", name="chk_daily_quota_used"),
        sa.CheckConstraint("active_turns >= 0", name="chk_daily_quota_active"),
    )
    op.create_index("ix_daily_turn_quota_date", "daily_turn_quotas", ["utc_date"])

    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.add_column(sa.Column("provider_mode", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("provider_model", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("prompt_hash", sa.String(71), nullable=True))
        batch_op.add_column(sa.Column("prompt_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("output_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("total_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("token_source", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("provider_latency_ms", sa.Float(), nullable=True))
        batch_op.create_check_constraint(
            "chk_tool_provider_mode",
            "provider_mode IS NULL OR provider_mode IN ('mock', 'real')",
        )
        batch_op.create_check_constraint(
            "chk_tool_token_source",
            "token_source IS NULL OR token_source IN ('actual', 'mock')",
        )
        batch_op.create_check_constraint(
            "chk_tool_usage",
            "(prompt_tokens IS NULL OR prompt_tokens >= 0) AND "
            "(output_tokens IS NULL OR output_tokens >= 0) AND "
            "(total_tokens IS NULL OR total_tokens >= 0)",
        )

    with op.batch_alter_table("memory_llm_judgments") as batch_op:
        batch_op.drop_constraint("chk_llm_judge_type", type_="check")
        batch_op.create_check_constraint(
            "chk_llm_judge_type",
            "judge_type IN "
            "('summary', 'applicability', 'tool_planning', 'effect', 'consolidation')",
        )

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', "
            "'merge', 'scope_resolution', 'llm_extract', 'llm_update', "
            "'llm_supersede', 'llm_coexist', 'user_edit', 'user_restore')",
        )

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', "
            "'merge', 'scope_resolution', 'llm_extract', 'llm_update', "
            "'llm_supersede', 'llm_coexist', 'user_edit')",
        )

    with op.batch_alter_table("memory_llm_judgments") as batch_op:
        batch_op.drop_constraint("chk_llm_judge_type", type_="check")
        batch_op.create_check_constraint(
            "chk_llm_judge_type",
            "judge_type IN ('summary', 'applicability', 'effect', 'consolidation')",
        )

    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.drop_constraint("chk_tool_usage", type_="check")
        batch_op.drop_constraint("chk_tool_token_source", type_="check")
        batch_op.drop_constraint("chk_tool_provider_mode", type_="check")
        batch_op.drop_column("provider_latency_ms")
        batch_op.drop_column("token_source")
        batch_op.drop_column("total_tokens")
        batch_op.drop_column("output_tokens")
        batch_op.drop_column("prompt_tokens")
        batch_op.drop_column("prompt_hash")
        batch_op.drop_column("provider_model")
        batch_op.drop_column("provider_mode")

    op.drop_index("ix_daily_turn_quota_date", table_name="daily_turn_quotas")
    op.drop_table("daily_turn_quotas")
    op.drop_index("ix_auth_rate_blocked", table_name="auth_rate_limit_buckets")
    op.drop_table("auth_rate_limit_buckets")
    op.drop_table("account_recovery_credentials")
    op.drop_index("ix_registration_invites_expiry", table_name="registration_invites")
    op.drop_table("registration_invites")
    op.drop_index("ix_local_accounts_username", table_name="local_accounts")
    op.drop_table("local_accounts")

    with op.batch_alter_table("demo_sessions") as batch_op:
        batch_op.drop_constraint("chk_session_public_csrf", type_="check")
        batch_op.drop_constraint("chk_session_revoked_reason", type_="check")
        batch_op.drop_constraint("chk_session_auth_kind", type_="check")
        batch_op.drop_column("revoked_reason")
        batch_op.drop_column("auth_kind")
        batch_op.drop_column("csrf_token_hash")

    op.execute("PRAGMA foreign_keys=ON")
