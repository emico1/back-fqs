"""
Correo de confirmación para los acompañantes adultos.

Cuando una familia inscribe a alguien de su comunidad que tiene correo y ya cumplió 18 años,
esa persona recibe la confirmación con la fecha, el lugar y quién la inscribió. Si la
actividad se cancela, también recibe el aviso.

Cuidados de privacidad y de abuso.
  A menores nunca se les escribe, aunque tengan correo registrado.
  El correo no incluye el teléfono ni el correo de quien inscribió, solo su nombre.
  Como el correo del acompañante lo escribe la familia y no está verificado, cada titular
  puede generar como máximo 30 de estos correos al día. Así una cuenta no puede usar las
  inscripciones para mandar correos a quien quiera.
  El envío corre aparte de la petición. Si el proveedor falla, la inscripción ya quedó y solo
  se registra el error.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from .db import Consultable
from .log import log

MAYORIA_EDAD = 18

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

_SQL_ACTIVIDAD = """
  SELECT a.titulo, a.inicio, a.direccion, aso.nombre AS asociacion, ci.zona_horaria AS zona
  FROM actividades a JOIN asociaciones aso ON aso.id = a.asociacion_id JOIN ciudades ci ON ci.id = a.ciudad_id
  WHERE a.id = $1"""

# Acompañantes de las inscripciones indicadas que son mayores de edad el día del evento y
# tienen un correo distinto al del titular
_SQL_DESTINATARIOS = f"""
  SELECT DISTINCT ON (lower(m.correo), i.usuario_id) m.correo, m.nombre, u.id AS "titularId", u.nombre AS titular
  FROM inscripcion_participantes p
  JOIN inscripciones i ON i.id = p.inscripcion_id
  JOIN miembros_comunidad m ON m.id = p.miembro_comunidad_id
  JOIN usuarios u ON u.id = i.usuario_id
  WHERE NOT p.es_titular AND m.correo IS NOT NULL AND p.edad_al_evento >= {MAYORIA_EDAD}
    AND lower(m.correo) IS DISTINCT FROM lower(u.correo)"""


def fecha_legible(inicio: datetime, zona: str) -> str:
    """Por ejemplo, lunes, 26 de octubre de 2026, 10:00 a.m. en la hora de la ciudad."""
    try:
        tz = ZoneInfo(zona)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("America/Mexico_City")
    d = inicio.astimezone(tz)
    hora12 = d.hour % 12 or 12
    sufijo = "a.m." if d.hour < 12 else "p.m."
    return f"{_DIAS[d.weekday()]}, {d.day} de {_MESES[d.month - 1]} de {d.year}, {hora12}:{d.minute:02d} {sufijo}"


async def _datos_actividad(db: Consultable, actividad_id: str) -> dict | None:
    r = await db.query(_SQL_ACTIVIDAD, [actividad_id])
    return r.rows[0] if r.rows else None


async def destinatarios_inscripcion(db: Consultable, inscripcion_id: str) -> list[dict]:
    """Destinatarios de una inscripción recién hecha."""
    r = await db.query(f"{_SQL_DESTINATARIOS} AND i.id = $1 AND i.estado = 'confirmada'", [inscripcion_id])
    return r.rows


async def destinatarios_actividad(db: Consultable, actividad_id: str) -> list[dict]:
    """Destinatarios de una actividad que se va a cancelar. Se consulta antes de cancelar."""
    r = await db.query(f"{_SQL_DESTINATARIOS} AND i.actividad_id = $1 AND i.estado = 'confirmada'", [actividad_id])
    return r.rows


async def _enviar_a_todos(s, destinatarios: list[dict], armar) -> int:  # noqa: ANN001
    enviados = 0
    for d in destinatarios:
        clave = f"acompanantes {d['titularId']}"
        if s.limites.correos_acompanantes.bloqueado(clave):
            log.warn("Tope diario de correos a acompañantes alcanzado", {"titularId": d["titularId"]})
            continue
        s.limites.correos_acompanantes.consumir(clave)
        asunto, parrafos = armar(d)
        try:
            await s.correo.enviar_aviso(d["correo"], asunto, parrafos)
            enviados += 1
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo enviar el correo al acompañante", {"error": str(e)})
    return enviados


async def avisar_inscripcion(s, actividad_id: str, inscripcion_id: str) -> int:  # noqa: ANN001
    destinatarios = await destinatarios_inscripcion(s.db, inscripcion_id)
    if not destinatarios:
        return 0
    a = await _datos_actividad(s.db, actividad_id)
    if not a:
        return 0
    cuando = fecha_legible(a["inicio"], a["zona"])
    return await _enviar_a_todos(
        s,
        destinatarios,
        lambda d: (
            f"Te inscribieron a {a['titulo']}",
            [
                f"Hola {d['nombre']}.",
                f"{d['titular']} te inscribió a la actividad \"{a['titulo']}\" de {a['asociacion']}, como parte de su grupo en Familias que Suman.",
                f"Cuándo, {cuando}.",
                f"Dónde, {a['direccion']}.",
                "Si no puedes asistir, avísale a quien te inscribió para que libere tu lugar y otra familia pueda aprovecharlo.",
                "Si no conoces a esta persona, puedes ignorar este correo. No se creó ninguna cuenta con tu dirección.",
            ],
        ),
    )


async def avisar_cancelacion(s, actividad_id: str, destinatarios: list[dict], motivo: str) -> int:  # noqa: ANN001
    if not destinatarios:
        return 0
    a = await _datos_actividad(s.db, actividad_id)
    if not a:
        return 0
    cuando = fecha_legible(a["inicio"], a["zona"])
    return await _enviar_a_todos(
        s,
        destinatarios,
        lambda d: (
            f"Se canceló {a['titulo']}",
            [
                f"Hola {d['nombre']}.",
                f"La actividad \"{a['titulo']}\" de {a['asociacion']}, programada para {cuando}, se canceló.",
                f"Motivo, {motivo}",
                f"{d['titular']} te había inscrito. No necesitas hacer nada más.",
            ],
        ),
    )
