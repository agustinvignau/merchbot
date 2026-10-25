"""API del panel admin: métricas, registro de interacciones y gestión de reclamos.

Acceso con la clave ADMIN_KEY del .env. Al ingresar se guarda una cookie
HttpOnly derivada de la clave (HMAC); también se acepta el header X-Admin-Key
para usar la API desde scripts. Sin ADMIN_KEY configurada el panel queda
deshabilitado. Los intentos de ingreso tienen un límite por IP.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from merchbot.config import settings
from merchbot.core.metricas import calcular_metricas, cambiar_estado_reclamo, listar_reclamos
from merchbot.core.registro import listar_interacciones
from merchbot.data.models import ESTADOS_RECLAMO
from merchbot.security import limites

ADMIN_COOKIE = "merchbot_admin"
ADMIN_MAX_AGE = 60 * 60 * 12  # 12 horas


def _token() -> str:
    return hmac.new(settings.admin_key.encode(), b"merchbot-admin-v1", hashlib.sha256).hexdigest()


def _clave_valida(clave: Optional[str]) -> bool:
    return bool(settings.admin_key) and hmac.compare_digest((clave or "").encode(), settings.admin_key.encode())


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _autenticado(request: Request, contar_fallos: bool = False) -> bool:
    if not settings.admin_key:
        return False
    cookie = request.cookies.get(ADMIN_COOKIE, "")
    if cookie and hmac.compare_digest(cookie, _token()):
        return True
    header = request.headers.get("X-Admin-Key")
    if header is None:
        return False
    if not contar_fallos:
        return _clave_valida(header)
    # El header es otra forma de ingresar: cuenta contra el mismo límite que el login,
    # si no, se podrían probar claves sin freno.
    clave_ip = ("admin", _ip(request))
    if not limites.limite_login().should_respond(clave_ip):
        raise HTTPException(429, "Demasiados intentos. Esperá unos minutos y probá de nuevo.")
    if _clave_valida(header):
        return True
    limites.limite_login().register_attempt(clave_ip)
    return False


def requiere_admin(request: Request) -> None:
    if not settings.admin_key:
        raise HTTPException(503, "El panel está deshabilitado: configurá ADMIN_KEY en el .env.")
    if not _autenticado(request, contar_fallos=True):
        raise HTTPException(401, "Ingresá la clave del panel.")


class Login(BaseModel):
    clave: str


class CambioEstado(BaseModel):
    estado: str


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/estado")
def estado(request: Request) -> dict:
    return {"configurado": bool(settings.admin_key), "autenticado": _autenticado(request)}


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict:
    if not settings.admin_key:
        raise HTTPException(503, "El panel está deshabilitado: configurá ADMIN_KEY en el .env.")
    ip = _ip(request)
    if not limites.permitir(limites.limite_login(), ("admin", ip)):
        raise HTTPException(429, "Demasiados intentos. Esperá unos minutos y probá de nuevo.")
    if not _clave_valida(body.clave):
        raise HTTPException(401, "La clave no es correcta.")
    limites.limite_login().reset(("admin", ip))
    response.set_cookie(
        ADMIN_COOKIE, _token(), max_age=ADMIN_MAX_AGE, httponly=True, samesite="strict",
        secure=settings.app_env == "production", path="/",
    )
    return {"autenticado": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"autenticado": False}


@router.get("/metricas", dependencies=[Depends(requiere_admin)])
def metricas(
    dias: Optional[int] = Query(7, ge=1, le=3650, description="Últimos N días; omitir con todo=true"),
    todo: bool = False,
    canal: Optional[str] = None,
) -> dict:
    return calcular_metricas(dias=None if todo else dias, canal=canal or None)


@router.get("/interacciones", dependencies=[Depends(requiere_admin)])
def interacciones(
    limite: int = Query(100, ge=1, le=1000),
    canal: Optional[str] = None,
    tipo: Optional[str] = None,
    fuera_de_horario: bool = False,
    errores: bool = False,
) -> dict:
    filas = listar_interacciones(limite=limite, canal=canal or None, tipo=tipo or None,
                                 solo_fuera_de_horario=fuera_de_horario, solo_errores=errores)
    return {"cantidad": len(filas), "interacciones": filas}


@router.get("/reclamos", dependencies=[Depends(requiere_admin)])
def reclamos(
    estado: Optional[str] = None,
    orden: Literal["prioridad", "recientes"] = "prioridad",
    solo_humano: bool = False,
) -> dict:
    if estado and estado not in ESTADOS_RECLAMO:
        raise HTTPException(422, f"Estado inválido. Usá uno de: {', '.join(ESTADOS_RECLAMO)}.")
    filas = listar_reclamos(estado=estado or None, orden=orden, solo_humano=solo_humano)
    return {"cantidad": len(filas), "reclamos": filas}


@router.patch("/reclamos/{numero}", dependencies=[Depends(requiere_admin)])
def actualizar_reclamo(numero: int, body: CambioEstado) -> dict:
    try:
        reclamo = cambiar_estado_reclamo(numero, body.estado)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if reclamo is None:
        raise HTTPException(404, f"No existe el reclamo #{numero}.")
    return reclamo
