"""Login del chat: usuarios definidos en el .env y sesión con cookie firmada.

Formato de CHAT_USUARIOS (separados por coma):
    ana:una-clave-larga                    clave en texto plano (solo para probar)
    ana:pbkdf2_sha256$600000$<sal>$<hash>  clave hasheada (recomendado)

El hash se genera con `merchbot hashear-clave`. Si CHAT_USUARIOS está vacío, el
chat queda abierto (pensado para correr en tu máquina).

La sesión es un token `datos.firma`: los datos (usuario y vencimiento) van en
base64 y la firma es un HMAC-SHA256 con SECRET_KEY. Nadie puede fabricar o
modificar un token sin conocer la clave secreta.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional

from merchbot.config import settings

logger = logging.getLogger(__name__)

PREFIJO_HASH = "pbkdf2_sha256"
ITERACIONES = 600_000
_secreto_temporal: Optional[bytes] = None


# ---------------------------------------------------------------------------
# Claves
# ---------------------------------------------------------------------------

def hashear_clave(clave: str, iteraciones: int = ITERACIONES) -> str:
    sal = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), iteraciones)
    return f"{PREFIJO_HASH}${iteraciones}${sal}${base64.b64encode(dk).decode()}"


def verificar_clave(guardada: str, ingresada: str) -> bool:
    """Compara en tiempo constante; acepta hash pbkdf2 o texto plano."""
    if guardada.startswith(PREFIJO_HASH + "$"):
        try:
            _, iteraciones, sal, esperado = guardada.split("$", 3)
            dk = hashlib.pbkdf2_hmac("sha256", ingresada.encode(), sal.encode(), int(iteraciones))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(base64.b64encode(dk).decode(), esperado)
    return hmac.compare_digest(guardada.encode(), ingresada.encode())


def usuarios() -> dict[str, str]:
    """CHAT_USUARIOS como {usuario: clave_o_hash}. Ignora entradas mal formadas."""
    resultado = {}
    for entrada in settings.chat_usuarios.split(","):
        usuario, sep, clave = entrada.strip().partition(":")
        if sep and usuario.strip() and clave.strip():
            resultado[usuario.strip().lower()] = clave.strip()
    return resultado


def login_requerido() -> bool:
    return bool(usuarios())


def autenticar(usuario: str, clave: str) -> Optional[str]:
    """Devuelve el usuario normalizado si la clave es correcta."""
    usuario = (usuario or "").strip().lower()
    guardada = usuarios().get(usuario)
    if guardada is None:
        # Igual se calcula un hash para no revelar por tiempo qué usuarios existen.
        verificar_clave(f"{PREFIJO_HASH}$1000$x$x", clave or "")
        return None
    return usuario if verificar_clave(guardada, clave or "") else None


# ---------------------------------------------------------------------------
# Tokens de sesión
# ---------------------------------------------------------------------------

def _secreto() -> bytes:
    global _secreto_temporal
    if settings.secret_key:
        return settings.secret_key.encode()
    if _secreto_temporal is None:
        _secreto_temporal = secrets.token_bytes(32)
        logger.warning("SECRET_KEY vacía: uso una clave temporal; las sesiones se cierran al reiniciar.")
    return _secreto_temporal


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def crear_token(usuario: str, horas: Optional[int] = None, ahora: Optional[float] = None) -> str:
    vence = int((ahora or time.time()) + 3600 * (horas or settings.sesion_horas))
    datos = _b64(json.dumps({"u": usuario, "exp": vence}, separators=(",", ":")).encode())
    firma = hmac.new(_secreto(), datos.encode(), hashlib.sha256).hexdigest()
    return f"{datos}.{firma}"


def leer_token(token: Optional[str], ahora: Optional[float] = None) -> Optional[str]:
    """Usuario del token si la firma es válida, no venció y el usuario sigue existiendo."""
    if not token or "." not in token:
        return None
    datos, firma = token.rsplit(".", 1)
    esperada = hmac.new(_secreto(), datos.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(firma, esperada):
        return None
    try:
        contenido = json.loads(_desb64(datos))
    except (ValueError, json.JSONDecodeError):
        return None
    if contenido.get("exp", 0) < (ahora or time.time()):
        return None
    usuario = contenido.get("u")
    return usuario if usuario in usuarios() else None
