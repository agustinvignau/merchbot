"""Tests de la normalización del texto dictado por voz."""
import pytest

from merchbot.core.normalizacion import normalizar_dictado, numeros_a_digitos, talles_a_letras


class TestNumeros:
    @pytest.mark.parametrize("entrada,esperado", [
        ("doscientos buzos", "200 buzos"),
        ("doscientos cincuenta buzos", "250 buzos"),
        ("treinta y cinco remeras", "35 remeras"),
        ("ciento veinte gorras", "120 gorras"),
        ("mil quinientas tazas", "1500 tazas"),
        ("dos mil remeras", "2000 remeras"),
        ("veintidós llaveros", "22 llaveros"),
        ("veintiun buzos", "21 buzos"),
        ("dieciséis remeras", "16 remeras"),
        ("cien", "100"),
        ("noventa y nueve", "99"),
        ("Necesito Doscientos Buzos", "Necesito 200 Buzos"),
    ])
    def test_convierte(self, entrada, esperado):
        assert numeros_a_digitos(entrada) == esperado

    @pytest.mark.parametrize("texto", [
        "una remera negra",          # "una" suelto no es número
        "un evento de Coca-Cola",
        "remeras y buzos",            # la "y" sola no se toca
        "ya tengo 200 buzos",         # los dígitos quedan igual
        "el pedido de ese cliente",
    ])
    def test_no_toca(self, texto):
        assert numeros_a_digitos(texto) == texto

    def test_dos_numeros_separados(self):
        assert numeros_a_digitos("dos remeras y tres gorras") == "2 remeras y 3 gorras"

    def test_y_entre_decena_y_otra_palabra(self):
        assert numeros_a_digitos("treinta y buzos") == "30 y buzos"


class TestTalles:
    @pytest.mark.parametrize("entrada,esperado", [
        ("buzos talle ele", "buzos talle L"),
        ("remeras talle eme", "remeras talle M"),
        ("talle ese", "talle S"),
        ("talle equis ele", "talle XL"),
        ("talle doble equis ele", "talle XXL"),
        ("talles equis ese", "talles XS"),
        ("¿y en ele?", "¿y en L?"),
        ("¿y en equis ele?", "¿y en XL?"),
        ("talle m", "talle M"),
        ("Talle Ele", "Talle L"),
    ])
    def test_convierte(self, entrada, esperado):
        assert talles_a_letras(entrada) == esperado

    @pytest.mark.parametrize("texto", [
        "¿hay algo en ese color?",   # "en ese" es demostrativo
        "elegí el modelo",            # "ele" dentro de otra palabra
        "la remera de ese cliente",
    ])
    def test_no_toca(self, texto):
        assert talles_a_letras(texto) == texto


class TestNormalizarDictado:
    def test_frase_completa(self):
        assert normalizar_dictado("necesito doscientos buzos canguro grises talle ele") == \
            "Necesito 200 buzos canguro grises talle L"

    def test_espacios_y_mayuscula_inicial(self):
        assert normalizar_dictado("  cuántas   remeras talle eme  ") == "Cuántas remeras talle M"

    def test_vacio(self):
        assert normalizar_dictado("") == ""
        assert normalizar_dictado(None) == ""
