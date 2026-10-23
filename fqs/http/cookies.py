"""
Cookies del panel web de administración.

El panel no guarda tokens en localStorage (cualquier script inyectado podría leerlos). Los
tokens viajan en cookies HttpOnly, Secure y SameSite=Strict.

En producción se usan los prefijos del navegador.
  __Host- obliga a Secure, Path=/ y prohíbe Domain, así un subdominio no puede plantar ni
  pisar la cookie de acceso.
  __Secure- obliga a Secure. La cookie de renovación lleva Path limitado a la ruta de
  renovación y salida, así no viaja en ninguna otra petición.

En desarrollo (http://localhost) los prefijos y Secure no funcionan, se usan nombres simples.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from starlette.requests import Request

from ..errores import HttpError

RUTA_RENOVACION = "/v1/panel/sesion"


@dataclass(frozen=True)
class NombresCookies:
    acceso: str
    renovacion: str
    seguras: bool


def nombres_cookies(produccion: bool) -> NombresCookies:
    if produccion:
        return NombresCookies("__Host-fqs_panel", "__Secure-fqs_panel_r", True)
    return NombresCookies("fqs_panel", "fqs_panel_r", False)


_VALOR = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def leer_cookies(request: Request) -> dict[str, str]:
    """Lee las cookies de la petición. Ignora nombres repetidos (se queda con la primera)."""
    r: dict[str, str] = {}
    for parte in request.headers.get("cookie", "").split(";"):
        i = parte.find("=")
        if i <= 0:
            continue
        nombre = parte[:i].strip()
        valor = parte[i + 1 :].strip()
        # Los tokens de la API solo usan letras, números, guion y guion bajo
        if nombre not in r and _VALOR.match(valor):
            r[nombre] = valor
    return r


def _serializar(nombre: str, valor: str, ruta: str, segundos: float, seguras: bool) -> str:
    partes = [f"{nombre}={valor}", f"Path={ruta}", f"Max-Age={max(0, int(segundos))}", "HttpOnly", "SameSite=Strict"]
    if seguras:
        partes.append("Secure")
    return "; ".join(partes)


def _segundos_hasta(iso: str) -> float:
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()


def cookies_sesion(n: NombresCookies, tokens: dict[str, str]) -> list[str]:
    """Set-Cookie para guardar los tokens de una sesión del panel."""
    return [
        _serializar(n.acceso, tokens["accessToken"], "/", _segundos_hasta(tokens["accessExpiraEn"]), n.seguras),
        _serializar(n.renovacion, tokens["refreshToken"], RUTA_RENOVACION, _segundos_hasta(tokens["refreshExpiraEn"]), n.seguras),
    ]


def cookies_borrar(n: NombresCookies) -> list[str]:
    """Set-Cookie que borra las dos cookies."""
    return [_serializar(n.acceso, "", "/", 0, n.seguras), _serializar(n.renovacion, "", RUTA_RENOVACION, 0, n.seguras)]


def exigir_mismo_origen(request: Request) -> None:
    """
    Defensa contra CSRF para toda petición que llega autenticada con cookie y cambia algo.
    Son tres capas independientes.
      1. SameSite=Strict, el navegador no manda la cookie desde otro sitio.
      2. El encabezado X-FQS-Panel. Un formulario de otro sitio no puede ponerlo, y si lo
         pone un script de otro origen el navegador primero hace una consulta CORS que esta
         API no autoriza.
      3. El encabezado Origin, si viene, tiene que ser el mismo host al que se habla.
    """
    if request.headers.get("x-fqs-panel") != "1":
        raise HttpError(403, "csrf", "Petición rechazada, falta el encabezado del panel")
    origen = request.headers.get("origin")
    if origen is not None:
        try:
            partes = urlsplit(origen)
            host = partes.netloc if partes.scheme in ("http", "https") else None
        except ValueError:
            host = None
        # Caddy conserva el Host original al pasar la petición, no hace falta X-Forwarded-Host
        if not host or host != request.headers.get("host"):
            raise HttpError(403, "csrf", "Petición rechazada, el origen no coincide")
