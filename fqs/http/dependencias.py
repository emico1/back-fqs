"""
Dependencias de FastAPI para la autenticación.

Cada ruta declara su nivel de acceso con una de estas dependencias, y FastAPI las resuelve
antes de ejecutar el código de la ruta.
  usuario_actual  cualquier cuenta con sesión
  admin_actual    cuenta de administración (y con segundo factor si es obligatorio)

La sesión llega como Authorization Bearer (la app) o como cookie HttpOnly (el panel web).
Toda petición con cookie que cambie algo tiene que demostrar que viene del propio panel
(defensa contra CSRF).
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie, HTTPBearer

from ..errores import HttpError, no_autenticado, prohibido
from ..seguridad.bitacora import registrar_evento
from ..seguridad.sesiones import UsuarioSesion, autenticar
from ..servicios import Servicios
from .cookies import exigir_mismo_origen, leer_cookies, nombres_cookies

# Rutas de administración que funcionan sin segundo factor, son las que sirven para activarlo
RUTAS_ACTIVAR_2FA = {"/v1/admin/2fa", "/v1/admin/2fa/iniciar", "/v1/admin/2fa/confirmar", "/v1/panel/sesion"}


# Solo describen en OpenAPI cómo se manda la sesión. La lectura real está en cargar_sesion
_bearer = HTTPBearer(auto_error=False, scheme_name="bearer", description="Token opaco fqs_at_ de la app")
_cookie = APIKeyCookie(
    name="__Host-fqs_panel",
    auto_error=False,
    scheme_name="panelCookie",
    description="Panel web. Cookie HttpOnly (fqs_panel en desarrollo). Todo lo que no sea GET exige además X-FQS-Panel 1",
)


def servicios(request: Request) -> Servicios:
    return request.app.state.servicios


Svc = Annotated[Servicios, Depends(servicios)]


async def cargar_sesion(request: Request) -> None:
    """Se aplica a todas las rutas. Lee la sesión si la hay, no exige que exista."""
    s: Servicios = request.app.state.servicios
    usuario: UsuarioSesion | None = None
    cambia = request.method not in ("GET", "HEAD")
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        usuario = await autenticar(s.db, auth[7:].strip())
    else:
        de_cookie = leer_cookies(request).get(nombres_cookies(s.config.produccion).acceso)
        if de_cookie:
            if cambia:
                exigir_mismo_origen(request)
            usuario = await autenticar(s.db, de_cookie)
    # Las rutas de sesión del panel no llevan cookie de acceso, pero sí la de renovación
    if cambia and request.url.path.startswith("/v1/panel/"):
        exigir_mismo_origen(request)
    request.state.usuario = usuario


def _plantilla(request: Request) -> str:
    ruta = request.scope.get("route")
    return getattr(ruta, "path", request.url.path)


async def usuario_actual(request: Request, _b: object = Depends(_bearer), _c: object = Depends(_cookie)) -> UsuarioSesion:
    usuario = getattr(request.state, "usuario", None)
    if not usuario:
        raise no_autenticado()
    request.state.acceso = "usuario"
    return usuario


async def admin_actual(request: Request, _b: object = Depends(_bearer), _c: object = Depends(_cookie)) -> UsuarioSesion:
    usuario = getattr(request.state, "usuario", None)
    if not usuario:
        raise no_autenticado()
    s: Servicios = request.app.state.servicios
    plantilla = _plantilla(request)
    evento = {
        "actor_id": usuario.id,
        "actor_rol": usuario.rol,
        "ruta": f"{request.method} {plantilla}",
        "ip": request.state.ip,
        "request_id": request.state.request_id,
    }
    if usuario.rol != "admin":
        # Una familia intentando usar la administración es una señal que vale la pena guardar
        await registrar_evento(s.db, "acceso_denegado", **evento)
        raise prohibido()
    if s.config.ADMIN_2FA == "obligatorio" and not usuario.segundo_factor and plantilla not in RUTAS_ACTIVAR_2FA:
        await registrar_evento(s.db, "requiere_2fa", **evento)
        raise HttpError(
            403,
            "requiere_2fa",
            "Para usar la administración activa el segundo factor con una app de autenticación e inicia sesión con tu código",
        )
    request.state.acceso = "admin"
    return usuario


Usuario = Annotated[UsuarioSesion, Depends(usuario_actual)]
Admin = Annotated[UsuarioSesion, Depends(admin_actual)]
