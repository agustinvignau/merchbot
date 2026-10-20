"""Corre las conversaciones de demo del TP y guarda la transcripción.

Cada escenario es una situación cotidiana distinta, a una hora distinta del día,
para mostrar la atención 24/7. Usa el asistente real (requiere GEMINI_API_KEY)
y los datos de la planilla de demo.

Uso:
    python scripts/demo_dialogos.py                    # escribe docs/DIALOGOS_DEMO.md
    python scripts/demo_dialogos.py --salida otra.md
    python scripts/demo_dialogos.py --en-la-base       # registra en la base de la app (para verlo en /admin)

Por defecto usa una base temporal y no toca la base de la app.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Escenario:
    titulo: str
    situacion: str
    hora: str
    mensajes: tuple[str, ...]


GUION: tuple[Escenario, ...] = (
    Escenario(
        "Consulta de stock a la mañana",
        "Un vendedor necesita saber si hay talles antes de cotizar.",
        "09:30",
        ("¿Cuántas remeras negras talle M tengo?", "¿Y en talle L?"),
    ),
    Escenario(
        "Pedidos de un cliente a la tarde",
        "El dueño quiere repasar qué le vendieron a un cliente antes de una reunión.",
        "15:00",
        ("¿Qué pidió Coca-Cola?",),
    ),
    Escenario(
        "Reposición a la noche",
        "Después del cierre, el encargado arma la compra del día siguiente.",
        "22:45",
        ("¿Qué hay que comprar?",
         "Necesito 200 buzos canguro grises L para un evento, ¿me alcanza?"),
    ),
    Escenario(
        "Reclamo de madrugada",
        "Un cliente avisa de un problema fuera de horario; queda registrado para el día hábil.",
        "03:20",
        ("Me llegaron 20 remeras blancas M con manchas de tinta, son del pedido de Coca-Cola.",
         "¿Cómo va el reclamo 1?"),
    ),
    Escenario(
        "Consulta fuera de alcance",
        "Alguien pregunta algo que el asistente no maneja: debe decirlo sin inventar.",
        "13:10",
        ("¿Cuánto sale una remera dry-fit?",),
    ),
)


def correr_guion(service, guion=GUION) -> list[dict]:
    """Ejecuta cada escenario con su propia conversación. Devuelve la transcripción."""
    resultados = []
    for i, esc in enumerate(guion, start=1):
        turnos = []
        for mensaje in esc.mensajes:
            a = service.atender(f"demo-{i}", mensaje, canal="demo", hora_simulada=esc.hora)
            turnos.append({"usuario": mensaje, "bot": a.texto, "tipo": a.tipo,
                           "fuera_de_horario": a.fuera_de_horario})
        resultados.append({"escenario": esc, "turnos": turnos})
    return resultados


def a_markdown(resultados: list[dict], modelo: str) -> str:
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    partes = [
        "# Diálogos de demostración",
        "",
        f"Generado el {fecha} con `scripts/demo_dialogos.py`, modelo `{modelo}` y los datos "
        "de la planilla de demo. Las respuestas son las reales del asistente, sin editar.",
        "",
        "Cada conversación ocurre a una hora simulada distinta para mostrar la atención 24/7 "
        "(horario de atención humana: lunes a viernes de 9 a 18).",
    ]
    for r in resultados:
        esc = r["escenario"]
        partes += ["", f"## {esc.titulo} ({esc.hora} hs)", "", f"*{esc.situacion}*", ""]
        for t in r["turnos"]:
            partes.append(f"**Usuario ({esc.hora}):** {t['usuario']}")
            partes.append("")
            bot = t["bot"].replace("\n", "  \n")
            partes.append(f"**MerchBot:** {bot}")
            partes.append("")
            nota = "fuera de horario" if t["fuera_de_horario"] else "en horario"
            partes.append(f"<sub>Tipo registrado: {t['tipo']}, {nota}.</sub>")
            partes.append("")
    return "\n".join(partes).rstrip() + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salida", default=str(RAIZ / "docs" / "DIALOGOS_DEMO.md"))
    parser.add_argument("--en-la-base", action="store_true",
                        help="usar la base configurada en .env en vez de una temporal")
    args = parser.parse_args(argv)

    # Base temporal y datos de demo, antes de importar la app (lee la config al importar).
    if not args.en_la_base:
        tmp = tempfile.mkdtemp(prefix="merchbot-demo-")
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'demo.db'}"
        os.environ["DATA_SOURCE"] = "demo"
    sys.path.insert(0, str(RAIZ / "src"))

    from merchbot.config import settings
    from merchbot.core.chat_service import ChatService
    from merchbot.data.database import init_db
    from merchbot.data.demo_seed import cargar_datos_demo

    if not settings.gemini_api_key:
        print("Falta GEMINI_API_KEY en el .env: el guion usa el asistente real.")
        return 1
    init_db()
    carga = cargar_datos_demo() if not args.en_la_base else None
    if carga is not None and not carga.ok:
        print(carga.resumen())
        return 1

    resultados = correr_guion(ChatService())
    salida = Path(args.salida)
    salida.write_text(a_markdown(resultados, settings.gemini_model), encoding="utf-8")
    print(f"Listo: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
