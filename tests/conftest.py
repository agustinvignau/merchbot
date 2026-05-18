"""Fixtures compartidas: DB en memoria + CSV de fixture real del Sheets."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database as db_module
from src.models import Base


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# DB en memoria
# ---------------------------------------------------------------------------

@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def test_session_factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def _patch_db(monkeypatch, test_engine, test_session_factory):
    """Reemplaza el engine global por el de test para que get_session() lo use."""
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_factory)


# ---------------------------------------------------------------------------
# Fixtures del Sheets real (CSV congelado de la versión de Agustín)
# ---------------------------------------------------------------------------

@pytest.fixture
def stock_csv() -> str:
    """CSV de la hoja Stock tal cual lo devuelve Google Sheets."""
    return (FIXTURES_DIR / "stock_sample.csv").read_text(encoding="utf-8")


@pytest.fixture
def pedidos_csv() -> str:
    return (FIXTURES_DIR / "pedidos_sample.csv").read_text(encoding="utf-8")
