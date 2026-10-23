"""
Llamadas HTTP salientes (Brevo, Firebase, Pwned Passwords) con la biblioteca estándar, sin
dependencias. Corren en un hilo aparte para no detener las demás peticiones.

Las pruebas reemplazan esta función por una falsa con la misma firma.
"""

import asyncio
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class RespuestaHttp:
    status: int
    texto: str


Http = Callable[[str, str, dict[str, str], bytes | None, float], Awaitable[RespuestaHttp]]


def _llamar(metodo: str, url: str, encabezados: dict[str, str], cuerpo: bytes | None, tiempo: float) -> RespuestaHttp:
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers=encabezados)
    try:
        with urllib.request.urlopen(req, timeout=tiempo) as r:
            return RespuestaHttp(r.status, r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return RespuestaHttp(e.code, e.read().decode("utf-8", "replace") if e.fp else "")


async def http_real(metodo: str, url: str, encabezados: dict[str, str], cuerpo: bytes | None, tiempo: float) -> RespuestaHttp:
    return await asyncio.to_thread(_llamar, metodo, url, encabezados, cuerpo, tiempo)
