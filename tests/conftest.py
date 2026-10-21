"""Fixtures compartidas: DB en memoria + CSV de fixture real del Sheets."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import merchbot.data.database as db_module
from merchbot.data.models import Base, Pedido, StockItem


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


# ---------------------------------------------------------------------------
# Datos de ejemplo (compartidos por varios módulos de test)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_stock():
    return [
        StockItem(sku="REM-CR-BCO-M", producto="Remera", modelo="Cuello Redondo",
                  color="Blanco", talle="M", stock_inicial=100, ingresos=100,
                  pedidos=180, stock_actual=20, estado="OK"),
        StockItem(sku="REM-DF-NEG-M", producto="Remera", modelo="Dry-Fit",
                  color="Negro", talle="M", stock_inicial=30, ingresos=0,
                  pedidos=45, stock_actual=-15, estado="COMPRAR"),
        StockItem(sku="BUZ-CN-NEG-L", producto="Buzo", modelo="Canguro",
                  color="Negro", talle="L", stock_inicial=45, ingresos=30,
                  pedidos=50, stock_actual=25, estado="OK"),
        StockItem(sku="GOR-RES-ROJ", producto="Gorra", modelo="Con Respiración",
                  color="Rojo", talle="Único", stock_inicial=20, ingresos=0,
                  pedidos=40, stock_actual=-20, estado="COMPRAR"),
    ]


@pytest.fixture
def sample_pedidos():
    return [
        Pedido(fecha=date(2026, 5, 14), cliente="Globant - Welcome Kit",
               sku="BUZ-CN-NEG-L", producto="Buzo Canguro Negro L", cantidad=50),
        Pedido(fecha=date(2026, 4, 15), cliente="Coca-Cola - Evento",
               sku="REM-CR-BCO-M", producto="Remera CR Blanco M", cantidad=120),
        Pedido(fecha=date(2026, 4, 28), cliente="Movistar - Día del Padre",
               sku="REM-DF-NEG-M", producto="Remera Dry-Fit Negro M", cantidad=45),
    ]


@pytest.fixture
def db_with_data(test_session_factory, sample_stock, sample_pedidos):
    session = test_session_factory()
    session.add_all(sample_stock + sample_pedidos)
    session.commit()
    session.close()
    return sample_stock, sample_pedidos
