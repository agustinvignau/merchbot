"""Punto de entrada de MerchBot.

Uso:
    python -m merchbot                 # interfaz web en http://127.0.0.1:8000
    python -m merchbot web --port 9000
    python -m merchbot telegram        # bot de Telegram (long-polling)
    python -m merchbot cargar-demo     # carga la planilla de ejemplo en la base
    python -m merchbot indexar-politicas  # (re)indexa data/politicas.md para el RAG

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.comando is None:  # sin subcomando → web
        args = parser.parse_args(["web", *(argv or [])])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
