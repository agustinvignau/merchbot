"""Conexión y sesiones de base de datos."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.config import settings
from src.models import Base


def _normalize_db_url(url: str) -> str:
    """Railway/Heroku exponen 'postgres://' pero SQLAlchemy requiere 'postgresql://'."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


_db_url = _normalize_db_url(settings.database_url)

connect_args = (
    {"check_same_thread": False}
    if _db_url.startswith("sqlite")
    else {}
)

engine = create_engine(_db_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Crea las tablas si no existen."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Session:
    """Context manager para una sesión con commit/rollback automático."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
