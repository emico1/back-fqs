"""
Métricas para Prometheus.

Se publican en un puerto aparte (METRICAS_PUERTO), nunca en el puerto de la API, así que Caddy
y el túnel no las exponen. En Docker ese puerto solo escucha en la red de monitoreo, donde
únicamente está Prometheus.

Las etiquetas tienen valores acotados. La ruta es la plantilla (/v1/actividades/{id}), nunca
la dirección real, y una ruta que no existe se cuenta como "desconocida". No hay ids de
usuario, IPs, correos ni tokens en ninguna métrica.
"""

import threading
from typing import Callable
from wsgiref.simple_server import WSGIRequestHandler, make_server

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    disable_created_metrics,
    make_wsgi_app,
)
from prometheus_client.exposition import ThreadingWSGIServer
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector

from . import __version__

# Sin las series *_created, que Prometheus no necesita y duplican cada contador
disable_created_metrics()

# Registro propio, así las pruebas pueden armar varias apps sin chocar con el registro global
REGISTRO = CollectorRegistry(auto_describe=True)
ProcessCollector(registry=REGISTRO)
PlatformCollector(registry=REGISTRO)
GCCollector(registry=REGISTRO)

INFO = Info("fqs", "Versión y entorno de la API", registry=REGISTRO)

PETICIONES = Counter(
    "fqs_peticiones",
    "Peticiones atendidas por ruta, método y código de respuesta",
    ["ruta", "metodo", "status"],
    registry=REGISTRO,
)

DURACION = Histogram(
    "fqs_peticion_duracion_segundos",
    "Tiempo de respuesta por ruta y método",
    ["ruta", "metodo"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRO,
)

EN_CURSO = Gauge("fqs_peticiones_en_curso", "Peticiones que se están atendiendo en este momento", registry=REGISTRO)

LIMITES = Counter(
    "fqs_limite_excedido",
    "Respuestas 429 por ruta (límites de slowapi, por cuenta y de conexiones en tiempo real)",
    ["ruta"],
    registry=REGISTRO,
)

INICIOS_SESION = Counter(
    "fqs_inicios_sesion",
    "Resultados del inicio de sesión de la app y del panel",
    ["resultado"],
    registry=REGISTRO,
)

EVENTOS_SEGURIDAD = Counter(
    "fqs_eventos_seguridad",
    "Eventos escritos en la bitácora de seguridad por acción",
    ["accion"],
    registry=REGISTRO,
)

ERRORES_BITACORA = Counter(
    "fqs_bitacora_errores",
    "Eventos de seguridad que no se pudieron escribir en la bitácora",
    registry=REGISTRO,
)

FLUJOS = Gauge("fqs_flujos_tiempo_real", "Conexiones abiertas de cupos en tiempo real", registry=REGISTRO)

RESULTADOS_LOGIN = {
    "correcto",
    "desafio_2fa",
    "credenciales",
    "cuenta_bloqueada",
    "suspendida",
    "en_eliminacion",
    "2fa_correcto",
    "2fa_fallido",
    "2fa_bloqueado",
    "2fa_expirado",
}

# Acciones que escribe la API en la bitácora de seguridad
ACCIONES_SEGURIDAD = (
    "2fa_activado",
    "2fa_codigo_respaldo_usado",
    "2fa_codigos_regenerados",
    "2fa_correcto",
    "2fa_desafio",
    "2fa_fallido",
    "2fa_iniciado",
    "2fa_reiniciado",
    "acceso_denegado",
    "admin_accion",
    "clave_2fa_rotada",
    "contrasena_cambiada",
    "contrasena_restablecida",
    "correo_cambiado",
    "login_admin",
    "login_admin_fallido",
    "recuperacion_solicitada",
    "refresh_reutilizado",
    "requiere_2fa",
    "sesion_cerrada_remota",
    "telefono_cambiado",
)


def iniciar(entorno: str, rutas: list[str]) -> None:
    """
    Publica la versión y crea en cero las series que usan las alertas. Sin esto, la primera vez
    que pasa algo la serie aparece ya con valor y increase() no la cuenta.
    """
    INFO.info({"version": __version__, "entorno": entorno})
    for r in RESULTADOS_LOGIN:
        INICIOS_SESION.labels(r)
    for a in ACCIONES_SEGURIDAD:
        EVENTOS_SEGURIDAD.labels(a)
    for ruta in rutas:
        LIMITES.labels(ruta)


def registrar_peticion(ruta: str, metodo: str, status: int, segundos: float) -> None:
    PETICIONES.labels(ruta, metodo, str(status)).inc()
    DURACION.labels(ruta, metodo).observe(segundos)
    if status == 429:
        LIMITES.labels(ruta).inc()


def inicio_sesion(resultado: str) -> None:
    INICIOS_SESION.labels(resultado if resultado in RESULTADOS_LOGIN else "otro").inc()


def evento_seguridad(accion: str) -> None:
    EVENTOS_SEGURIDAD.labels(accion).inc()


def vigilar_flujos(contar: Callable[[], int]) -> None:
    """El número de conexiones se lee del canal al momento de cada consulta de Prometheus."""
    FLUJOS.set_function(lambda: float(contar()))


class _SinBitacora(WSGIRequestHandler):
    """Sin una línea por consulta en la salida estándar, Prometheus consulta cada 15 segundos."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _solo_metricas(app: Callable) -> Callable:
    """Solo responde GET /metrics. Cualquier otra ruta o método es 404 o 405 sin cuerpo útil."""

    def envoltura(environ: dict, start_response: Callable):  # noqa: ANN202
        ruta = environ.get("PATH_INFO", "")
        if ruta != "/metrics":
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")])
            return [b"no encontrado\n"]
        if environ.get("REQUEST_METHOD") != "GET":
            start_response("405 Method Not Allowed", [("Allow", "GET"), ("Content-Type", "text/plain; charset=utf-8")])
            return [b"metodo no permitido\n"]
        return app(environ, start_response)

    return envoltura


class ServidorMetricas:
    def __init__(self, host: str, puerto: int) -> None:
        app = _solo_metricas(make_wsgi_app(REGISTRO))
        self._httpd = make_server(host, puerto, app, ThreadingWSGIServer, handler_class=_SinBitacora)
        self.puerto = self._httpd.server_port
        self._hilo = threading.Thread(target=self._httpd.serve_forever, name="metricas", daemon=True)

    def iniciar(self) -> "ServidorMetricas":
        self._hilo.start()
        return self

    def detener(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
