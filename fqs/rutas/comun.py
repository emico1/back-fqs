"""Piezas compartidas por todos los módulos de rutas."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Request
from fastapi.responses import Response
from pydantic import AfterValidator

from ..http.ruta import RutaFqs
from ..jsonfmt import RespuestaJson
from ..validacion import UUID_RE

# Todos los parámetros de ruta de esta API son UUID. Se validan antes de llegar al código de
# la ruta, así un valor con otro formato (por ejemplo 1' OR 1=1) nunca llega a la base.
IdRuta = Annotated[str, Path(pattern=UUID_RE.pattern), AfterValidator(str.lower)]

# Clave para reintentar una escritura sin duplicarla (ver fqs/idempotencia.py)
ClaveIdempotencia = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        pattern=r"^[A-Za-z0-9_-]{16,64}$",
        description="Opcional. Clave aleatoria de 16 a 64 caracteres. Al repetir la petición con la misma clave se devuelve la respuesta original sin crear un duplicado",
    ),
]


def nuevo_router(etiqueta: str) -> APIRouter:
    return APIRouter(route_class=RutaFqs, tags=[etiqueta], default_response_class=RespuestaJson)


def ok(datos: Any) -> RespuestaJson:
    return RespuestaJson(datos, status_code=200)


def creado(datos: Any) -> RespuestaJson:
    return RespuestaJson(datos, status_code=201)


def aceptado(datos: Any = None) -> RespuestaJson:
    return RespuestaJson(datos if datos is not None else {"ok": True}, status_code=202)


def sin_contenido() -> Response:
    return Response(status_code=204)


def ip(request: Request) -> str:
    return request.state.ip


def rid(request: Request) -> str:
    return request.state.request_id


def solo_parametros(*permitidos: str):  # noqa: ANN201
    """
    Dependencia que rechaza parámetros de consulta no declarados, igual que los cuerpos JSON.
    Así un filtro mal escrito no se ignora en silencio.
    """
    from fastapi import Depends

    from ..validacion import error_validacion

    def revisar(request: Request) -> None:
        for nombre in request.query_params.keys():
            if nombre not in permitidos:
                raise error_validacion(nombre, "Parámetro no permitido")

    return Depends(revisar)
