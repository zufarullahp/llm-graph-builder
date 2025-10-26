"""
PostgreSQL database factory & session utilities
for the Privas AI backend registry.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import get_settings


# ============================================================
# Engine & Session Factory
# ============================================================

cfg = get_settings()

# SQLAlchemy Engine (lazy init, pooled)
engine = create_engine(
    cfg.DATABASE_URL,
    pool_pre_ping=True,      # auto-check connections before using
    pool_size=5,             # adjust per environment
    max_overflow=10,
    echo=(cfg.LOG_LEVEL.upper() == "DEBUG"),
    future=True,
)

# Scoped session factory (no autoflush)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
    class_=Session,
)


# ============================================================
# Context Manager for Dependency Injection
# ============================================================

def get_db():
    """
    FastAPI dependency that yields a SQLAlchemy Session.
    MUST be a generator (yield), not a @contextmanager.
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# ============================================================
# Health Check
# ============================================================

def check_database_health() -> dict:
    """
    Simple connectivity & latency check for PostgreSQL registry.
    Returns:
        {"status": "ok", "latency_ms": float} or raises SQLAlchemyError
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            _ = result.scalar()
            return {"status": "ok"}
    except SQLAlchemyError as e:
        # let the caller decide how to respond (500 or degraded)
        return {"status": "error", "detail": str(e)}


# ============================================================
# CLI / Debug Utility
# ============================================================

if __name__ == "__main__":
    print("Checking Postgres connection...")
    print(check_database_health())
