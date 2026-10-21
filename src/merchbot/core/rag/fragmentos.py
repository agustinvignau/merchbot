"""División del documento de políticas en fragmentos recuperables.

Cada sección `## Título` es un fragmento. Si una sección es muy larga se parte
por párrafos, y cada parte conserva el título para no perder el contexto.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_CARACTERES = 900


@dataclass(frozen=True)
class FragmentoTexto:
    seccion: str
    orden: int
    texto: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(f"{self.seccion}\n{self.texto}".encode()).hexdigest()

    @property
    def para_embedding(self) -> str:
        """El título va adelante: ayuda a que el vector represente de qué trata."""
        return f"{self.seccion}\n{self.texto}"


def fragmentar(markdown: str, max_caracteres: int = MAX_CARACTERES) -> list[FragmentoTexto]:
    """Divide por secciones `##`. Lo anterior a la primera sección (título y aclaraciones) se ignora."""
    partes = re.split(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    fragmentos: list[FragmentoTexto] = []
    orden = 0
    # partes = [preambulo, titulo1, cuerpo1, titulo2, cuerpo2, ...]
    for titulo, cuerpo in zip(partes[1::2], partes[2::2]):
        cuerpo = cuerpo.strip()
        if not cuerpo:
            continue
        for bloque in _partir(cuerpo, max_caracteres):
            fragmentos.append(FragmentoTexto(seccion=titulo.strip(), orden=orden, texto=bloque))
            orden += 1
    return fragmentos


def _partir(texto: str, maximo: int) -> list[str]:
    if len(texto) <= maximo:
        return [texto]
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    bloques, actual = [], ""
    for p in parrafos:
        if actual and len(actual) + len(p) + 2 > maximo:
            bloques.append(actual)
            actual = p
        else:
            actual = f"{actual}\n\n{p}" if actual else p
    if actual:
        bloques.append(actual)
    return bloques
