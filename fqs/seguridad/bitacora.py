"""
Eventos que quedan en la bitácora de seguridad (db/07_seguridad.sql). La tabla es de solo
agregar y cada fila lleva el hash de la anterior.

Nunca se guardan contraseñas, códigos, tokens ni el cuerpo de las peticiones, solo quién hizo
qué, sobre qué id, desde qué IP y cuándo.
"""

import json
from typing import Any

from .. import metricas
from ..db import Consultable
from ..log import log
from ..validacion import UUID_RE


async def registrar_evento(
    db: Consultable,
    accion: str,
    actor_id: str | None = None,
    actor_rol: str | None = None,
    ruta: str | None = None,
    entidad_id: str | None = None,
    detalles: dict[str, Any] | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> None:
    """Guarda un evento. Si falla no tumba la petición, pero deja rastro en el log."""
    try:
        await db.query(
            """INSERT INTO bitacora_seguridad (actor_id, actor_rol, accion, ruta, entidad_id, detalles, ip, request_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            [
                actor_id,
                actor_rol,
                accion,
                ruta[:200] if ruta else None,
                entidad_id if entidad_id and UUID_RE.match(entidad_id) else None,
                json.dumps(detalles or {}, ensure_ascii=False),
                ip[:64] if ip else None,
                request_id if request_id and UUID_RE.match(request_id) else None,
            ],
        )
        metricas.evento_seguridad(accion)
    except Exception as e:  # noqa: BLE001
        metricas.ERRORES_BITACORA.inc()
        log.error("No se pudo escribir en la bitácora de seguridad", {"accion": accion, "error": str(e)})
