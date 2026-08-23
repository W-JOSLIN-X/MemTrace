"""Day 3 migration tests: fresh upgrade, G1-data upgrade, downgrade, constraints, readiness."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.database import create_session_factory
from memtrace_api.db_models import (
    MemoryCardModel,
    UserModel,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.readiness import DatabaseRevisionError, ensure_database_current
from memtrace_api.schemas import utc_now

ALEMBIC_INI = str(PROJECT_ROOT / "apps" / "api" / "alembic.ini")


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ, MEMTRACE_DATABASE_URL=db_url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", ALEMBIC_INI, *args],
        env=env,
        check=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
    )


def _new_db(name: str) -> tuple[Path, str]:
    directory = tempfile.mkdtemp(prefix="memtrace-mig-")
    db_file = Path(directory) / name
    return db_file, f"sqlite:///{db_file.as_posix()}"


def _seed_task(session: Session, owner_id: str) -> str:
    task_id = new_prefixed_ulid("task")
    session.execute(
        text(
            "INSERT INTO tasks (id, owner_id, scenario, task_text, "
            "effective_memory_mode, status, next_event_seq, created_at, updated_at) "
            "VALUES (:id, :owner, 'programming_learning', '学 Python', 'on', "
            "'active', 1, :now, :now)"
        ),
        {"id": task_id, "owner": owner_id, "now": utc_now()},
    )
    return task_id


def _seed_run(session: Session, owner_id: str, task_id: str) -> str:
    run_id = new_prefixed_ulid("run")
    session.execute(
        text(
            "INSERT INTO agent_runs (id, owner_id, task_id, provider_mode, model, "
            "status, stage, token_source, created_at) VALUES "
            "(:id, :owner, :task, 'mock', 'fixture-g1', 'succeeded', 'done', "
            "'mock', :now)"
        ),
        {"id": run_id, "owner": owner_id, "task": task_id, "now": utc_now()},
    )
    return run_id


def test_fresh_empty_database_upgrades_to_head() -> None:
    _, db_url = _new_db("fresh.sqlite3")
    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert {
        "memory_cards",
        "memory_versions",
        "memory_evidence",
        "memory_evidence_links",
        "memory_relations",
    } <= tables
    with Session(engine) as session:
        assert ensure_database_current(session) == "003_g2_job_retryable"
    engine.dispose()


def test_g1_database_upgrades_with_data_preserved(tmp_path: Path) -> None:
    _, db_url = _new_db("g1data.sqlite3")
    _run_alembic(db_url, "upgrade", "001_initial_g1_schema")

    owner_id = new_prefixed_ulid("usr")
    task_id = new_prefixed_ulid("task")
    run_id = new_prefixed_ulid("run")
    feedback_id = new_prefixed_ulid("feedback")
    job_id = new_prefixed_ulid("job")
    engine = create_engine(db_url)
    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO users (id, demo_alias, created_at, updated_at) "
                "VALUES (:id, 'blank_demo', :now, :now)"
            ),
            {"id": owner_id, "now": utc_now()},
        )
        session.execute(
            text(
                "INSERT INTO tasks (id, owner_id, scenario, task_text, "
                "effective_memory_mode, status, next_event_seq, created_at, updated_at) "
                "VALUES (:id, :owner, 'programming_learning', '学 Python', 'on', "
                "'active', 1, :now, :now)"
            ),
            {"id": task_id, "owner": owner_id, "now": utc_now()},
        )
        session.execute(
            text(
                "INSERT INTO agent_runs (id, owner_id, task_id, provider_mode, model, "
                "status, stage, token_source, created_at) VALUES "
                "(:id, :owner, :task, 'mock', 'fixture-g1', 'succeeded', 'done', "
                "'mock', :now)"
            ),
            {"id": run_id, "owner": owner_id, "task": task_id, "now": utc_now()},
        )
        session.execute(
            text(
                "INSERT INTO feedback_events (id, owner_id, task_id, run_id, "
                "feedback_type, explicit_text, created_at) VALUES "
                "(:id, :owner, :task, :run, 'explicit_text', "
                "'以后先提示再修复', :now)"
            ),
            {
                "id": feedback_id,
                "owner": owner_id,
                "task": task_id,
                "run": run_id,
                "now": utc_now(),
            },
        )
        session.execute(
            text(
                "INSERT INTO memory_jobs (id, owner_id, job_type, feedback_id, status, "
                "stage, attempt, created_at, updated_at) VALUES "
                "(:id, :owner, 'extract_feedback', :fb, 'pending', 'queued', 0, "
                ":now, :now)"
            ),
            {"id": job_id, "owner": owner_id, "fb": feedback_id, "now": utc_now()},
        )
        session.commit()
    engine.dispose()

    _run_alembic(db_url, "upgrade", "head")

    engine = create_engine(db_url)
    with engine.connect() as conn:
        job = conn.execute(
            text(
                "SELECT status, stage, attempt, disposition, retryable "
                "FROM memory_jobs WHERE id=:id"
            ),
            {"id": job_id},
        ).one()
        assert job.status == "pending"
        assert job.stage == "queued"
        assert job.attempt == 0
        assert job.disposition is None
        assert job.retryable == 0
        fb_count = conn.execute(text("SELECT COUNT(*) FROM feedback_events")).scalar_one()
        assert fb_count == 1
        # The G2 stage values must now be accepted by the rebuilt check constraint.
        conn.execute(text("UPDATE memory_jobs SET stage='diffing' WHERE id=:id"), {"id": job_id})
        conn.commit()
        stage = conn.execute(
            text("SELECT stage FROM memory_jobs WHERE id=:id"), {"id": job_id}
        ).scalar_one()
        assert stage == "diffing"
    engine.dispose()


def test_downgrade_upon_dedicated_temp_database() -> None:
    _, db_url = _new_db("cycle.sqlite3")
    _run_alembic(db_url, "upgrade", "head")

    # Seed a job row so the post-downgrade CHECK can actually be exercised:
    # an UPDATE that matches zero rows never violates a CHECK constraint.
    owner_id = new_prefixed_ulid("usr")
    feedback_id = new_prefixed_ulid("feedback")
    job_id = new_prefixed_ulid("job")
    engine = create_engine(db_url)
    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO users (id, demo_alias, created_at, updated_at) "
                "VALUES (:id, 'blank_demo', :now, :now)"
            ),
            {"id": owner_id, "now": utc_now()},
        )
        task_id = _seed_task(session, owner_id)
        run_id = _seed_run(session, owner_id, task_id)
        session.execute(
            text(
                "INSERT INTO feedback_events (id, owner_id, task_id, run_id, "
                "feedback_type, explicit_text, created_at) VALUES "
                "(:id, :owner, :task, :run, 'explicit_text', '以后先提示', :now)"
            ),
            {
                "id": feedback_id,
                "owner": owner_id,
                "task": task_id,
                "run": run_id,
                "now": utc_now(),
            },
        )
        session.execute(
            text(
                "INSERT INTO memory_jobs (id, owner_id, job_type, feedback_id, status, "
                "stage, attempt, created_at, updated_at) VALUES "
                "(:id, :owner, 'extract_feedback', :fb, 'pending', 'queued', 0, :now, :now)"
            ),
            {"id": job_id, "owner": owner_id, "fb": feedback_id, "now": utc_now()},
        )
        session.commit()
    engine.dispose()

    _run_alembic(db_url, "downgrade", "001_initial_g1_schema")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(memory_jobs)"))}
        job_count = conn.execute(text("SELECT COUNT(*) FROM memory_jobs")).scalar_one()
    assert job_count == 1
    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.execute(text("UPDATE memory_jobs SET stage='diffing'"))
            session.commit()
    engine.dispose()
    assert not {"memory_cards", "memory_versions", "memory_evidence"} & tables
    assert "disposition" not in cols
    assert "retryable" not in cols

    _run_alembic(db_url, "upgrade", "head")


def test_readiness_rejects_stale_revision() -> None:
    _, db_url = _new_db("stale.sqlite3")
    _run_alembic(db_url, "upgrade", "001_initial_g1_schema")
    engine = create_engine(db_url)
    with Session(engine) as session:
        with pytest.raises(DatabaseRevisionError):
            ensure_database_current(session)
    engine.dispose()


def test_day2_revision_upgrades_to_retryable_head() -> None:
    _, db_url = _new_db("day2-head.sqlite3")
    _run_alembic(db_url, "upgrade", "002_g2_memory_admission")
    engine = create_engine(db_url)
    with Session(engine) as session:
        with pytest.raises(DatabaseRevisionError):
            ensure_database_current(session)
    engine.dispose()

    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    with Session(engine) as session:
        assert ensure_database_current(session) == "003_g2_job_retryable"
    engine.dispose()


def test_candidate_invariant_check_constraints_reject_bad_rows() -> None:
    _, db_url = _new_db("checks.sqlite3")
    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    factory = create_session_factory(engine)

    owner_id = new_prefixed_ulid("usr")
    with factory() as session:
        session.add(
            UserModel(
                id=owner_id,
                demo_alias=f"chk_{owner_id[-6:]}",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        session.commit()

    def _card(**overrides: object) -> MemoryCardModel:
        values: dict[str, object] = {
            "id": new_prefixed_ulid("mem"),
            "owner_id": owner_id,
            "status": "candidate",
            "kind": "preference",
            "source_type": "explicit_feedback",
            "save_preselected": False,
            "title": "偏好标题",
            "rule": "这是一条至少二十个字符的偏好规则正文。",
            "avoid": "",
            "trigger_text": "",
            "scope_level": "task_family",
            "domain": "programming_learning",
            "scope_json": "{}",
            "exceptions_json": "[]",
            "source_trust": 1.0,
            "evidence_count": 0,
            "version": 0,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        values.update(overrides)
        return MemoryCardModel(**values)  # type: ignore[arg-type]

    with factory() as session:
        session.add(_card())
        session.commit()

    with factory() as session:
        session.add(_card(version=1))
        with pytest.raises(IntegrityError):
            session.commit()
    with factory() as session:
        session.add(_card(rule_confidence=0.9))
        with pytest.raises(IntegrityError):
            session.commit()
    with factory() as session:
        session.add(_card(status="active"))
        with pytest.raises(IntegrityError):
            session.commit()
    with factory() as session:
        session.add(_card(kind="not_a_kind"))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_owner_scoped_indexes_exist() -> None:
    _, db_url = _new_db("idx.sqlite3")
    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        indexes = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memory_cards'")
        ).fetchall()
    engine.dispose()
    names = {row[0] for row in indexes}
    assert "ix_memory_cards_owner_status" in names
    assert "ix_memory_cards_owner_status_scope" in names
