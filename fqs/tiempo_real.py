"""
Cupos en tiempo real (RF-05). PostgreSQL avisa por el canal fqs_cupos cada vez que cambian los
lugares de una actividad publicada (ver db/05_fase1.sql). Una sola conexión escucha ese canal
y reenvía cada aviso a todas las apps conectadas por Server-Sent Events. Si la conexión con
la base se cae, se reintenta sola.
"""

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from .db import Db
from .errores import HttpError
from .log import log

MAX_POR_USUARIO = 3
MAX_TOTAL = 2000
LATIDO_SEGUNDOS = 25
# Cada flujo dura como máximo lo mismo que un token de acceso. Al cerrarse, la app se vuelve a
# conectar con un token vigente, así una sesión revocada no sigue escuchando.
DURACION_MAXIMA_SEGUNDOS = 15 * 60


@dataclass(eq=False)
class Suscriptor:
    usuario_id: str
    cola: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=200))
    cerrado: bool = False


class CanalCupos:
    def __init__(self, db: Db | None) -> None:
        self.db = db
        self.suscriptores: set[Suscriptor] = set()
        self._otros: dict[str, Callable[[str], None]] = {}
        self._tareas: list[asyncio.Task] = []
        self._detenido = False

    def escuchar(self, canal: str, manejador: Callable[[str], None]) -> None:
        """
        Escucha otro canal de PostgreSQL en la misma conexión, por ejemplo fqs_notificaciones
        para el envío push. Se registra antes de iniciar().
        """
        self._otros[canal] = manejador

    async def iniciar(self) -> None:
        if self.db is None:
            return
        listo = asyncio.Event()
        self._tareas.append(asyncio.create_task(self._latidos()))
        self._tareas.append(asyncio.create_task(self._escuchar(listo)))
        try:
            await asyncio.wait_for(listo.wait(), 10)
        except asyncio.TimeoutError:
            log.warn("La escucha de cupos tardó en conectarse, sigue intentando")

    async def _latidos(self) -> None:
        while not self._detenido:
            await asyncio.sleep(LATIDO_SEGUNDOS)
            self._enviar_a_todos(": latido\n\n")

    async def _escuchar(self, listo: asyncio.Event) -> None:
        assert self.db is not None
        while not self._detenido:
            conn = None
            try:
                conn = await self.db.conexion_escucha()
                await conn.execute("LISTEN fqs_cupos")
                # Los nombres de canal son fijos en el código, nunca vienen del cliente
                for canal in self._otros:
                    await conn.execute(f"LISTEN {canal}")
                listo.set()
                async for aviso in conn.notifies():
                    if not aviso.payload:
                        continue
                    if aviso.channel == "fqs_cupos":
                        self._enviar_a_todos(f"event: cupos\ndata: {aviso.payload}\n\n")
                    elif aviso.channel in self._otros:
                        try:
                            self._otros[aviso.channel](aviso.payload)
                        except Exception as e:  # noqa: BLE001
                            log.warn("Falló el manejador de un aviso de la base", {"error": str(e)})
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                if self._detenido:
                    return
                log.warn("Se perdió la escucha de cupos, reintentando en 5 segundos", {"error": str(e)})
                listo.set()
                await asyncio.sleep(5)
            finally:
                if conn is not None:
                    try:
                        await conn.close()
                    except Exception:  # noqa: BLE001
                        pass

    def suscribir(self, usuario_id: str) -> Suscriptor:
        """Registra un flujo SSE para un usuario. Lanza 429 si ya tiene demasiados abiertos."""
        propios = sum(1 for s in self.suscriptores if s.usuario_id == usuario_id)
        if propios >= MAX_POR_USUARIO or len(self.suscriptores) >= MAX_TOTAL:
            raise HttpError(429, "demasiadas_conexiones", "Demasiadas conexiones abiertas en tiempo real")
        s = Suscriptor(usuario_id)
        self.suscriptores.add(s)
        return s

    async def flujo(self, s: Suscriptor) -> AsyncIterator[bytes]:
        """Texto del flujo SSE, termina al cerrar la conexión o a los 15 minutos."""
        try:
            yield b"retry: 5000\n: conectado\n\n"
            fin = asyncio.get_running_loop().time() + DURACION_MAXIMA_SEGUNDOS
            while not s.cerrado:
                restante = fin - asyncio.get_running_loop().time()
                if restante <= 0:
                    break
                try:
                    texto = await asyncio.wait_for(s.cola.get(), timeout=min(restante, LATIDO_SEGUNDOS + 5))
                except asyncio.TimeoutError:
                    continue
                if texto is None:
                    break
                yield texto.encode("utf-8")
        finally:
            self.suscriptores.discard(s)

    def desconectar(self, usuario_id: str) -> None:
        """Cierra las conexiones de un usuario (al cerrar sesión o suspender la cuenta)."""
        for s in list(self.suscriptores):
            if s.usuario_id == usuario_id:
                self._cerrar(s)

    @staticmethod
    def _cerrar(s: Suscriptor) -> None:
        s.cerrado = True
        try:
            s.cola.put_nowait(None)
        except asyncio.QueueFull:
            pass

    @property
    def conectados(self) -> int:
        return len(self.suscriptores)

    def _enviar_a_todos(self, texto: str) -> None:
        for s in list(self.suscriptores):
            try:
                s.cola.put_nowait(texto)
            except asyncio.QueueFull:
                # Una conexión que no lee se cierra, no se acumula memoria por ella
                self._cerrar(s)

    async def detener(self) -> None:
        self._detenido = True
        for s in list(self.suscriptores):
            self._cerrar(s)
        for t in self._tareas:
            t.cancel()
        for t in self._tareas:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tareas.clear()
