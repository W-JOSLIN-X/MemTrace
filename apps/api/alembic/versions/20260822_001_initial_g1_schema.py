"""initial G1 schema

Revision ID: 001_initial_g1_schema
Revises:
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_g1_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('demo_alias', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('demo_alias')
    )

    # 2. demo_sessions
    op.create_table(
        'demo_sessions',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_demo_sessions_owner_id'), 'demo_sessions', ['owner_id'], unique=False)

    # 3. tasks
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('scenario', sa.String(length=64), nullable=False),
        sa.Column('task_text', sa.Text(), nullable=False),
        sa.Column('effective_memory_mode', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('next_event_seq', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scenario IN ('programming_learning', 'software_development', 'general_text', 'other')", name='chk_task_scenario'),
        sa.CheckConstraint("effective_memory_mode IN ('on', 'off')", name='chk_task_memory_mode'),
        sa.CheckConstraint("status IN ('active', 'archived')", name='chk_task_status'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_owner_id'), 'tasks', ['owner_id'], unique=False)

    # 4. task_fingerprints
    op.create_table(
        'task_fingerprints',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('domain', sa.String(length=64), nullable=False),
        sa.Column('task_type', sa.String(length=64), nullable=False),
        sa.Column('artifact_type', sa.String(length=64), nullable=False),
        sa.Column('language', sa.String(length=32), nullable=True),
        sa.Column('fingerprint_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id')
    )
    op.create_index(op.f('ix_task_fingerprints_owner_id'), 'task_fingerprints', ['owner_id'], unique=False)

    # 5. agent_runs
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('provider_mode', sa.String(length=16), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('token_source', sa.String(length=32), nullable=False),
        sa.Column('first_token_ms', sa.Float(), nullable=True),
        sa.Column('total_ms', sa.Float(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider_mode IN ('mock', 'real')", name='chk_run_provider_mode'),
        sa.CheckConstraint("token_source IN ('actual', 'unavailable', 'mock')", name='chk_run_token_source'),
        sa.CheckConstraint("status IN ('queued', 'fingerprinting', 'retrieving', 'planning', 'tool_running', 'generating', 'succeeded', 'failed')", name='chk_run_status'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_runs_owner_id'), 'agent_runs', ['owner_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_task_id'), 'agent_runs', ['task_id'], unique=False)

    # 6. messages
    op.create_table(
        'messages',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name='chk_message_role'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_owner_id'), 'messages', ['owner_id'], unique=False)
    op.create_index(op.f('ix_messages_task_id'), 'messages', ['task_id'], unique=False)
    op.create_index(op.f('ix_messages_run_id'), 'messages', ['run_id'], unique=False)

    # 7. tool_calls
    op.create_table(
        'tool_calls',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=False),
        sa.Column('tool_name', sa.String(length=64), nullable=False),
        sa.Column('reason', sa.String(length=256), nullable=False),
        sa.Column('args_summary_json', sa.Text(), nullable=False),
        sa.Column('result_summary_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('result_ref', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name='chk_tool_status'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tool_calls_owner_id'), 'tool_calls', ['owner_id'], unique=False)
    op.create_index(op.f('ix_tool_calls_task_id'), 'tool_calls', ['task_id'], unique=False)
    op.create_index(op.f('ix_tool_calls_run_id'), 'tool_calls', ['run_id'], unique=False)

    # 8. feedback_events
    op.create_table(
        'feedback_events',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=False),
        sa.Column('feedback_type', sa.String(length=32), nullable=False),
        sa.Column('explicit_text', sa.Text(), nullable=True),
        sa.Column('edited_output', sa.Text(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('accepted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("feedback_type IN ('explicit_text', 'edited_output', 'rating', 'accepted', 'rejected', 'composite')", name='chk_feedback_type'),
        sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name='chk_feedback_rating'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_events_owner_id'), 'feedback_events', ['owner_id'], unique=False)
    op.create_index(op.f('ix_feedback_events_task_id'), 'feedback_events', ['task_id'], unique=False)
    op.create_index(op.f('ix_feedback_events_run_id'), 'feedback_events', ['run_id'], unique=False)

    # 9. memory_jobs
    op.create_table(
        'memory_jobs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('job_type', sa.String(length=64), nullable=False),
        sa.Column('feedback_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('last_error_code', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("job_type IN ('extract_feedback')", name='chk_job_type'),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name='chk_job_status'),
        sa.CheckConstraint("stage IN ('queued', 'extracting', 'done', 'failed')", name='chk_job_stage'),
        sa.ForeignKeyConstraint(['feedback_id'], ['feedback_events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('feedback_id')
    )
    op.create_index(op.f('ix_memory_jobs_owner_id'), 'memory_jobs', ['owner_id'], unique=False)

    # 10. event_log
    op.create_table(
        'event_log',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('stream_type', sa.String(length=32), nullable=False),
        sa.Column('stream_id', sa.String(length=32), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'stream_type', 'stream_id', 'seq', name='uq_event_log_stream_seq')
    )
    op.create_index('ix_event_log_stream', 'event_log', ['stream_type', 'stream_id', 'seq'], unique=False)
    op.create_index(op.f('ix_event_log_owner_id'), 'event_log', ['owner_id'], unique=False)

    # 11. idempotency_keys
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('route', sa.String(length=256), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_json', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'route', 'key', name='uq_idempotency_owner_route_key')
    )
    op.create_index('ix_idempotency_lookup', 'idempotency_keys', ['owner_id', 'route', 'key'], unique=False)
    op.create_index(op.f('ix_idempotency_keys_owner_id'), 'idempotency_keys', ['owner_id'], unique=False)


def downgrade() -> None:
    op.drop_table('idempotency_keys')
    op.drop_table('event_log')
    op.drop_table('memory_jobs')
    op.drop_table('feedback_events')
    op.drop_table('tool_calls')
    op.drop_table('messages')
    op.drop_table('agent_runs')
    op.drop_table('task_fingerprints')
    op.drop_table('tasks')
    op.drop_table('demo_sessions')
    op.drop_table('users')
