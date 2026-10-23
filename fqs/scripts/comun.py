"""Piezas compartidas por los scripts de operación."""

import asyncio
import sys
from typing import Awaitable, Callable

from ..config import Config, cargar_config, cargar_env
from ..db import Db


def correr(principal: Callable[[], Awaitable[None]]) -> None:
    """Corre el script y convierte cualquier error en un mensaje corto y código de salida 1."""
    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        sys.stderr.write("\nCancelado\n")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Error, {e}\n")
        sys.exit(1)


def configuracion() -> Config:
    cargar_env(".env")
    return cargar_config()


async def abrir_db(config: Config) -> Db:
    db = Db(config)
    await db.abrir()
    return db
