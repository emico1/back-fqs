"""
Respuestas de error. Todas tienen la misma forma, la que ya entiende la app Android.

    {"error": {"codigo": "...", "mensaje": "...", "detalles": ...}, "requestId": "..."}

Los errores de validación de Pydantic se traducen al español y se responden con 400 y la lista
de campos con problema. Un parámetro de ruta que no es UUID responde 404 sin tocar la base.
"""

from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..errores import HttpError, traducir_error_pg
from ..jsonfmt import RespuestaJson
from ..limites import segundos_para_reintentar
from ..log import log

_MENSAJES = {
    "missing": "Requerido",
    "extra_forbidden": "Campo no permitido",
    "string_type": "Debe ser texto",
    "int_type": "Debe ser un número entero",
    "int_parsing": "Debe ser un número entero",
    "int_from_float": "Debe ser un número entero",
    "float_type": "Debe ser un número",
    "float_parsing": "Debe ser un número",
    "bool_type": "Debe ser verdadero o falso",
    "bool_parsing": "Debe ser verdadero o falso",
    "list_type": "Debe ser una lista",
    "dict_type": "Debe ser un objeto",
    "model_type": "Debe ser un objeto",
    "model_attributes_type": "Debe ser un objeto",
    "string_pattern_mismatch": "Formato inválido",
    "literal_error": "Opción inválida",
    "enum": "Opción inválida",
    "finite_number": "Debe ser un número",
}


def _mensaje(e: dict[str, Any]) -> str:
    tipo = e.get("type", "")
    ctx = e.get("ctx") or {}
    if tipo == "value_error":
        err = ctx.get("error")
        return str(err) if err else "Valor inválido"
    if tipo == "string_too_short":
        return f"Debe tener al menos {ctx.get('min_length')} caracteres"
    if tipo == "string_too_long":
        return f"Debe tener como máximo {ctx.get('max_length')} caracteres"
    # Con un texto, too_short y too_long cuentan caracteres, con una lista cuentan elementos
    unidad = "caracteres" if isinstance(e.get("input"), str) else "elementos"
    if tipo == "too_short":
        return f"Debe tener al menos {ctx.get('min_length')} {unidad}"
    if tipo == "too_long":
        return f"Debe tener como máximo {ctx.get('max_length')} {unidad}"
    if tipo in ("greater_than_equal", "greater_than"):
        return f"Debe ser mayor{' o igual' if tipo.endswith('equal') else ''} a {ctx.get('ge', ctx.get('gt'))}"
    if tipo in ("less_than_equal", "less_than"):
        return f"Debe ser menor{' o igual' if tipo.endswith('equal') else ''} a {ctx.get('le', ctx.get('lt'))}"
    if tipo == "literal_error" and ctx.get("expected"):
        return f"Opción inválida, se esperaba {str(ctx['expected']).replace(' or ', ' o ')}"
    return _MENSAJES.get(tipo, "Valor inválido")


def respuesta_error(request: Request, status: int, codigo: str, mensaje: str, detalles: Any = None) -> RespuestaJson:
    error: dict[str, Any] = {"codigo": codigo, "mensaje": mensaje}
    if detalles is not None:
        error["detalles"] = detalles
    encabezados = {}
    if status == 429 and isinstance(detalles, dict) and detalles.get("reintentarEnSegundos"):
        encabezados["Retry-After"] = str(detalles["reintentarEnSegundos"])
    return RespuestaJson({"error": error, "requestId": getattr(request.state, "request_id", None)}, status_code=status, headers=encabezados)


def instalar(app: FastAPI) -> None:
    @app.exception_handler(HttpError)
    async def _http_error(request: Request, e: HttpError) -> RespuestaJson:
        return respuesta_error(request, e.status, e.codigo, e.mensaje, e.detalles)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, e: RequestValidationError) -> RespuestaJson:
        errores = e.errors()
        if any(err.get("loc", [None])[0] == "path" for err in errores):
            return respuesta_error(request, 404, "no_encontrado", "Recurso no encontrado")
        if any(err.get("type") == "json_invalid" for err in errores):
            return respuesta_error(request, 400, "json_invalido", "El cuerpo no es JSON válido")
        detalles = []
        for err in errores:
            loc = [str(x) for x in err.get("loc", [])]
            if loc and loc[0] in ("body", "query"):
                loc = loc[1:]
            detalles.append({"campo": ".".join(loc), "mensaje": _mensaje(err)})
        return respuesta_error(request, 400, "validacion", "Revisa los datos enviados", detalles)

    @app.exception_handler(RateLimitExceeded)
    async def _limite(request: Request, e: RateLimitExceeded) -> RespuestaJson:
        return respuesta_error(
            request, 429, "demasiadas_solicitudes", "Demasiados intentos, espera un momento", {"reintentarEnSegundos": segundos_para_reintentar(request)}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _starlette(request: Request, e: StarletteHTTPException) -> RespuestaJson:
        if e.status_code == 404:
            return respuesta_error(request, 404, "no_encontrado", "Ruta no encontrada")
        if e.status_code == 405:
            return respuesta_error(request, 405, "metodo_no_permitido", "Método no permitido")
        if e.status_code == 413:
            return respuesta_error(request, 413, "demasiado_grande", "El contenido excede el tamaño permitido")
        if e.status_code == 400:
            return respuesta_error(request, 400, "json_invalido", "El cuerpo no es JSON válido")
        return respuesta_error(request, e.status_code, "error", str(e.detail))

    @app.exception_handler(psycopg.Error)
    async def _pg(request: Request, e: psycopg.Error) -> RespuestaJson:
        traducido = traducir_error_pg(e)
        if traducido:
            return respuesta_error(request, traducido.status, traducido.codigo, traducido.mensaje)
        log.error("Error de base de datos no controlado", {"requestId": getattr(request.state, "request_id", None), "error": str(e)})
        return respuesta_error(request, 500, "interno", "Ocurrió un error inesperado")
