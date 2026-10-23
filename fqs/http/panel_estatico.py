"""
Archivos del panel web de administración (HTML, CSS y JavaScript sin compilar).

Se leen una sola vez al arrancar y se sirven desde memoria, sin leer disco por petición. Una
ruta con ../ o codificada no puede salir de la carpeta, simplemente no está en la lista.
"""

from pathlib import Path

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from ..errores import HttpError
from ..log import log

DIRECTORIO_PANEL = Path(__file__).resolve().parent.parent.parent / "panel"

_TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

# Política estricta para el panel, solo recursos propios y nada de scripts en línea
CSP_PANEL = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


def cargar_panel(carpeta: Path) -> dict[str, tuple[bytes, str]]:
    """Lee la carpeta del panel. Si no existe, el panel simplemente no se sirve."""
    archivos: dict[str, tuple[bytes, str]] = {}
    if not carpeta.is_dir():
        log.warn("No se encontró la carpeta del panel web, /panel no estará disponible", {"dir": str(carpeta)})
        return archivos
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file() or any(p.startswith(".") for p in ruta.relative_to(carpeta).parts):
            continue
        tipo = _TIPOS.get(ruta.suffix.lower())
        if tipo:
            archivos["/panel/" + ruta.relative_to(carpeta).as_posix()] = (ruta.read_bytes(), tipo)
    return archivos


def rutas_panel(archivos: dict[str, tuple[bytes, str]]) -> list[Route]:
    async def redirigir(request: Request) -> Response:
        return RedirectResponse("/panel/", status_code=301)

    async def servir(request: Request) -> Response:
        ruta = request.url.path
        archivo = archivos.get("/panel/index.html" if ruta == "/panel/" else ruta)
        if not archivo:
            raise HttpError(404, "no_encontrado", "Ruta no encontrada")
        datos, tipo = archivo
        # Las páginas siempre se revisan contra el servidor, así una versión nueva llega de inmediato
        return Response(
            content=b"" if request.method == "HEAD" else datos,
            media_type=tipo,
            headers={"Content-Security-Policy": CSP_PANEL, "Cache-Control": "no-cache", "Content-Length": str(len(datos))},
        )

    return [
        Route("/panel", redirigir, methods=["GET", "HEAD"]),
        Route("/panel/{archivo:path}", servir, methods=["GET", "HEAD"]),
    ]
