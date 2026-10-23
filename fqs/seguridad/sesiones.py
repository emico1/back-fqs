"""
Sesiones con tokens opacos y renovación rotativa.

Para familias el token de renovación dura REFRESH_TTL_DIAS. Para administración dura
ADMIN_INACTIVIDAD_MINUTOS desde el último uso, con un tope absoluto de ADMIN_SESION_HORAS
desde el inicio de sesión. El token de acceso nunca vence después del de renovación.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Config
from ..db import Consultable, Db
from ..errores import HttpError
from ..jsonfmt import iso
from ..log import log
from .bitacora import registrar_evento
from .tokens import formato_valido, hash_token, nuevo_token


@dataclass
class Duraciones:
    access_minutos: int
    refresh_dias: int
    admin_inactividad_minutos: int
    admin_sesion_horas: int


def duraciones_de(c: Config) -> Duraciones:
    return Duraciones(c.ACCESS_TTL_MINUTOS, c.REFRESH_TTL_DIAS, c.ADMIN_INACTIVIDAD_MINUTOS, c.ADMIN_SESION_HORAS)


@dataclass
class UsuarioSesion:
    id: str
    rol: str
    sesion_id: str
    familia_id: str
    # La sesión se abrió con contraseña y código de la app de autenticación
    segundo_factor: bool


def _invalido() -> HttpError:
    return HttpError(401, "refresh_invalido", "Sesión expirada, inicia sesión de nuevo")


async def emitir_sesion(
    db: Consultable,
    usuario_id: str,
    d: Duraciones,
    agente: str | None = None,
    familia_id: str | None = None,
    familia_inicio: datetime | None = None,
    segundo_factor: bool = False,
) -> dict[str, str]:
    """
    Crea una sesión. También actualiza el último acceso de la cuenta y cancela un aviso por
    inactividad.
    """
    access = nuevo_token("at")
    refresh = nuevo_token("rt")
    r = await db.query(
        """WITH datos AS (
             SELECT u.rol, $9::timestamptz AS inicio,
                    CASE WHEN u.rol = 'admin'
                         THEN least(now() + make_interval(mins => $10), $9::timestamptz + make_interval(hours => $11))
                         ELSE now() + make_interval(days => $6) END AS refresh_fin
             FROM usuarios u WHERE u.id = $1
           )
           INSERT INTO sesiones (usuario_id, familia_id, access_hash, access_expira_en, refresh_hash, refresh_expira_en,
                                 agente, segundo_factor, familia_inicio)
           SELECT $1, $2, $3, least(now() + make_interval(mins => $4), refresh_fin - interval '1 second'), $5, refresh_fin,
                  $7, $8, inicio
           FROM datos
           -- Si el tope ya pasó no se emite nada y quien llama responde que la sesión expiró
           WHERE refresh_fin > now() + interval '1 minute'
           RETURNING access_expira_en, refresh_expira_en""",
        [
            usuario_id,
            familia_id or str(uuid.uuid4()),
            hash_token(access),
            d.access_minutos,
            hash_token(refresh),
            d.refresh_dias,
            agente[:200] if agente else None,
            segundo_factor,
            familia_inicio or datetime.now(timezone.utc),
            d.admin_inactividad_minutos,
            d.admin_sesion_horas,
        ],
    )
    if not r.rows:
        raise _invalido()
    f = r.rows[0]
    await db.query("UPDATE usuarios SET ultimo_acceso_en = now() WHERE id = $1", [usuario_id])
    # Si había avisado que la cuenta se iba a eliminar por inactividad, volver lo cancela
    await db.query("DELETE FROM avisos_inactividad WHERE usuario_id = $1", [usuario_id])
    await db.query(
        "DELETE FROM solicitudes_eliminacion WHERE usuario_id = $1 AND origen = 'inactividad' AND estado = 'pendiente'",
        [usuario_id],
    )
    return {
        "accessToken": access,
        "refreshToken": refresh,
        "accessExpiraEn": iso(f["access_expira_en"]),
        "refreshExpiraEn": iso(f["refresh_expira_en"]),
    }


async def autenticar(db: Db, token: str) -> UsuarioSesion | None:
    """Busca la sesión de un token de acceso. Una cuenta suspendida deja de funcionar al instante."""
    if not formato_valido(token, "at"):
        return None
    r = await db.query(
        """SELECT s.id AS sesion_id, s.familia_id, u.id AS usuario_id, u.rol, s.segundo_factor
           FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.access_hash = $1 AND s.revocada_en IS NULL AND s.rotada_en IS NULL
             AND s.access_expira_en > now() AND u.estado = 'activo'""",
        [hash_token(token)],
    )
    if not r.rows:
        return None
    f = r.rows[0]
    return UsuarioSesion(f["usuario_id"], f["rol"], f["sesion_id"], f["familia_id"], f["segundo_factor"])


async def rotar_sesion(db: Db, refresh: str, d: Duraciones, agente: str | None, ip: str | None = None) -> dict[str, str]:
    """
    Rota un token de renovación. Si llega uno que ya fue rotado, alguien lo está reutilizando
    (posible robo), así que se revoca toda la familia de sesiones.
    """
    if not formato_valido(refresh, "rt"):
        raise _invalido()
    resultado: dict | None = None
    async with db.transaccion() as c:
        r = await c.query(
            """SELECT s.id, s.usuario_id, s.familia_id, s.familia_inicio, s.rotada_en, s.revocada_en, s.segundo_factor,
                      s.refresh_expira_en > now() AS vigente, u.estado
               FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
               WHERE s.refresh_hash = $1 FOR UPDATE OF s""",
            [hash_token(refresh)],
        )
        if r.rows:
            s = r.rows[0]
            if s["rotada_en"] or s["revocada_en"]:
                await c.query("UPDATE sesiones SET revocada_en = now() WHERE familia_id = $1 AND revocada_en IS NULL", [s["familia_id"]])
                resultado = {"reuso": True, "usuario_id": s["usuario_id"]}
            elif not s["vigente"] or s["estado"] != "activo":
                await c.query("UPDATE sesiones SET revocada_en = now() WHERE id = $1", [s["id"]])
            else:
                await c.query("UPDATE sesiones SET rotada_en = now() WHERE id = $1", [s["id"]])
                # La sesión renovada conserva su familia, su inicio y si se abrió con segundo factor
                tokens = await emitir_sesion(
                    c,
                    s["usuario_id"],
                    d,
                    agente=agente,
                    familia_id=s["familia_id"],
                    familia_inicio=s["familia_inicio"],
                    segundo_factor=s["segundo_factor"],
                )
                resultado = {"reuso": False, "tokens": tokens}
    if resultado is None:
        raise _invalido()
    if resultado["reuso"]:
        log.warn("Reuso de refresh token detectado, familia de sesiones revocada", {"usuarioId": resultado["usuario_id"]})
        await registrar_evento(db, "refresh_reutilizado", actor_id=resultado["usuario_id"], ip=ip)
        raise _invalido()
    return resultado["tokens"]


async def listar_sesiones(db: Consultable, usuario_id: str, familia_actual: str) -> list[dict]:
    """
    Sesiones abiertas de una cuenta, una por dispositivo (familia de sesiones). El id que se
    devuelve es el de la familia, que no sirve para autenticarse.
    """
    r = await db.query(
        """SELECT DISTINCT ON (familia_id) familia_id AS id, agente, familia_inicio AS iniciada,
                  creado_en AS ultima_actividad, refresh_expira_en AS vence, segundo_factor
           FROM sesiones
           WHERE usuario_id = $1 AND revocada_en IS NULL AND rotada_en IS NULL AND refresh_expira_en > now()
           ORDER BY familia_id, creado_en DESC""",
        [usuario_id],
    )
    lista = [
        {
            "id": f["id"],
            "dispositivo": f["agente"] or "Dispositivo desconocido",
            "iniciada": iso(f["iniciada"]),
            "ultimaActividad": iso(f["ultima_actividad"]),
            "vence": iso(f["vence"]),
            "segundoFactor": f["segundo_factor"],
            "actual": f["id"] == familia_actual,
        }
        for f in r.rows
    ]
    # La actual primero, después de la más reciente a la más vieja
    lista.sort(key=lambda x: x["ultimaActividad"], reverse=True)
    lista.sort(key=lambda x: not x["actual"])
    return lista


async def revocar_por_refresh(db: Db, refresh: str) -> None:
    if not formato_valido(refresh, "rt"):
        return
    await db.query(
        """UPDATE sesiones SET revocada_en = now()
           WHERE familia_id = (SELECT familia_id FROM sesiones WHERE refresh_hash = $1) AND revocada_en IS NULL""",
        [hash_token(refresh)],
    )


async def revocar_familia(db: Consultable, familia_id: str, usuario_id: str | None = None) -> bool:
    """Revoca una familia de sesiones. Si se indica usuario, solo si es suya. Devuelve si existía."""
    r = await db.query(
        """UPDATE sesiones SET revocada_en = now()
           WHERE familia_id = $1 AND revocada_en IS NULL AND ($2::uuid IS NULL OR usuario_id = $2::uuid)""",
        [familia_id, usuario_id],
    )
    return r.rowcount > 0


async def revocar_todas(db: Consultable, usuario_id: str, excepto_familia: str | None = None) -> None:
    await db.query(
        """UPDATE sesiones SET revocada_en = now()
           WHERE usuario_id = $1 AND revocada_en IS NULL AND ($2::uuid IS NULL OR familia_id <> $2::uuid)""",
        [usuario_id, excepto_familia],
    )


async def purgar_sesiones(db: Db) -> None:
    """Limpieza periódica de sesiones, desafíos y verificaciones que ya no sirven."""
    await db.query(
        """DELETE FROM sesiones WHERE refresh_expira_en < now() - interval '7 days'
              OR (revocada_en IS NOT NULL AND revocada_en < now() - interval '30 days')
              OR (rotada_en IS NOT NULL AND rotada_en < now() - interval '30 days')"""
    )
    await db.query("DELETE FROM tokens_recuperacion WHERE expira_en < now() - interval '1 day'")
    await db.query("DELETE FROM desafios_2fa WHERE expira_en < now() - interval '1 day'")
    # Los registros que nadie verificó se borran, junto con su copia del hash de la contraseña
    await db.query("DELETE FROM verificaciones_contacto WHERE expira_en < now() - interval '1 day'")
