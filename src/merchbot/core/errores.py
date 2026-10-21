"""Traducción de errores del proveedor de IA a mensajes accionables.

Cuando Gemini falla, el usuario (y quien mira el panel) tiene que saber si es la
API key, el modelo, la cuota o la red, sin ver detalles internos ni la clave.
"""
from __future__ import annotations

from dataclasses import dataclass

from merchbot.config import settings


@dataclass(frozen=True)
class ErrorIA:
    codigo: str          # corto, para el registro y el panel
    mensaje: str         # para mostrarle al usuario


def describir_error(exc: BaseException) -> ErrorIA:
    texto = str(exc)
    status = getattr(exc, "code", None)
    estado = str(getattr(exc, "status", "") or "")
    mensaje_api = str(getattr(exc, "message", "") or "")
    todo = f"{texto} {estado} {mensaje_api}".lower()

    if isinstance(exc, ValueError) and "api key" in todo:
        return ErrorIA("sin_api_key", "Falta la GEMINI_API_KEY en el .env. Cargala y reiniciá MerchBot.")
    if "api_key_invalid" in todo or "api key not valid" in todo or (status in (400, 403) and "key" in todo):
        return ErrorIA("api_key_invalida", "La GEMINI_API_KEY no es válida. Revisala en Google AI Studio y reiniciá MerchBot.")
    if status == 404 or "not_found" in todo or "no longer available" in todo or "is not found" in todo:
        return ErrorIA(
            "modelo_no_disponible",
            f"El modelo '{settings.gemini_model}' no está disponible para tu API key. "
            "Cambiá GEMINI_MODEL en el .env por uno vigente (corré 'merchbot diagnostico' para ver cuáles) y reiniciá.",
        )
    if status == 429 or "resource_exhausted" in todo or "quota" in todo:
        return ErrorIA("cuota_agotada", "Se agotó la cuota de Gemini por ahora. Probá en un rato o revisá tu plan en Google AI Studio.")
    if status == 403 or "permission_denied" in todo:
        return ErrorIA("sin_permiso", "La API key no tiene permiso para usar Gemini. Revisala en Google AI Studio.")
    if status in (500, 502, 503, 504) or "unavailable" in todo or "overloaded" in todo:
        return ErrorIA("servicio_no_disponible", "Gemini no está respondiendo en este momento. Probá de nuevo en unos segundos.")
    if any(p in todo for p in ("connecterror", "connection", "timed out", "timeout", "name resolution")):
        return ErrorIA("sin_conexion", "No pude conectarme con Gemini. Revisá la conexión a internet.")
    return ErrorIA("error_desconocido", "No pude consultar al asistente. Probá de nuevo en unos segundos.")
