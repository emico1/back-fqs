"""
Sesión del panel web de administración.

Usa exactamente el mismo inicio de sesión que la app (límites, bitácora, segundo factor), la
diferencia es que los tokens nunca llegan al JavaScript de la página, van en cookies HttpOnly.
Solo las cuentas de administración pueden abrir el panel.
"""

from typing import Annotated, Any

from fastapi import Request
from fastapi.responses import Response
from pydantic import Field

from ..errores import HttpError, no_autenticado
from ..http.cookies import cookies_borrar, cookies_sesion, leer_cookies, nombres_cookies
from ..http.dependencias import Admin, Svc
from ..http.manejo_errores import respuesta_error
from ..jsonfmt import RespuestaJson
from ..limites import LOGIN, REFRESH, limiter
from ..seguridad.acceso import abrir_sesion, agente_de, canjear_desafio, verificar_credenciales
from ..seguridad.bitacora import registrar_evento
from ..seguridad.sesiones import duraciones_de, revocar_familia, revocar_por_refresh, rotar_sesion
from ..servicios import Servicios
from ..validacion import Modelo, Texto
from .comun import ip, nuevo_router, ok, rid
from .consultas import perfil_completo

router = nuevo_router("panel")


class LoginPanel(Modelo):
    identificador: Texto(3, 254)
    password: Annotated[str, Field(min_length=1, max_length=200)]


class SegundoPasoPanel(Modelo):
    desafio: Annotated[str, Field(max_length=120)]
    codigo: Texto(6, 12)


def _con_cookies(respuesta: Response, cookies: list[str]) -> Response:
    for c in cookies:
        respuesta.headers.append("set-cookie", c)
    return respuesta


async def _estado_panel(s: Servicios, usuario_id: str, segundo_factor: bool) -> dict[str, Any]:
    return {
        "usuario": await perfil_completo(s.db, usuario_id),
        "sesionConSegundoFactor": segundo_factor,
        "segundoFactor": {**(await s.segundo_factor.estado(usuario_id)), "obligatorio": s.config.ADMIN_2FA == "obligatorio"},
    }


def _refresh_de(request: Request, s: Servicios) -> str | None:
    return leer_cookies(request).get(nombres_cookies(s.config.produccion).renovacion)


@router.post("/v1/panel/sesion", summary="Iniciar sesión en el panel")
@limiter.shared_limit(LOGIN, scope="login")
async def entrar(request: Request, d: LoginPanel, s: Svc):
    cuenta = await verificar_credenciales(s, request, d.identificador, d.password)
    if cuenta.rol != "admin":
        # Mismo trato que un acceso denegado, queda en la bitácora
        await registrar_evento(
            s.db,
            "acceso_denegado",
            actor_id=cuenta.id,
            actor_rol=cuenta.rol,
            ruta="POST /v1/panel/sesion",
            ip=ip(request),
            request_id=rid(request),
        )
        raise HttpError(403, "solo_admin", "El panel es solo para cuentas de administración. Las familias usan la app")
    r = await abrir_sesion(s, request, cuenta)
    if r["tipo"] == "desafio":
        return ok({"requiere2fa": True, "desafio": r["desafio"], "desafioExpiraEn": r["expiraEn"]})
    nombres = nombres_cookies(s.config.produccion)
    return _con_cookies(ok(await _estado_panel(s, r["usuarioId"], False)), cookies_sesion(nombres, r["tokens"]))


@router.post("/v1/panel/sesion/2fa", summary="Segundo paso del inicio de sesión del panel")
@limiter.shared_limit(LOGIN, scope="login")
async def segundo_paso(request: Request, d: SegundoPasoPanel, s: Svc):
    r = await canjear_desafio(s, request, d.desafio, d.codigo)
    nombres = nombres_cookies(s.config.produccion)
    return _con_cookies(ok(await _estado_panel(s, r["usuarioId"], True)), cookies_sesion(nombres, r["tokens"]))


# La cookie de renovación solo viaja a /v1/panel/sesion y lo que cuelga de ahí
@router.post("/v1/panel/sesion/renovar", summary="Renovar la sesión del panel")
@limiter.shared_limit(REFRESH, scope="refresh")
async def renovar(request: Request, s: Svc):
    refresh = _refresh_de(request, s)
    if not refresh:
        raise no_autenticado()
    nombres = nombres_cookies(s.config.produccion)
    try:
        tokens = await rotar_sesion(s.db, refresh, duraciones_de(s.config), agente_de(request), ip(request))
    except HttpError as e:
        # Si la sesión ya no sirve se borran las cookies para que el panel vuelva al inicio
        if e.status == 401:
            return _con_cookies(respuesta_error(request, 401, e.codigo, e.mensaje), cookies_borrar(nombres))
        raise
    return _con_cookies(Response(status_code=204), cookies_sesion(nombres, tokens))


@router.post("/v1/panel/sesion/salir", summary="Cerrar la sesión del panel")
async def salir(request: Request, s: Svc):
    refresh = _refresh_de(request, s)
    usuario = getattr(request.state, "usuario", None)
    if refresh:
        await revocar_por_refresh(s.db, refresh)
    elif usuario:
        await revocar_familia(s.db, usuario.familia_id, usuario.id)
    return _con_cookies(Response(status_code=204), cookies_borrar(nombres_cookies(s.config.produccion)))


# Funciona sin segundo factor, así el panel puede llevar a activarlo
@router.get("/v1/panel/sesion", summary="Estado de la sesión del panel")
async def estado(s: Svc, u: Admin) -> RespuestaJson:
    return ok(await _estado_panel(s, u.id, u.segundo_factor))
