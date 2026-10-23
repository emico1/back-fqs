"""
Armado de la aplicación FastAPI.

crear_app() sin argumentos arma todos los servicios a partir de la configuración (variables de
entorno) al arrancar. Las pruebas le pasan sus propios servicios ya armados.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from . import __version__
from .almacen import Almacen
from .config import Config, cargar_config, claves_anteriores_2fa
from .correo import CorreoBitacora, CorreoBrevo
from .db import Db, verificar_migraciones, verificar_rol_seguro
from .idempotencia import purgar as purgar_idempotencia
from .http import manejo_errores
from .http.dependencias import cargar_sesion
from .http.middleware import MiddlewareFqs
from .http.panel_estatico import DIRECTORIO_PANEL, cargar_panel, rutas_panel
from .jsonfmt import RespuestaJson
from . import metricas
from .limites import limiter
from .log import log, nivel_log
from .push import Push, cargar_cuenta_servicio
from .rutas import (
    admin,
    admin_listas,
    archivos,
    auth,
    catalogo,
    comunidad,
    panel,
    participacion,
    perfil,
    proyectos,
    seguridad,
    social,
    tiempo_real,
)
from .seguridad.filtradas import RevisorFiltradas
from .seguridad.segundo_factor import SegundoFactor
from .seguridad.sesiones import purgar_sesiones
from .seguridad.totp import CifradoSecretos
from .servicios import Servicios
from .sms import ControlSms, SmsBitacora, SmsBrevo
from .tareas import en_segundo_plano, esperar_pendientes
from .tiempo_real import CanalCupos
from .vigilancia import Vigilancia

DESCRIPCION = """
API del proyecto Familias que Suman. La consume la app Android (sesión con Bearer) y el panel
web de administración (sesión con cookies HttpOnly).

Todas las respuestas de error tienen la forma
{"error": {"codigo", "mensaje", "detalles?"}, "requestId"}.

