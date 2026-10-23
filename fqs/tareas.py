"""Tareas que corren aparte de la petición (envíos de correo, SMS y push)."""

import asyncio
from typing import Any, Coroutine

from .log import log

_pendientes: set[asyncio.Task] = set()


def en_segundo_plano(coro: Coroutine[Any, Any, Any], que: str) -> asyncio.Task:
    """Corre la corutina sin esperarla. Si falla, solo queda el error en el log."""

    async def envoltura() -> None:
        try:
            await coro
        except Exception as e:  # noqa: BLE001
            log.error(f"No se pudo completar {que}", {"error": str(e)})

    tarea = asyncio.create_task(envoltura())
    _pendientes.add(tarea)
    tarea.add_done_callback(_pendientes.discard)
    return tarea


async def esperar_pendientes() -> None:
    """Para las pruebas y el apagado, espera a que terminen los envíos en curso."""
    while _pendientes:
        await asyncio.gather(*list(_pendientes), return_exceptions=True)
