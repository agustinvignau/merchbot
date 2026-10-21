"""Cabeceras de seguridad para todas las respuestas.

- CSP: las páginas solo cargan scripts y estilos propios (más Google Fonts) y
  solo hablan con este mismo servidor. Si alguien lograra inyectar HTML, no
  podría traer scripts de afuera ni mandar datos a otro dominio.
- No se permite meter la web en un iframe de otro sitio (clickjacking).
- El micrófono solo para esta página; cámara y ubicación, nunca.

La documentación automática (/docs, /redoc) carga recursos de un CDN, así que
queda fuera de la CSP.
"""
from __future__ import annotations

from fastapi import FastAPI, Request

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",           # los scripts están dentro de los HTML
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])

CABECERAS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

SIN_CSP = ("/docs", "/redoc", "/openapi.json")


def agregar_cabeceras_de_seguridad(app: FastAPI) -> None:
    @app.middleware("http")
    async def cabeceras(request: Request, call_next):
        respuesta = await call_next(request)
        for nombre, valor in CABECERAS.items():
            respuesta.headers.setdefault(nombre, valor)
        if not request.url.path.startswith(SIN_CSP):
            respuesta.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            respuesta.headers.setdefault("Cache-Control", "no-store")
        return respuesta
