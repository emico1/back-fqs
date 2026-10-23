"""
Acceso a PostgreSQL con psycopg 3 (asíncrono) y un pool de conexiones.

Todas las consultas usan parámetros ($1, $2...) que se mandan aparte del texto SQL, nunca
se concatena texto del cliente dentro del SQL. Cada conexión fija el search_path al schema
fqs y un tiempo máximo por consulta, para que una consulta lenta no acapare conexiones.

bigint y numeric llegan como texto (no pierden precisión), date como AAAA-MM-DD y uuid como
texto, que es como los espera la app.
"""

import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, Sequence

import psycopg
from psycopg.adapt import Loader
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import Config
from .log import log


class _Texto(Loader):
    def load(self, data: Any) -> str:
        return bytes(data).decode("utf-8")


def _configurar_tipos(conn: psycopg.AsyncConnection | psycopg.Connection) -> None:
    for tipo in ("int8", "numeric", "date", "uuid"):
        conn.adapters.register_loader(tipo, _Texto)


@dataclass
class Resultado:
    rows: list[dict[str, Any]]
    rowcount: int


_PARAM = re.compile(r"\$(\d+)")


def _preparar(sql: str, params: Sequence[Any] | None) -> tuple[str, dict[str, Any] | None]:
    """Convierte $1, $2 al formato de psycopg. El texto SQL nunca lleva datos del cliente."""
    if not params:
        return sql, None
    convertido = _PARAM.sub(lambda m: f"%(p{m.group(1)})s", sql.replace("%", "%%"))
    return convertido, {f"p{i + 1}": v for i, v in enumerate(params)}


class Consultable(Protocol):
    async def query(self, sql: str, params: Sequence[Any] | None = None) -> Resultado: ...


class Conexion:
    """Conexión tomada del pool, normalmente dentro de una transacción."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    async def query(self, sql: str, params: Sequence[Any] | None = None) -> Resultado:
        texto, valores = _preparar(sql, params)
        async with self.conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(texto, valores)
            filas = await cur.fetchall() if cur.description else []
            return Resultado(rows=filas, rowcount=cur.rowcount)


def _conninfo_extra(c: Config, nombre: str, con_tiempos: bool = True) -> dict[str, Any]:
    opciones = "-c search_path=fqs,pg_catalog"
    if con_tiempos:
        opciones += " -c statement_timeout=10000 -c idle_in_transaction_session_timeout=15000"
    extra: dict[str, Any] = {"application_name": nombre, "options": opciones, "connect_timeout": 5}
    if c.DB_SSL == "disable":
        extra["sslmode"] = "disable"
    else:
        extra["sslmode"] = c.DB_SSL
        if c.DB_SSL_CA:
            extra["sslrootcert"] = c.DB_SSL_CA
    return extra


class Db:
    """Pool de conexiones con la misma interfaz de consulta que una Conexion."""

    def __init__(self, config: Config) -> None:
        self.config = config

        async def configurar(conn: psycopg.AsyncConnection) -> None:
            _configurar_tipos(conn)

        self.pool = AsyncConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=config.DB_POOL_MAX,
            timeout=5,
            open=False,
            configure=configurar,
            kwargs={**_conninfo_extra(config, "fqs-backend"), "autocommit": True},
        )

    async def abrir(self) -> None:
        await self.pool.open(wait=True, timeout=10)

    async def cerrar(self) -> None:
        await self.pool.close()

    async def query(self, sql: str, params: Sequence[Any] | None = None) -> Resultado:
        async with self.pool.connection() as conn:
            return await Conexion(conn).query(sql, params)

    @asynccontextmanager
    async def transaccion(self) -> AsyncIterator[Conexion]:
        """Ejecuta un bloque en una transacción. Cualquier excepción hace ROLLBACK."""
        async with self.pool.connection() as conn:
            async with conn.transaction():
                yield Conexion(conn)

    async def conexion_escucha(self) -> psycopg.AsyncConnection:
        """Conexión dedicada para LISTEN, fuera del pool porque se queda abierta todo el tiempo."""
        conn = await psycopg.AsyncConnection.connect(
            self.config.DATABASE_URL, autocommit=True, **_conninfo_extra(self.config, "fqs-backend-escucha", False)
        )
        return conn


async def verificar_rol_seguro(db: Db, produccion: bool) -> None:
    """
    En producción el backend no debe conectarse como superusuario ni como dueño del schema,
    sino con un usuario del grupo fqs_backend (ver db/03_roles.sql).
    """
    r = await db.query(
        """SELECT r.rolsuper,
                  EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname = 'fqs' AND n.nspowner = r.oid) AS es_dueno
           FROM pg_roles r WHERE r.rolname = current_user"""
    )
    fila = r.rows[0] if r.rows else None
    if fila and (fila["rolsuper"] or fila["es_dueno"]):
        msg = "El backend está conectado con un rol con privilegios de más (superusuario o dueño del schema)"
        if produccion:
            raise RuntimeError(msg + ". Usa un usuario del grupo fqs_backend.")
        log.warn(msg + ". Aceptable solo en desarrollo.")


# Cada migración agrega algo que el código necesita. Si falta alguna, el servidor se niega a
# arrancar con un mensaje que dice qué script correr.
_MIGRACIONES = [
    ("db/04_backend.sql", "sesiones", "refresh_hash"),
    ("db/05_fase1.sql", "actividades", "tipo"),
    ("db/05_fase1.sql", "proyectos", "ciudad_id"),
    ("db/06_fase2.sql", "notificaciones", "push_enviada_en"),
    ("db/07_seguridad.sql", "sesiones", "segundo_factor"),
    ("db/07_seguridad.sql", "bitacora_seguridad", "hash"),
    ("db/08_seguridad2.sql", "usuarios", "correo_verificado_en"),
    ("db/08_seguridad2.sql", "bitacora_cortes", "hasta_id"),
    ("db/09_telefono.sql", "usuarios", "telefono_verificado_en"),
    ("db/10_idempotencia.sql", "idempotencia", "huella"),
]


async def verificar_migraciones(db: Db) -> None:
    r = await db.query(
        """SELECT table_name AS tabla, column_name AS columna FROM information_schema.columns
           WHERE table_schema = 'fqs' AND (table_name, column_name) IN (SELECT * FROM unnest($1::text[], $2::text[]))""",
        [[m[1] for m in _MIGRACIONES], [m[2] for m in _MIGRACIONES]],
    )
    presentes = {f"{f['tabla']}.{f['columna']}" for f in r.rows}
    faltan: list[str] = []
    for archivo, tabla, columna in _MIGRACIONES:
        if f"{tabla}.{columna}" not in presentes and archivo not in faltan:
            faltan.append(archivo)
    if faltan:
        raise RuntimeError(f"A la base le faltan migraciones. Córrelas en este orden con el usuario postgres, {', '.join(faltan)}")
