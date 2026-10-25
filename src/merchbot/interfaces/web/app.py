"""Interfaz web de MerchBot: API FastAPI + chat en HTML.

Endpoints:
    GET    /               chat (static/index.html)
    POST   /api/chat       envía un mensaje, devuelve la respuesta
    GET    /api/historial  conversación guardada de la sesión
    DELETE /api/historial  borra la conversación de la sesión
    GET    /api/comprar    productos a reponer (sin IA)
    GET    /api/resumen    resumen ejecutivo (sin IA)
    POST   /api/reclamos   registra un reclamo desde el formulario (sin IA)
    GET    /api/reclamos/{numero}  estado de un reclamo
    GET    /api/horario    hora real y horario de atención
    POST   /api/sync       actualiza la base desde la fuente de datos
    GET    /health         estado del servicio
    GET    /admin          panel de métricas (API en /api/admin, ver admin.py)
    GET    /login          ingreso al chat (si CHAT_USUARIOS está configurado)
    POST   /api/login      {"usuario", "clave"} -> cookie de sesión firmada
    POST   /api/logout     cierra la sesión
    GET    /api/sesion     si hace falta ingresar y quién está conectado

Sin CHAT_USUARIOS, cada navegador tiene su propia conversación, identificada con
una cookie (`merchbot_sid`). Con CHAT_USUARIOS, hay que ingresar y la conversación
es del usuario (lo sigue en cualquier navegador). La lógica vive en ChatService,
igual que en Telegram. Seguridad: ver security/ y docs/SEGURIDAD.md.

Los endpoints que atienden al usuario aceptan una hora simulada ("HH:MM") para
la demo de atención 24/7: el asistente responde como si fuera esa hora.
"""
from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from merchbot import __version__
from merchbot.config import settings
from merchbot.core.chat_service import MAX_MESSAGE_LEN, ChatService, get_chat_service
from merchbot.core.errores import describir_error
from merchbot.core.horario import dias_habiles, resolver_momento, validar_hora
from merchbot.data.models import TIPOS_RECLAMO
from merchbot.interfaces.web.admin import router as admin_router
from merchbot.interfaces.web.cabeceras import agregar_cabeceras_de_seguridad
from merchbot.security import auth, limites


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "merchbot_sid"
AUTH_COOKIE = "merchbot_auth"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 días
_SID_VALIDO = re.compile(r"^[a-f0-9]{32}$")


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------

HoraSimulada = Optional[str]


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LEN)
    hora: HoraSimulada = Field(None, description="Hora simulada HH:MM; vacío = hora real")
    origen: Literal["texto", "voz"] = Field("texto", description="'voz' si el mensaje se dictó")


class ChatReply(BaseModel):
    reply: str
    hora: str
    fuera_de_horario: bool
    tipo: str
    consulta: str = Field(..., description="La consulta como la procesó el asistente (normalizada si fue dictada)")
    fuentes: list[str] = Field(default_factory=list, description="Secciones de las políticas en que se basó la respuesta")


class Turno(BaseModel):
    role: str
    text: str
    hora: Optional[str] = None


class ReclamoRequest(BaseModel):
    descripcion: str = Field(..., min_length=5, max_length=2000)
    tipo: str = Field("otro", description=f"Uno de: {', '.join(TIPOS_RECLAMO)}")
    cliente: Optional[str] = Field(None, max_length=160)
    hora: HoraSimulada = None


class Historial(BaseModel):
    mensajes: list[Turno]


class Login(BaseModel):
    usuario: str = Field(..., max_length=64)
    clave: str = Field(..., max_length=256)


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _usuario(request: Request) -> Optional[str]:
    return auth.leer_token(request.cookies.get(AUTH_COOKIE))


def _session_id(request: Request, response: Response) -> str:
    """Identifica la conversación.

    Con login activo: el usuario (401 si no ingresó). Sin login: una cookie por
    navegador, que se crea si no hay una válida.
    """
    if auth.login_requerido():
        usuario = _usuario(request)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Ingresá con tu usuario para usar el chat.")
        return f"web:u:{usuario}"
    sid = request.cookies.get(SESSION_COOKIE, "")
    if not _SID_VALIDO.match(sid):
        sid = uuid.uuid4().hex
        response.set_cookie(
            SESSION_COOKIE,
            sid,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.app_env == "production",
        )
    return f"web:{sid}"


