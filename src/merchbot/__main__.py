"""Punto de entrada de MerchBot.

Uso:
    python -m merchbot                 # interfaz web en http://127.0.0.1:8000
    python -m merchbot web --port 9000
    python -m merchbot telegram        # bot de Telegram (long-polling)
    python -m merchbot cargar-demo     # carga la planilla de ejemplo en la base
    python -m merchbot indexar-politicas  # (re)indexa data/politicas.md para el RAG
    python -m merchbot diagnostico     # prueba la API key, el modelo y los embeddings
    python -m merchbot hashear-clave   # genera el hash de una clave para CHAT_USUARIOS

Instalado con pip, también funciona como comando: `merchbot web`.
"""
from __future__ import annotations

import argparse
import logging
import sys

from merchbot.config import settings


def _cabecera(interfaz: str) -> None:
    print(f"[merchbot] Interfaz: {interfaz}")
    print(f"[merchbot] Entorno: {settings.app_env}")
    print(f"[merchbot] Modelo Gemini: {settings.gemini_model}")
    print(f"[merchbot] Base de datos: {settings.database_url}")
    print(f"[merchbot] Fuente de datos: {settings.fuente_de_datos}")


def _web(args: argparse.Namespace) -> int:
    from merchbot.interfaces.web.app import run

    _cabecera("web")
    host = args.host or settings.web_host
    port = args.port or settings.web_port
    print(f"[merchbot] Abrí http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}\n")
    run(host=host, port=port)
    return 0


def _telegram(_: argparse.Namespace) -> int:
    from merchbot.data.database import init_db
    from merchbot.data.scheduler import start_scheduler, stop_scheduler
    from merchbot.interfaces.telegram.bot import run as run_telegram_bot

    _cabecera("telegram")
    init_db()
    start_scheduler()
    from merchbot.core.rag import indexar_sin_fallar

    indexar_sin_fallar()
    try:
        run_telegram_bot()
    finally:
        logging.getLogger(__name__).info("Cerrando scheduler...")
        stop_scheduler()
    return 0


def _cargar_demo(_: argparse.Namespace) -> int:
    from merchbot.data.database import init_db
    from merchbot.data.demo_seed import cargar_datos_demo

    init_db()
    resultado = cargar_datos_demo()
    print(resultado.resumen())
    return 0 if resultado.ok else 1


def _indexar(_: argparse.Namespace) -> int:
    from merchbot.core.rag import indexar
    from merchbot.data.database import init_db

    init_db()
    resultado = indexar()
    print(resultado.resumen())
    return 1 if resultado.fragmentos == 0 else 0


def _diagnostico(_: argparse.Namespace) -> int:
    """Prueba la conexión con Gemini y sugiere qué cambiar si algo falla."""
    from merchbot.core.errores import describir_error

    print(f"Modelo de chat configurado: {settings.gemini_model}")
    print(f"Modelo de embeddings:       {settings.embedding_model}\n")
    if not settings.gemini_api_key or settings.gemini_api_key.startswith("tu_"):
        print("[X] Falta GEMINI_API_KEY en el .env (o sigue el valor de ejemplo).")
        return 1
    from google import genai

    cliente = genai.Client(api_key=settings.gemini_api_key)
    ok = True
    try:
        modelos = [m for m in cliente.models.list()
                   if "generateContent" in (getattr(m, "supported_actions", None) or [])]
        nombres = sorted(m.name.replace("models/", "") for m in modelos)
        print(f"[OK] La API key funciona. Modelos de chat disponibles ({len(nombres)}):")
        for n in nombres:
            if "flash" in n or "pro" in n:
                print(f"     - {n}")
        if settings.gemini_model not in nombres:
            print(f"\n[!]  '{settings.gemini_model}' no aparece en la lista: elegí uno de arriba y ponelo en GEMINI_MODEL.")
    except Exception as e:  # noqa: BLE001
        print(f"[X] No pude listar modelos: {describir_error(e).mensaje}\n    Detalle: {e}")
        return 1
    try:
        r = cliente.models.generate_content(model=settings.gemini_model, contents="Respondé solo: OK")
        print(f"\n[OK] El modelo de chat responde: {(r.text or '').strip()[:40]}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"\n[X] El modelo de chat falla: {describir_error(e).mensaje}\n    Detalle: {e}")
    try:
        cliente.models.embed_content(model=settings.embedding_model, contents=["prueba"])
        print("[OK] Los embeddings funcionan (RAG semántico).")
    except Exception as e:  # noqa: BLE001
        print(f"[!]  Los embeddings fallan, el RAG va a usar BM25: {describir_error(e).mensaje}\n    Detalle: {e}")
    return 0 if ok else 1


def _hashear(_: argparse.Namespace) -> int:
    import getpass

    from merchbot.security.auth import hashear_clave

    clave = getpass.getpass("Clave (no se muestra): ")
    if len(clave) < 10:
        print("Usá al menos 10 caracteres.")
        return 1
    if getpass.getpass("Repetila: ") != clave:
        print("No coinciden.")
        return 1
    print("\nAgregá esto en CHAT_USUARIOS del .env (reemplazá 'usuario'):")
    print(f"usuario:{hashear_clave(clave)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merchbot",
        description="Asistente conversacional de stock para merchandising.",
    )
    sub = parser.add_subparsers(dest="comando")

    web = sub.add_parser("web", help="interfaz web (por defecto)")
    web.add_argument("--host", help=f"por defecto {settings.web_host}")
    web.add_argument("--port", type=int, help=f"por defecto {settings.web_port}")
    web.set_defaults(func=_web)

    tg = sub.add_parser("telegram", help="bot de Telegram")
    tg.set_defaults(func=_telegram)

    demo = sub.add_parser("cargar-demo", help="carga la planilla de ejemplo en la base")
    demo.set_defaults(func=_cargar_demo)

    rag = sub.add_parser("indexar-politicas", help="indexa data/politicas.md para el RAG")
    rag.set_defaults(func=_indexar)

    diag = sub.add_parser("diagnostico", help="prueba la API key, el modelo y los embeddings")
    diag.set_defaults(func=_diagnostico)

    hashear = sub.add_parser("hashear-clave", help="genera el hash de una clave para CHAT_USUARIOS")
    hashear.set_defaults(func=_hashear)

    return parser


def _consola_utf8() -> None:
    """La consola de Windows usa cp1252 por defecto: sin esto, cualquier log con
    tildes raras, flechas o emojis tira 'UnicodeEncodeError' / 'Logging error'."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _consola_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.comando is None:  # sin subcomando → web
        args = parser.parse_args(["web", *(argv or [])])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
