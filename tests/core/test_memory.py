"""Tests de la memoria conversacional (en RAM y persistida en SQL)."""
import pytest

from merchbot.core.memory import (
    InMemoryConversationStore,
    SqlConversationStore,
    Turno,
)


@pytest.fixture(params=["memoria", "sql"])
def store(request):
    if request.param == "memoria":
        return InMemoryConversationStore(max_turnos=4)
    return SqlConversationStore(max_turnos=4)


class TestContrato:
    """Las dos implementaciones se comportan igual."""

    def test_historial_vacio(self, store):
        assert store.history("nadie") == []

    def test_guarda_en_orden(self, store):
        store.append("u1", "user", "hola")
        store.append("u1", "model", "buenas")
        assert store.history("u1") == [Turno("user", "hola"), Turno("model", "buenas")]

    def test_devuelve_solo_los_ultimos_turnos(self, store):
        for i in range(10):
            store.append("u1", "user", f"m{i}")
        assert [t.text for t in store.history("u1")] == ["m6", "m7", "m8", "m9"]

    def test_aislado_por_usuario(self, store):
        store.append("a", "user", "de a")
        store.append("b", "user", "de b")
        assert [t.text for t in store.history("a")] == ["de a"]

    def test_clear_devuelve_cantidad_y_borra(self, store):
        store.append("u1", "user", "x")
        store.append("u1", "model", "y")
        assert store.clear("u1") == 2
        assert store.history("u1") == []
        assert store.clear("u1") == 0

    def test_id_numerico_y_texto_son_el_mismo_usuario(self, store):
        store.append(123, "user", "desde telegram")
        assert store.history("123")[0].text == "desde telegram"

    def test_rechaza_rol_invalido(self, store):
        with pytest.raises(ValueError):
            store.append("u1", "system", "no")


def test_sql_sobrevive_a_una_instancia_nueva():
    """Simula un reinicio: otra instancia del store lee lo que guardó la primera."""
    SqlConversationStore().append("u1", "user", "antes del reinicio")
    assert SqlConversationStore().history("u1")[0].text == "antes del reinicio"


def test_limit_permite_ver_mas_que_la_ventana_del_modelo():
    store = SqlConversationStore(max_turnos=2)
    for i in range(6):
        store.append("u1", "user", f"m{i}")
    assert len(store.history("u1")) == 2
    assert [t.text for t in store.history("u1", limit=5)] == ["m1", "m2", "m3", "m4", "m5"]