Los límites de peticiones se declaran en cada ruta sensible (inicio de sesión, registro,
verificación, recuperación, escrituras y subidas). No hay un límite global.
"""

# Swagger UI se carga de un CDN, así que la página de documentación lleva una política propia
_CSP_DOCS = (
    "default-src 'none'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; frame-ancestors 'none'"
)


async def armar_servicios(config: Config) -> Servicios:
    """Conecta la base, revisa que esté lista y arma todos los servicios."""
    db = Db(config)
    await db.abrir()
    await db.query("SELECT 1")
    await verificar_rol_seguro(db, config.produccion)
    await verificar_migraciones(db)
    almacen = Almacen(config.UPLOAD_DIR)
    almacen.preparar()
    push = Push(db, cargar_cuenta_servicio(config.FCM_CUENTA_SERVICIO))
    if not push.activo:
        log.warn("FCM_CUENTA_SERVICIO no está configurada, las notificaciones no se mandarán como push")
    cupos = CanalCupos(db)
    metricas.vigilar_flujos(lambda: cupos.conectados)
    # Cada notificación nueva llega por este canal y se manda por push
    cupos.escuchar("fqs_notificaciones", lambda ident: en_segundo_plano(push.procesar(ident), "el envío push"))
    await cupos.iniciar()
    await push.pendientes()

    if config.BREVO_API_KEY and config.CORREO_REMITENTE:
        correo = CorreoBrevo(config.BREVO_API_KEY, config.CORREO_REMITENTE, config.CORREO_REMITENTE_NOMBRE)
    else:
        correo = CorreoBitacora(config.desarrollo)
        log.warn("BREVO_API_KEY no está configurada, los códigos de recuperación no se mandan por correo")
    cifrado = CifradoSecretos(config.CLAVE_CIFRADO_2FA, claves_anteriores_2fa(config)) if config.CLAVE_CIFRADO_2FA else None
    sms_activo = config.SMS == "brevo" and bool(config.BREVO_API_KEY)
    # En desarrollo sin proveedor el código aparece en la consola y el flujo se puede probar
    sms = ControlSms(
        db,
        SmsBrevo(config.BREVO_API_KEY or "", config.SMS_REMITENTE) if sms_activo else SmsBitacora(config.desarrollo),
        config,
        sms_activo or config.desarrollo,
    )
    if not sms_activo:
        log.warn("SMS desactivado, el registro solo con teléfono no está disponible fuera de desarrollo")
    if config.ADMIN_2FA != "obligatorio":
        log.warn("ADMIN_2FA=opcional, la administración funciona sin segundo factor")
    return Servicios(
        db=db,
        config=config,
        almacen=almacen,
        correo=correo,
        cupos=cupos,
        push=push,
        segundo_factor=SegundoFactor(db, cifrado),
        filtradas=RevisorFiltradas(config.CONTRASENAS_FILTRADAS == "revisar"),
        vigilancia=Vigilancia(db, correo, config),
        sms=sms,
    )


def _periodica(nombre: str, cada_segundos: float, fn: Callable[[], Awaitable[object]]) -> asyncio.Task:
    async def ciclo() -> None:
        while True:
            await asyncio.sleep(cada_segundos)
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warn(f"Falló la tarea {nombre}", {"error": str(e)})

    return asyncio.create_task(ciclo())


def _tareas_periodicas(s: Servicios) -> list[asyncio.Task]:
    async def avisos() -> None:
        # Recordatorios de actividades e invitaciones a encuestas (RF16, RF-13)
        await s.db.query("SELECT generar_avisos() AS n")
        await s.push.pendientes()

    async def horaria() -> None:
        await s.vigilancia.anclar()
        await s.vigilancia.revisar_inactivas()

    async def limpieza() -> None:
        await purgar_sesiones(s.db)
        await s.sms.purgar()
        await purgar_idempotencia(s.db)

    return [
        _periodica("avisos", s.config.AVISOS_CADA_MINUTOS * 60, avisos),
        # Alertas de la bitácora cada minuto, ancla y cuentas inactivas cada hora
        _periodica("alertas", 60, s.vigilancia.revisar_bitacora),
        _periodica("ancla e inactividad", 60 * 60, horaria),
        _periodica("limpieza", 6 * 60 * 60, limpieza),
    ]


def crear_app(
    servicios: Servicios | None = None,
    config: Config | None = None,
    fabrica: Callable[[Config], Awaitable[Servicios]] | None = None,
) -> FastAPI:
    """
    Sin argumentos arma los servicios al arrancar a partir de la configuración y corre las
    tareas periódicas. Las pruebas pasan sus propios servicios, o una fabrica que los arma
    dentro del ciclo de eventos del servidor, y en ese caso no hay tareas periódicas.
    """
    cfg = servicios.config if servicios else (config or cargar_config())
    panel_dir = servicios.panel_dir if servicios else None
    nivel_log(cfg.LOG_LEVEL)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        propios = app.state.servicios is None
        tareas: list[asyncio.Task] = []
        if propios:
            app.state.servicios = await (fabrica or armar_servicios)(cfg)
            if fabrica is None:
                tareas = _tareas_periodicas(app.state.servicios)
            log.info("API de Familias que Suman escuchando", {"host": cfg.HOST, "puerto": cfg.PORT, "entorno": cfg.ENTORNO})
        try:
            yield
        finally:
            if propios:
                log.info("Apagando")
                for t in tareas:
                    t.cancel()
                s: Servicios = app.state.servicios
                # Los flujos en tiempo real se cierran primero, si no el apagado esperaría para siempre
                await s.cupos.detener()
                await esperar_pendientes()
                await s.db.cerrar()

    desarrollo = cfg.desarrollo
    app = FastAPI(
        title="Familias que Suman",
        version=__version__,
        description=DESCRIPCION,
        lifespan=ciclo_de_vida,
        default_response_class=RespuestaJson,
        # La documentación interactiva solo existe en desarrollo
        openapi_url="/openapi.json" if desarrollo else None,
        docs_url=None,
        redoc_url=None,
        dependencies=[Depends(cargar_sesion)],
        # Una ruta con diagonal al final no existe y no se redirige
        redirect_slashes=False,
    )
    app.state.servicios = servicios
    app.state.limiter = limiter

    for modulo in (
        catalogo,
        auth,
        perfil,
        comunidad,
        participacion,
        proyectos,
        tiempo_real,
        social,
        archivos,
        admin,
        seguridad,
        admin_listas,
        panel,
    ):
        app.include_router(modulo.router)

    if desarrollo:

        @app.get("/docs", include_in_schema=False)
        async def documentacion() -> HTMLResponse:
            r = get_swagger_ui_html(openapi_url="/openapi.json", title="Familias que Suman")
            r.headers["Content-Security-Policy"] = _CSP_DOCS
            return r

    carpeta = Path(panel_dir) if panel_dir else DIRECTORIO_PANEL
    app.router.routes.extend(rutas_panel(cargar_panel(carpeta)))

    metricas.iniciar(cfg.ENTORNO, sorted({r.path for r in app.routes if getattr(r, "path", "").startswith("/v1/")}))

    manejo_errores.instalar(app)
    app.add_middleware(MiddlewareFqs, trust_proxy=cfg.TRUST_PROXY, produccion=cfg.produccion)
    return app
