"""Normalización del texto que llega por voz.

El reconocimiento de voz devuelve lo que escucha tal cual: "doscientos buzos
talle ele". Antes de mandarlo al modelo lo llevamos a la forma en que están
los datos ("200 buzos talle L"). Es un paso clásico de preprocesamiento en
PLN: tokenizar, reconocer patrones y reescribirlos.

Se aplica solo a lo dictado; lo escrito a mano no se toca.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Números en palabras → dígitos
# ---------------------------------------------------------------------------

_UNIDADES = {
    "cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintiuna": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
_CENTENAS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300,
    "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500,
    "quinientas": 500, "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
    "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900,
    "novecientas": 900,
}
# "un"/"una" sueltos no se convierten ("una remera", "un evento"), solo dentro de un número.
_UNO_COMPUESTO = {"un": 1, "una": 1}
_MIL = "mil"


def _sin_tildes(palabra: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", palabra) if unicodedata.category(c) != "Mn")


def _valor(palabra: str) -> int | None:
    p = _sin_tildes(palabra.lower())
    for tabla in (_UNIDADES, _DECENAS, _CENTENAS):
        if p in tabla:
            return tabla[p]
    return None


def _es_parte(palabra: str, dentro: bool) -> bool:
    p = _sin_tildes(palabra.lower())
    if _valor(p) is not None or p == _MIL:
        return True
    return dentro and p in _UNO_COMPUESTO


_TOKEN = re.compile(r"\w+|\W+", re.UNICODE)


def numeros_a_digitos(texto: str) -> str:
    """'doscientos cincuenta buzos' → '250 buzos'; 'mil quinientas tazas' → '1500 tazas'."""
    tokens = _TOKEN.findall(texto)
    salida: list[str] = []
    i = 0
    while i < len(tokens):
        if not _es_parte(tokens[i], dentro=False):
            salida.append(tokens[i])
            i += 1
            continue
        # Consumir la secuencia numérica más larga: palabras numéricas, espacios y "y" entre decena y unidad.
        j, total, actual, ultimo = i, 0, 0, None
        fin = i
        while j < len(tokens):
            tok = tokens[j]
            p = _sin_tildes(tok.lower())
            if tok.isspace():
                j += 1
                continue
            if p == "y" and ultimo in _DECENAS and j + 2 < len(tokens) and _valor(tokens[j + 2]) is not None \
                    and _valor(tokens[j + 2]) < 10:
                j += 1
                continue
            if p == _MIL:
                total += max(actual, 1) * 1000
                actual = 0
            elif _es_parte(tok, dentro=ultimo is not None):
                actual += _valor(p) if _valor(p) is not None else _UNO_COMPUESTO[p]
            else:
                break
            ultimo = p
            fin = j
            j += 1
        salida.append(str(total + actual))
        i = fin + 1
    return "".join(salida)


# ---------------------------------------------------------------------------
# Talles dictados → letras
# ---------------------------------------------------------------------------

_TALLES = [
    # El orden importa: primero los compuestos.
    (r"doble equis ele|equis equis ele", "XXL"),
    (r"equis ele", "XL"),
    (r"equis ese", "XS"),
    (r"ele", "L"),
    (r"eme", "M"),
    (r"ese", "S"),
]
_TALLE_LETRA = "|".join(p for p, _ in _TALLES)


def _letra(dicho: str) -> str:
    dicho = re.sub(r"\s+", " ", dicho.lower())
    for patron, letra in _TALLES:
        if re.fullmatch(patron, dicho):
            return letra
    return dicho


# Después de "talle"/"talles" se acepta cualquier talle. Después de "en" no se
# acepta "ese", porque "en ese" casi siempre es demostrativo ("en ese color").
_DESPUES_DE_TALLE = re.compile(rf"\b(talles?)\s+({_TALLE_LETRA})\b", re.IGNORECASE)
_DESPUES_DE_EN = re.compile(r"\b(en)\s+(doble equis ele|equis equis ele|equis ele|ele|eme)\b", re.IGNORECASE)
# Letras sueltas que el reconocimiento escribe en minúscula: "talle m" → "talle M".
_LETRA_MINUSCULA = re.compile(r"\b(talles?)\s+(xxl|xl|xs|s|m|l)\b", re.IGNORECASE)


def talles_a_letras(texto: str) -> str:
    """'buzos talle ele' → 'buzos talle L'; '¿y en equis ele?' → '¿y en XL?'."""
    texto = _DESPUES_DE_TALLE.sub(lambda m: f"{m.group(1)} {_letra(m.group(2))}", texto)
    texto = _DESPUES_DE_EN.sub(lambda m: f"{m.group(1)} {_letra(m.group(2))}", texto)
    texto = _LETRA_MINUSCULA.sub(lambda m: f"{m.group(1)} {m.group(2).upper()}", texto)
    return texto


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def normalizar_dictado(texto: str) -> str:
    """Aplica todas las reglas al texto reconocido por voz."""
    texto = re.sub(r"\s+", " ", (texto or "")).strip()
    texto = numeros_a_digitos(texto)
    texto = talles_a_letras(texto)
    if texto:
        texto = texto[0].upper() + texto[1:]
    return texto
