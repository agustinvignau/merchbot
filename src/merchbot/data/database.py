"""Conexión y sesiones de base de datos."""
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session

from merchbot.config import settings
from merchbot.data.models import Base


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
    """Crea las tablas que falten y agrega columnas nuevas a las existentes."""
    Base.metadata.create_all(bind=engine)
    _agregar_columnas_faltantes()


def _agregar_columnas_faltantes() -> None:
    """Migración liviana: agrega columnas nuevas (nullables) a tablas ya creadas.

    `create_all` no modifica tablas existentes. Para un proyecto de este tamaño
    alcanza con esto en vez de Alembic: solo agrega columnas que aceptan NULL o
    tienen default, nunca borra ni cambia tipos.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for tabla in Base.metadata.sorted_tables:
            if not inspector.has_table(tabla.name):
                continue
            existentes = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in existentes:
                    continue
                if not columna.nullable and columna.default is None:
                    continue  # no se puede agregar sin valor; requiere migración manual
                tipo = columna.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{tabla.name}" ADD COLUMN "{columna.name}" {tipo}'))


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
