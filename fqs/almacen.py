"""
Almacenamiento de imágenes en disco. El nombre de cada archivo es su UUID, nunca un nombre
elegido por el cliente, así que no hay forma de escribir fuera de la carpeta.
"""

import asyncio
import os
import re
from pathlib import Path


class Almacen:
    def __init__(self, carpeta: str) -> None:
        self.carpeta = Path(carpeta)

    def preparar(self) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _ruta(self, ident: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}", ident):
            raise ValueError("Identificador de archivo inválido")
        return self.carpeta / ident

    def _guardar(self, ident: str, datos: bytes) -> None:
        # O_EXCL falla si el archivo ya existe, nunca se sobrescribe nada
        fd = os.open(self._ruta(ident), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(datos)

    async def guardar(self, ident: str, datos: bytes) -> None:
        await asyncio.to_thread(self._guardar, ident, datos)

    async def leer(self, ident: str) -> bytes:
        return await asyncio.to_thread(self._ruta(ident).read_bytes)

    async def borrar(self, ident: str) -> None:
        await asyncio.to_thread(self._ruta(ident).unlink, True)
