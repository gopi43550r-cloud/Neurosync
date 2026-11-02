"""Database engine, session management and base declarative class."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

if settings.database_url.startswith("sqlite"):
    # SQLite does not enforce foreign keys (and therefore ON DELETE CASCADE) by
    # default. Without this, deleting an investigation or document leaves orphan
    # rows in association tables, which later break re-loading the demo.
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets readers proceed while the background investigation thread
        # writes; busy_timeout makes concurrent writers wait instead of failing
        # immediately with "database is locked".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_additive_migrations() -> None:
    """Add new nullable columns to pre-existing tables (SQLite dev schema).

    ``create_all`` never ALTERs an existing table, so a column added to a model
    after a database was first created would otherwise be missing. Every
    statement here only adds nullable columns (and indexes) and is idempotent,
    so it is safe to run on every startup and never destroys data.
    """
    from sqlalchemy import inspect, text

    additions: dict[str, list[tuple[str, str]]] = {
        "event_log": [
            ("agent_name", "VARCHAR(80)"),
            ("entity_type", "VARCHAR(40)"),
            ("entity_id", "INTEGER"),
            ("related", "TEXT"),
            ("processed_at", "DATETIME"),
        ],
        "conclusions": [
            ("superseded_at", "DATETIME"),
            ("superseded_by_id", "INTEGER"),
        ],
        "agent_activities": [
            ("sequence", "INTEGER"),
            ("attempt", "INTEGER"),
            ("input_record_ids", "TEXT"),
            ("output_record_ids", "TEXT"),
            ("error", "TEXT"),
            ("state_summary", "TEXT"),
        ],
    }
    indexes: dict[str, list[str]] = {
        "event_log": [
            "CREATE INDEX IF NOT EXISTS ix_event_log_agent_name ON event_log (agent_name)",
            "CREATE INDEX IF NOT EXISTS ix_event_log_entity_type ON event_log (entity_type)",
            "CREATE INDEX IF NOT EXISTS ix_event_log_entity_id ON event_log (entity_id)",
            "CREATE INDEX IF NOT EXISTS ix_event_log_processed_at ON event_log (processed_at)",
            "CREATE INDEX IF NOT EXISTS ix_event_log_investigation_id_id ON event_log (investigation_id, id)",
        ],
        "audit_events": [
            "CREATE INDEX IF NOT EXISTS ix_audit_events_entity_id ON audit_events (entity_id)",
            "CREATE INDEX IF NOT EXISTS ix_audit_events_entity_lookup ON audit_events (entity_type, action, entity_id)",
            "CREATE INDEX IF NOT EXISTS ix_audit_events_investigation_id_created_at ON audit_events (investigation_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_audit_events_conflict_id_created_at ON audit_events (conflict_id, created_at)",
        ],
        "agent_activities": [
            "CREATE INDEX IF NOT EXISTS ix_agent_activities_conflict_id ON agent_activities (conflict_id)",
            "CREATE INDEX IF NOT EXISTS ix_agent_activities_investigation_id_created_at ON agent_activities (investigation_id, created_at)",
        ],
        "evidence": [
            "CREATE INDEX IF NOT EXISTS ix_evidence_claim_id ON evidence (claim_id)",
            "CREATE INDEX IF NOT EXISTS ix_evidence_document_id ON evidence (document_id)",
            "CREATE INDEX IF NOT EXISTS ix_evidence_evidence_type ON evidence (evidence_type)",
            "CREATE INDEX IF NOT EXISTS ix_evidence_supports_hypothesis_id ON evidence (supports_hypothesis_id)",
            "CREATE INDEX IF NOT EXISTS ix_evidence_contradicts_hypothesis_id ON evidence (contradicts_hypothesis_id)",
            "CREATE INDEX IF NOT EXISTS ix_evidence_verification_status ON evidence (verification_status)",
            "CREATE INDEX IF NOT EXISTS ix_evidence_conflict_id_id ON evidence (conflict_id, id)",
        ],
        "documents": [
            "CREATE INDEX IF NOT EXISTS ix_documents_uploaded_at ON documents (uploaded_at)",
        ],
        "investigations": [
            "CREATE INDEX IF NOT EXISTS ix_investigations_updated_at ON investigations (updated_at)",
        ],
        "conclusions": [
            "CREATE INDEX IF NOT EXISTS ix_conclusions_investigation_id_id ON conclusions (investigation_id, id)",
            "CREATE INDEX IF NOT EXISTS ix_conclusions_conflict_id_id ON conclusions (conflict_id, id)",
        ],
        "human_reviews": [
            "CREATE INDEX IF NOT EXISTS ix_human_reviews_investigation_id_created_at ON human_reviews (investigation_id, created_at)",
        ],
        "blackboard_relations": [
            "CREATE INDEX IF NOT EXISTS ix_bb_relation_investigation_id_id ON blackboard_relations (investigation_id, id)",
        ],
    }

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        for table, statements in indexes.items():
            if table not in existing_tables:
                continue
            for statement in statements:
                conn.execute(text(statement))


def init_db() -> None:
    """Create all tables and apply additive migrations. Called on startup.

    New tables are added automatically; existing tables receive any new
    nullable columns via :func:`_run_additive_migrations` so that SQLite can be
    used without a heavy migration tool for local dev.
    """
    # Import models so that they register with the metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_additive_migrations()
