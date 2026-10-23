"""
Arranque del servidor.  python -m fqs

Lee .env de la carpeta actual (sin pisar variables que ya existen en el entorno), valida la
configuración y levanta uvicorn en HOST y PORT. Si METRICAS_PUERTO no es 0, también abre el
servidor de métricas para Prometheus en METRICAS_HOST y ese puerto.
"""

import sys

import uvicorn

from .config import ErrorConfig, cargar_config, cargar_env
from .log import log


def main() -> None:
    cargar_env(".env")
    try:
        config = cargar_config()
    except ErrorConfig as e:
        log.error("No se pudo iniciar el servidor", {"error": str(e)})
        sys.exit(1)
    from .app import crear_app
    from .metricas import ServidorMetricas

    metricas = None
    if config.METRICAS_PUERTO:
        try:
            metricas = ServidorMetricas(config.METRICAS_HOST, config.METRICAS_PUERTO).iniciar()
        except OSError as e:
            log.error("No se pudo abrir el puerto de métricas", {"host": config.METRICAS_HOST, "puerto": config.METRICAS_PUERTO, "error": str(e)})
            sys.exit(1)
        log.info("Métricas para Prometheus", {"host": config.METRICAS_HOST, "puerto": metricas.puerto})

    try:
        _correr(crear_app(config=config), config)
    finally:
        if metricas:
            metricas.detener()


def _correr(app, config) -> None:  # noqa: ANN001
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        # La IP real la calcula el middleware según TRUST_PROXY, uvicorn no toca los encabezados
        proxy_headers=False,
        server_header=False,
        date_header=True,
        access_log=False,
        log_level="warning",
        # Tiempos máximos para que conexiones lentas o colgadas no agoten el servidor
        timeout_keep_alive=5,
        # Al apagar se esperan como máximo 10 segundos, los flujos de cupos en vivo se cortan
        timeout_graceful_shutdown=10,
        h11_max_incomplete_event_size=16 * 1024,
        limit_concurrency=1000,
    )


if __name__ == "__main__":
    main()
