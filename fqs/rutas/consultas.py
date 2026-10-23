"""
Consultas compartidas entre rutas. Todas usan parámetros ($1, $2...) y nunca concatenan
texto del cliente dentro del SQL. Los fragmentos de SQL de este archivo son fijos.
"""

from ..db import Consultable
from ..errores import HttpError, no_encontrado
from ..seguridad.sesiones import UsuarioSesion


async def perfil_completo(db: Consultable, usuario_id: str) -> dict:
    r = await db.query(
        """SELECT u.id, u.nombre, u.username, u.correo, u.telefono, u.rol,
                  u.fecha_nacimiento::text AS "fechaNacimiento", u.foto_clave AS "fotoClave", u.creado_en AS "creadoEn",
                  CASE WHEN c.id IS NULL THEN NULL ELSE json_build_object('id', c.id, 'nombre', c.nombre, 'zonaHoraria', c.zona_horaria) END AS ciudad,
                  json_build_object(
                    'quiereDonar', COALESCE(p.quiere_donar, false),
                    'quiereParticipar', COALESCE(p.quiere_participar, false),
                    'quiereProponer', COALESCE(p.quiere_proponer, false),
                    'recibirRecordatorios', COALESCE(p.recibir_recordatorios, true),
                    'recibirSugerencias', COALESCE(p.recibir_sugerencias, true)
                  ) AS preferencias,
                  COALESCE((SELECT json_agg(ca.clave ORDER BY ca.clave) FROM usuario_categorias uc
                            JOIN categorias ca ON ca.id = uc.categoria_id WHERE uc.usuario_id = u.id), '[]') AS categorias,
                  COALESCE((SELECT sum(participaciones) FROM participaciones_usuario WHERE usuario_id = u.id), 0)::int AS participaciones,
                  (u.rol = 'familia' AND EXISTS (SELECT 1 FROM aviso_privacidad_vigente)
                    AND NOT EXISTS (SELECT 1 FROM aceptaciones_privacidad ap JOIN aviso_privacidad_vigente v ON v.id = ap.aviso_id
                                    WHERE ap.usuario_id = u.id)) AS "avisoPendiente"
           FROM usuarios u
           LEFT JOIN ciudades c ON c.id = u.ciudad_id
           LEFT JOIN usuario_preferencias p ON p.usuario_id = u.id
           WHERE u.id = $1""",
        [usuario_id],
    )
    if not r.rows:
        raise no_encontrado("Usuario")
    perfil = r.rows[0]
    total = int(perfil["participaciones"])
    nivel = await db.query(
        """SELECT nombre, descripcion, participaciones_minimas AS "participacionesMinimas"
           FROM niveles WHERE participaciones_minimas <= $1 ORDER BY participaciones_minimas DESC LIMIT 1""",
        [total],
    )
    # Las insignias se calculan a partir de las participaciones con asistencia, así no hay
    # forma de que el cliente se otorgue una
    insignias = await db.query(
        """SELECT i.id, i.nombre, i.descripcion, i.imagen_clave AS "imagenClave"
           FROM insignias i
           WHERE i.activa AND i.participaciones_requeridas <= COALESCE((
             SELECT sum(pu.participaciones) FROM participaciones_usuario pu
             WHERE pu.usuario_id = $1 AND (i.categoria_id IS NULL OR pu.categoria_id = i.categoria_id)), 0)
           ORDER BY i.participaciones_requeridas DESC, i.nombre""",
        [usuario_id],
    )
    return {**perfil, "nivel": nivel.rows[0] if nivel.rows else None, "insignias": insignias.rows}


async def ciudad_visible(db: Consultable, usuario: UsuarioSesion, ciudad_pedida: str | None) -> str | None:
    """
    Ciudad con la que se filtra el contenido (RF-02). Una familia solo ve la ciudad guardada en
    su perfil, aunque mande otra en la URL. Para cambiarla usa PATCH /v1/yo. La persona
    administradora puede elegir cualquiera o ninguna.
    """
    if usuario.rol == "admin":
        return ciudad_pedida or None
    r = await db.query("SELECT ciudad_id FROM usuarios WHERE id = $1", [usuario.id])
    ciudad = r.rows[0]["ciudad_id"] if r.rows else None
    if not ciudad:
        raise HttpError(409, "sin_ciudad", "Elige tu ciudad para ver el contenido")
    return ciudad