def _hora(valor: Optional[str]) -> Optional[str]:
    """Valida la hora simulada; 422 si viene mal."""
    try:
        return validar_hora(valor)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def create_app(
    service_factory: Callable[[], ChatService] = get_chat_service,
    on_startup: Optional[Callable[[], None]] = None,
) -> FastAPI:
    """Crea la app. Los parámetros permiten inyectar dobles en los tests."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if on_startup is not None:
            on_startup()
        yield

    app = FastAPI(
        title="MerchBot",
        version=__version__,
        description="Asistente conversacional de stock para merchandising.",
        lifespan=lifespan,
    )

    agregar_cabeceras_de_seguridad(app)

    def service() -> ChatService:
        return service_factory()

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        if auth.login_requerido() and _usuario(request) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/login", include_in_schema=False)
    def pagina_login(request: Request):
        if not auth.login_requerido() or _usuario(request):
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/api/sesion")
    def sesion(request: Request) -> dict:
        return {"login_requerido": auth.login_requerido(), "usuario": _usuario(request)}

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response) -> dict:
        if not auth.login_requerido():
            return {"usuario": None, "login_requerido": False}
        if not limites.permitir(limites.limite_login(), ("chat", _ip(request))):
            raise HTTPException(429, "Demasiados intentos. Esperá unos minutos y probá de nuevo.")
        usuario = auth.autenticar(body.usuario, body.clave)
        if usuario is None:
            raise HTTPException(401, "Usuario o clave incorrectos.")
        limites.limite_login().reset(("chat", _ip(request)))
        response.set_cookie(
            AUTH_COOKIE, auth.crear_token(usuario), max_age=settings.sesion_horas * 3600,
            httponly=True, samesite="lax", secure=settings.app_env == "production", path="/",
        )
        return {"usuario": usuario, "login_requerido": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(AUTH_COOKIE, path="/")
        return {"usuario": None}

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "fuente_de_datos": settings.fuente_de_datos,
        }

    # Los endpoints son `def` (no `async def`): FastAPI los corre en un thread
    # aparte, así una consulta lenta a Gemini no bloquea al resto.

    @app.post("/api/chat", response_model=ChatReply)
    def chat(
        body: ChatRequest,
        request: Request,
        sid: str = Depends(_session_id),
        svc: ChatService = Depends(service),
    ) -> ChatReply:
        hora = _hora(body.hora)
        if not (limites.permitir(limites.limite_chat(), sid)
                and limites.permitir(limites.limite_chat_ip(), ("ip", _ip(request)))):
            raise HTTPException(
                status_code=429,
                detail="Estás mandando muchas consultas seguidas. Esperá un minuto y seguimos.",
            )
        try:
            a = svc.atender(sid, body.message, canal="web", hora_simulada=hora, origen=body.origen)
            return ChatReply(reply=a.texto, hora=a.hora, fuera_de_horario=a.fuera_de_horario,
                             tipo=a.tipo, consulta=a.consulta, fuentes=a.fuentes)
        except Exception as e:
            error = describir_error(e)
            logger.exception("Error procesando mensaje de %s (%s)", sid, error.codigo)
            raise HTTPException(status_code=502, detail=error.mensaje)

    @app.get("/api/historial", response_model=Historial)
    def historial(
        sid: str = Depends(_session_id),
        svc: ChatService = Depends(service),
    ) -> Historial:
        turnos = svc.history(sid)
        return Historial(mensajes=[Turno(role=t.role, text=t.text, hora=t.hora) for t in turnos])

    @app.delete("/api/historial")
    def borrar_historial(
        sid: str = Depends(_session_id),
        svc: ChatService = Depends(service),
    ) -> dict:
        return {"borrados": svc.clear(sid)}

    @app.get("/api/comprar")
    def comprar(
        hora: Optional[str] = Query(None),
        sid: str = Depends(_session_id),
        svc: ChatService = Depends(service),
    ) -> dict:
        productos = svc.productos_a_comprar(sid, canal="web", hora_simulada=_hora(hora))
        return {"cantidad": len(productos), "productos": productos}

    @app.get("/api/resumen")
    def resumen(
        hora: Optional[str] = Query(None),
        sid: str = Depends(_session_id),
        svc: ChatService = Depends(service),
    ) -> dict:
        r = svc.resumen_ejecutivo(sid, canal="web", hora_simulada=_hora(hora))
        # Las tuplas (nombre, unidades) se pasan a objetos para el frontend.
        for clave in ("top_cliente", "top_producto"):
            if r.get(clave):
                nombre, unidades = r[clave]
                r[clave] = {"nombre": nombre, "unidades": int(unidades)}
        return r

    @app.post("/api/reclamos", status_code=201)
    def crear_reclamo(
        body: ReclamoRequest,
        request: Request,
        sid: str = Depends(_session_id),
        svc: ChatService = Depends(service),
    ) -> dict:
        if not (limites.permitir(limites.limite_chat(), sid)
                and limites.permitir(limites.limite_chat_ip(), ("ip", _ip(request)))):
            raise HTTPException(429, "Estás mandando muchos reclamos seguidos. Esperá un minuto.")
        resultado = svc.registrar_reclamo(
            sid, body.descripcion, body.tipo, body.cliente,
            canal="web", hora_simulada=_hora(body.hora),
        )
        if not resultado.get("ok"):
            raise HTTPException(status_code=422, detail=resultado.get("error", "Reclamo inválido."))
        return resultado

    @app.get("/api/reclamos/{numero}")
    def ver_reclamo(numero: int, sid: str = Depends(_session_id), svc: ChatService = Depends(service)) -> dict:
        # Solo los reclamos de esta sesión: uno ajeno da 404 igual que uno inexistente.
        resultado = svc.consultar_reclamo(numero, user_id=sid)
        if not resultado.get("encontrado"):
            raise HTTPException(status_code=404, detail=f"No existe el reclamo #{numero}.")
        return resultado

    @app.get("/api/horario")
    def horario() -> dict:
        ahora = resolver_momento()
        return {
            "hora_actual": ahora.hora,
            "dia": ahora.dia,
            "dia_habil": ahora.dia_semana in dias_habiles(),
            "fuera_de_horario": ahora.fuera_de_horario,
            "atencion_desde": settings.atencion_desde,
            "atencion_hasta": settings.atencion_hasta,
            "zona_horaria": settings.timezone,
        }

    @app.post("/api/sync")
    def sync(_: str = Depends(_session_id)) -> dict:
        from merchbot.data.refresh import actualizar_datos

        # Límite global: cada sincronización descarga la planilla completa.
        if not limites.permitir(limites.limite_sync(), "sync"):
            raise HTTPException(429, "Los datos se actualizaron hace un momento. Probá en un minuto.")
        resultado = actualizar_datos()
        if not resultado.ok:
            raise HTTPException(status_code=502, detail=resultado.error)
        return {
            "fuente": settings.fuente_de_datos,
            "productos": resultado.stock_total,
            "pedidos": resultado.pedidos_total,
        }

    @app.get("/admin", include_in_schema=False)
    def admin() -> FileResponse:
        return FileResponse(STATIC_DIR / "admin.html")

    app.include_router(admin_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _arranque() -> None:
    """Prepara la base, la fuente de datos y el índice de políticas al iniciar el servidor."""
    from merchbot.core.rag import indexar_sin_fallar
    from merchbot.data.database import init_db
    from merchbot.data.scheduler import start_scheduler

    init_db()
    start_scheduler()  # hace la primera carga y, con Sheets, el sync periódico
    indexar_sin_fallar()


def run(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Arranca el servidor web con uvicorn."""
    import uvicorn

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    app = create_app(on_startup=_arranque)
    uvicorn.run(
        app,
        host=host or settings.web_host,
        port=port or settings.web_port,
        # Detrás de un proxy con HTTPS (Caddy/nginx), la IP real llega en X-Forwarded-For.
        # Solo se le cree a los proxies listados, para que nadie pueda falsearla.
        proxy_headers=True,
        forwarded_allow_ips=settings.proxies_confiables,
    )
