"""
Clase de ruta propia. Además de lo que hace FastAPI, deja en la bitácora de seguridad toda
acción de administración que cambia algo. Se guarda el método, la ruta y los ids, nunca el
cuerpo (puede traer datos personales).
"""

import json
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.routing import APIRoute

from ..seguridad.bitacora import registrar_evento


def _extraer_id(cuerpo: bytes) -> str | None:
    """Id del recurso creado, cuando la respuesta lo trae, para que la bitácora diga qué se creó."""
    try:
        datos = json.loads(cuerpo)
    except (ValueError, TypeError):
        return None
    if isinstance(datos, dict) and isinstance(datos.get("id"), str):
        return datos["id"]
    return None


class RutaFqs(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Any]:
        original = super().get_route_handler()

        async def manejador(request: Request) -> Response:
            respuesta: Response = await original(request)
            if (
                getattr(request.state, "acceso", None) == "admin"
                and request.method != "GET"
                and respuesta.status_code < 400
                and getattr(request.state, "usuario", None)
            ):
                usuario = request.state.usuario
                params = dict(request.path_params)
                entidad = next(iter(params.values()), None) or _extraer_id(getattr(respuesta, "body", b"") or b"")
                await registrar_evento(
                    request.app.state.servicios.db,
                    "admin_accion",
                    actor_id=usuario.id,
                    actor_rol=usuario.rol,
                    ruta=f"{request.method} {self.path}",
                    entidad_id=entidad,
                    detalles={"params": params, "status": respuesta.status_code},
                    ip=request.state.ip,
                    request_id=request.state.request_id,
                )
            return respuesta

        return manejador