def ciudad_del_usuario(n: int) -> str:
    """Ciudad del perfil, en SQL, para revisar la visibilidad de un detalle. $n es el id de usuario."""
    return f"(SELECT u_c.ciudad_id FROM usuarios u_c WHERE u_c.id = ${n})"


# Una campaña solo se muestra a las familias si quien la organiza está verificado (RF-01).
# Aplica a la asociación de la campaña y a la del proyecto, si lo hay.
CAMPANA_VERIFICADA = """
  (aso.id IS NULL OR (aso.verificada AND aso.activa))
  AND (pr.id IS NULL OR pr.estado IN ('publicado','finalizado'))
  AND (pr.asociacion_id IS NULL OR EXISTS (
        SELECT 1 FROM asociaciones x WHERE x.id = pr.asociacion_id AND x.verificada AND x.activa))"""


async def exigir_archivo_propio(db: Consultable, archivo_id: str | None, usuario_id: str) -> None:
    """Verifica que un archivo subido pertenece al usuario antes de enlazarlo a algo."""
    if not archivo_id:
        return
    r = await db.query("SELECT 1 FROM archivos WHERE id = $1 AND usuario_id = $2", [archivo_id, usuario_id])
    if r.rowcount == 0:
        raise HttpError(422, "archivo_invalido", "La imagen no existe o no es tuya")


async def exigir_archivo_de_administracion(db: Consultable, archivo_id: str | None) -> None:
    """
    Imagen para contenido de la organización (asociaciones, actividades, campañas). Con varias
    personas en el panel, una puede editar lo que subió otra, así que basta con que la imagen
    la haya subido una cuenta de administración. Una foto subida por una familia no se puede
    usar como foto oficial.
    """
    if not archivo_id:
        return
    r = await db.query(
        "SELECT 1 FROM archivos ar JOIN usuarios u ON u.id = ar.usuario_id WHERE ar.id = $1 AND u.rol = 'admin'", [archivo_id]
    )
    if r.rowcount == 0:
        raise HttpError(422, "archivo_invalido", "La imagen no existe o no la subió el equipo de administración")


def votos_asociacion(alias: str, valor: int) -> str:
    """
    Me gusta y no me gusta que recibieron todas las actividades de una asociación (RF21). Solo
    puede votar quien asistió, lo exige la base de datos.
    """
    return f"""
  (SELECT count(*)::int FROM valoraciones_actividades v
   JOIN inscripciones vi ON vi.id = v.inscripcion_id
   JOIN actividades vx ON vx.id = vi.actividad_id
   WHERE vx.asociacion_id = {alias}.id AND v.valor = {int(valor)})"""


def calidad_asociacion(alias: str) -> str:
    """
    Calidad con suavizado de Laplace, (me gusta + 1) / (votos + 2). Una asociación sin votos
    queda en 0.5 y no gana ni pierde lugares por un solo voto.
    """
    return f"(({votos_asociacion(alias, 1)} + 1)::float8 / ({votos_asociacion(alias, 1)} + {votos_asociacion(alias, -1)} + 2))"


COLUMNAS_ACTIVIDAD = f"""
  a.id, a.titulo, a.descripcion_corta AS "descripcionCorta", a.descripcion, a.recomendaciones,
  a.inicio, a.fin, ci.zona_horaria AS "zonaHoraria", a.direccion,
  a.latitud::float8 AS latitud, a.longitud::float8 AS longitud,
  a.apta_ninos AS "aptaNinos", a.edad_minima AS "edadMinima",
  a.cupo_total AS "cupoTotal", a.cupos_ocupados AS "cuposOcupados",
  (a.cupo_total - a.cupos_ocupados) AS "cuposDisponibles",
  a.estado, a.tipo, a.foto_clave AS "fotoClave",
  json_build_object('id', ca.id, 'clave', ca.clave, 'nombre', ca.nombre) AS categoria,
  json_build_object('id', aso.id, 'nombre', aso.nombre, 'verificada', aso.verificada,
                    'meGusta', {votos_asociacion('aso', 1)}, 'noMeGusta', {votos_asociacion('aso', -1)}) AS asociacion,
  json_build_object('id', ci.id, 'nombre', ci.nombre) AS ciudad"""

