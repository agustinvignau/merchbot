"""Las métricas del panel coinciden con consultas SQL directas sobre el registro."""
from datetime import timedelta

import pytest
from sqlalchemy import text

from merchbot.core.horario import resolver_momento
from merchbot.core.metricas import _percentil, calcular_metricas, cambiar_estado_reclamo, listar_reclamos
from merchbot.core.registro import listar_interacciones, registrar_interaccion
from merchbot.core.tools import registrar_reclamo
from merchbot.data.database import get_session
from merchbot.data.models import Interaccion
from merchbot.timeutils import utc_now


def _registrar(hora, canal="web", tools=("buscar_stock",), duracion=100, estado="ok", user="u1", tipo=None):
    registrar_interaccion(canal=canal, user_id=user, momento=resolver_momento(hora), consulta="q",
                          respuesta="r", herramientas=list(tools), duracion_ms=duracion,
                          estado=estado, tipo=tipo)


@pytest.fixture
def actividad():
    _registrar("10:15", duracion=200)
    _registrar("10:40", tools=("obtener_pedidos_de_cliente",), duracion=400, user="u2")
    _registrar("03:20", canal="telegram", tools=("registrar_reclamo",), duracion=900, user="t1")
    _registrar("22:45", tools=(), duracion=100, estado="error")
    _registrar("22:50", tools=("buscar_stock", "listar_productos_a_comprar"), duracion=300)
    registrar_reclamo("Remeras manchadas", "producto_defectuoso")
    registrar_reclamo("Pedido demorado", "demora")


def _sql(consulta):
    with get_session() as s:
        return s.execute(text(consulta)).scalar()


class TestMetricas:
    def test_totales_coinciden_con_sql(self, actividad):
        m = calcular_metricas(dias=None)
        t = m["totales"]
        assert t["interacciones"] == _sql("SELECT COUNT(*) FROM interacciones") == 5
        assert t["usuarios"] == _sql("SELECT COUNT(DISTINCT user_id) FROM interacciones") == 3
        assert t["errores"] == _sql("SELECT COUNT(*) FROM interacciones WHERE estado='error'") == 1
        assert t["reclamos_abiertos"] == _sql("SELECT COUNT(*) FROM reclamos WHERE estado='abierto'") == 2

    def test_fuera_de_horario(self, actividad):
        t = calcular_metricas(dias=None)["totales"]
        esperado = _sql("SELECT COUNT(*) FROM interacciones WHERE fuera_de_horario=1")
        assert t["fuera_de_horario"] == esperado
        assert t["porcentaje_fuera_de_horario"] == round(100 * esperado / 5, 1)

    def test_por_hora_suma_el_total(self, actividad):
        m = calcular_metricas(dias=None)
        assert sum(m["por_hora"]) == 5
        assert m["por_hora"][10] == 2 and m["por_hora"][22] == 2 and m["por_hora"][3] == 1

    def test_por_tipo_ordenado(self, actividad):
        por_tipo = calcular_metricas(dias=None)["por_tipo"]
        assert por_tipo == {"stock": 1, "pedidos": 1, "reclamo": 1, "conversacion": 1, "reposicion": 1}
        assert list(por_tipo.values()) == sorted(por_tipo.values(), reverse=True)

    def test_herramientas_cuenta_cada_uso(self, actividad):
        h = calcular_metricas(dias=None)["herramientas"]
        assert h["buscar_stock"] == 2
        assert h["listar_productos_a_comprar"] == 1
        assert next(iter(h)) == "buscar_stock"

    def test_duraciones(self, actividad):
        t = calcular_metricas(dias=None)["totales"]
        assert t["duracion_mediana_ms"] == 300
        assert t["duracion_p95_ms"] == 900

    def test_filtro_por_canal(self, actividad):
        m = calcular_metricas(dias=None, canal="telegram")
        assert m["totales"]["interacciones"] == 1
        assert m["por_canal"] == {"telegram": 1}

    def test_filtro_por_dias_excluye_lo_viejo(self, actividad):
        with get_session() as s:
            vieja = s.query(Interaccion).first()
            vieja.created_at = utc_now() - timedelta(days=30)
        assert calcular_metricas(dias=7)["totales"]["interacciones"] == 4
        assert calcular_metricas(dias=None)["totales"]["interacciones"] == 5

    def test_sin_datos(self):
        m = calcular_metricas()
        assert m["totales"]["interacciones"] == 0
        assert m["totales"]["duracion_mediana_ms"] is None
        assert m["por_hora"] == [0] * 24

    def test_reclamos_por_estado_incluye_todos_los_estados(self, actividad):
        r = calcular_metricas()["reclamos"]
        assert r["por_estado"] == {"abierto": 2, "en_revision": 0, "resuelto": 0}
        assert r["por_tipo"] == {"producto_defectuoso": 1, "demora": 1}


class TestPercentil:
    @pytest.mark.parametrize("valores,p,esperado", [
        ([], 50, None), ([7], 95, 7), ([1, 2, 3, 4], 50, 2), ([1, 2, 3, 4, 5], 50, 3),
        (list(range(1, 101)), 95, 95),
    ])
    def test_rango_mas_cercano(self, valores, p, esperado):
        assert _percentil(valores, p) == esperado


class TestReclamosAdmin:
    def test_listar_y_filtrar(self, actividad):
        assert [r["numero"] for r in listar_reclamos()] == [2, 1]
        cambiar_estado_reclamo(1, "resuelto")
        assert [r["numero"] for r in listar_reclamos(estado="abierto")] == [2]

    def test_cambiar_estado(self, actividad):
        assert cambiar_estado_reclamo(2, "en_revision")["estado"] == "en_revision"

    def test_estado_invalido(self, actividad):
        with pytest.raises(ValueError):
            cambiar_estado_reclamo(1, "cerrado")

    def test_reclamo_inexistente(self):
        assert cambiar_estado_reclamo(99, "resuelto") is None


class TestFiltrosDeInteracciones:
    def test_filtros(self, actividad):
        assert len(listar_interacciones(solo_errores=True)) == 1
        assert {i["tipo"] for i in listar_interacciones(tipo="pedidos")} == {"pedidos"}
        assert all(i["fuera_de_horario"] for i in listar_interacciones(solo_fuera_de_horario=True))
