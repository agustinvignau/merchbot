"""Tests de las funciones de reclamos, el despacho con contexto y el registro."""
from merchbot.core.horario import resolver_momento
from merchbot.core.registro import clasificar, listar_interacciones, registrar_interaccion
from merchbot.core.tools import consultar_estado_reclamo, ejecutar_tool, registrar_reclamo


class TestRegistrarReclamo:
    def test_registra_con_contexto(self):
        r = registrar_reclamo("Llegaron 20 remeras con manchas", "producto_defectuoso", "Coca-Cola",
                              _contexto={"canal": "web", "user_id": "web:x", "hora": "23:40"})
        assert r["ok"] and r["numero"] == 1
        assert (r["canal"], r["hora"], r["cliente"], r["estado"]) == ("web", "23:40", "Coca-Cola", "abierto")

    def test_tipo_desconocido_pasa_a_otro(self):
        assert registrar_reclamo("El pedido vino incompleto", "cualquiera")["tipo"] == "otro"

    def test_tipo_con_espacios_se_normaliza(self):
        assert registrar_reclamo("No llegó el pedido", "Error en pedido")["tipo"] == "error_en_pedido"

    def test_descripcion_vacia_no_registra(self):
        r = registrar_reclamo("  ", "demora")
        assert r["ok"] is False
        assert consultar_estado_reclamo(1)["encontrado"] is False

    def test_consultar_numero_invalido(self):
        assert consultar_estado_reclamo("abc")["encontrado"] is False


class TestEjecutarToolConContexto:
    def test_pasa_el_contexto_solo_a_las_funciones_que_lo_usan(self):
        r = ejecutar_tool("registrar_reclamo", {"descripcion": "Faltan 5 tazas", "tipo": "faltante"},
                          contexto={"canal": "telegram", "user_id": "42", "hora": "02:00"})
        assert r["canal"] == "telegram"

    def test_el_modelo_no_puede_mandar_argumentos_internos(self):
        r = ejecutar_tool("registrar_reclamo",
                          {"descripcion": "Faltan 5 tazas", "_contexto": {"canal": "falso"}},
                          contexto={"canal": "web", "user_id": "1", "hora": "10:00"})
        assert r["canal"] == "web"

    def test_funciones_sin_contexto_siguen_igual(self, db_with_data):
        r = ejecutar_tool("buscar_stock", {"color": "Negro", "_x": 1}, contexto={"canal": "web"})
        assert r["encontrados"] == 2


class TestClasificar:
    def test_sin_herramientas(self):
        assert clasificar([]) == "conversacion"

    def test_una(self):
        assert clasificar(["obtener_pedidos_de_cliente"]) == "pedidos"

    def test_prioridad(self):
        assert clasificar(["buscar_stock", "registrar_reclamo"]) == "reclamo"
        assert clasificar(["buscar_stock", "listar_productos_a_comprar"]) == "reposicion"

    def test_desconocida(self):
        assert clasificar(["atajo_x"]) == "conversacion"


def test_registrar_y_listar_interacciones():
    m = resolver_momento("03:00")
    for i in range(3):
        registrar_interaccion(canal="web", user_id="u", momento=m, consulta=f"q{i}",
                              respuesta="r", herramientas=["buscar_stock"], duracion_ms=10)
    registrar_interaccion(canal="telegram", user_id="t", momento=m, consulta="qt",
                          respuesta="r", herramientas=[], duracion_ms=5)
    todas = listar_interacciones()
    assert [i["consulta"] for i in todas] == ["qt", "q2", "q1", "q0"]
    assert len(listar_interacciones(canal="web")) == 3
    assert listar_interacciones(limite=1)[0]["tipo"] == "conversacion"
