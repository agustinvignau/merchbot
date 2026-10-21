"""La migración liviana agrega columnas nuevas a bases creadas con versiones anteriores."""
from sqlalchemy import inspect, text

import merchbot.data.database as db


def test_agrega_columna_hora_a_mensajes_de_una_base_vieja(test_engine):
    with test_engine.begin() as conn:
        conn.execute(text("DROP TABLE mensajes"))
        conn.execute(text(
            "CREATE TABLE mensajes (id INTEGER PRIMARY KEY, user_id VARCHAR(64) NOT NULL, "
            "role VARCHAR(8) NOT NULL, text TEXT NOT NULL, created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO mensajes (user_id, role, text, created_at) VALUES ('u', 'user', 'hola', '2026-10-01')"
        ))
    db.init_db()
    columnas = {c["name"] for c in inspect(test_engine).get_columns("mensajes")}
    assert "hora" in columnas
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT text, hora FROM mensajes")).one() == ("hola", None)


def test_es_idempotente():
    db.init_db()
    db.init_db()