FROM_ACTIVIDAD = """
  FROM actividades a
  JOIN categorias ca ON ca.id = a.categoria_id
  JOIN asociaciones aso ON aso.id = a.asociacion_id
  JOIN ciudades ci ON ci.id = a.ciudad_id"""

COLUMNAS_ASOCIACION = f"""
  aso.id, aso.nombre, aso.descripcion, aso.mision, aso.necesidades,
  aso.familias_beneficiadas AS "familiasBeneficiadas", aso.direccion,
  aso.latitud::float8 AS latitud, aso.longitud::float8 AS longitud,
  aso.telefono, aso.whatsapp, aso.correo, aso.sitio_web AS "sitioWeb",
  aso.foto_clave AS "fotoClave", aso.verificada,
  {votos_asociacion('aso', 1)} AS "meGusta", {votos_asociacion('aso', -1)} AS "noMeGusta",
  json_build_object('id', ca.id, 'clave', ca.clave, 'nombre', ca.nombre) AS categoria,
  json_build_object('id', ci.id, 'nombre', ci.nombre) AS ciudad"""

COLUMNAS_CAMPANA = """
  cp.id, cp.titulo, cp.descripcion, cp.inicio, cp.fin, cp.urgente, cp.estado,
  cp.foto_clave AS "fotoClave",
  COALESCE(aso.nombre, pr.titulo) AS organizacion, cp.asociacion_id AS "asociacionId",
  cp.proyecto_id AS "proyectoId",
  json_build_object('id', ci.id, 'nombre', ci.nombre) AS ciudad,
  COALESCE((SELECT round(avg(LEAST(ar.cantidad_recibida / ar.cantidad_meta, 1)), 4)::float8
            FROM campana_articulos ar WHERE ar.campana_id = cp.id), 0) AS progreso,
  (SELECT count(*)::int FROM campana_articulos ar WHERE ar.campana_id = cp.id) AS "totalArticulos\""""

FROM_CAMPANA = """
  FROM campanas cp
  JOIN ciudades ci ON ci.id = cp.ciudad_id
  LEFT JOIN asociaciones aso ON aso.id = cp.asociacion_id
  LEFT JOIN proyectos pr ON pr.id = cp.proyecto_id"""

COLUMNAS_PROYECTO = """
  pr.id, pr.titulo, pr.descripcion, pr.fecha_inicio::text AS "fechaInicio", pr.fecha_fin::text AS "fechaFin",
  pr.foto_clave AS "fotoClave", pr.estado,
  CASE WHEN aso.id IS NULL THEN NULL ELSE json_build_object('id', aso.id, 'nombre', aso.nombre) END AS asociacion,
  json_build_object('id', ci.id, 'nombre', ci.nombre) AS ciudad,
  (SELECT count(*)::int FROM campanas c WHERE c.proyecto_id = pr.id AND c.estado = 'publicada' AND c.fin > now()) AS "campanasActivas",
  COALESCE((SELECT round(avg(LEAST(ar.cantidad_recibida / ar.cantidad_meta, 1)), 4)::float8
            FROM campanas c JOIN campana_articulos ar ON ar.campana_id = c.id
            WHERE c.proyecto_id = pr.id AND c.estado IN ('publicada','finalizada')), 0) AS progreso"""

FROM_PROYECTO = """
  FROM proyectos pr
  JOIN ciudades ci ON ci.id = pr.ciudad_id
  LEFT JOIN asociaciones aso ON aso.id = pr.asociacion_id"""

# Igual que CAMPANA_VERIFICADA pero para la lista de proyectos
PROYECTO_VERIFICADO = "(aso.id IS NULL OR (aso.verificada AND aso.activa))"
