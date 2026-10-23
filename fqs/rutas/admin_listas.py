"""
Listados y fichas completas para el panel de administración. A diferencia de las rutas de la
app, aquí se ven todos los estados (borradores, canceladas, sin verificar) y todos los campos
editables. Todas exigen rol de administración y, si está en obligatorio, segundo factor.
"""

from typing import Annotated, Literal

from fastapi import Query

from ..errores import no_encontrado
from ..http.dependencias import Admin, Svc
from ..validacion import Desplazamiento, UuidQuery
from .comun import IdRuta, nuevo_router, ok

router = nuevo_router("admin")

Busqueda = Annotated[str | None, Query(min_length=1, max_length=80)]
LimiteAdmin = Annotated[int, Query(ge=1, le=50)]


def _patron(t: str | None) -> str | None:
    """Los comodines de LIKE escritos por la persona se buscan como texto, no como patrón."""
    if t is None or not t.strip():
        return None
    limpio = t.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{limpio}%"


@router.get("/v1/admin/resumen", summary="Pendientes del equipo para la pantalla de inicio del panel")
async def resumen(s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT
             (SELECT count(*)::int FROM propuestas WHERE estado = 'en_revision') AS "propuestasPorRevisar",
             (SELECT count(*)::int FROM testimonios WHERE estado = 'pendiente') AS "testimoniosPorModerar",
             (SELECT count(*)::int FROM reportes_experiencia WHERE estado <> 'resuelto') AS "reportesAbiertos",
             (SELECT count(*)::int FROM entregas_donacion WHERE estado = 'registrada') AS "entregasPorConfirmar",
             (SELECT count(*)::int FROM solicitudes_eliminacion WHERE estado <> 'resuelta') AS "solicitudesEliminacion",
             (SELECT count(*)::int FROM asociaciones WHERE NOT verificada AND activa) AS "asociacionesSinVerificar",
             (SELECT count(*)::int FROM actividades WHERE estado = 'publicada' AND inicio > now()) AS "actividadesProximas",
             (SELECT count(*)::int FROM actividades WHERE estado = 'borrador') AS "actividadesBorrador",
             (SELECT count(*)::int FROM usuarios WHERE rol = 'familia' AND estado = 'activo') AS "familiasActivas",
             (SELECT count(*)::int FROM alertas_seguridad WHERE creado_en > now() - interval '7 days') AS "alertasSemana\""""
    )
    proximas = await s.db.query(
        """SELECT a.id, a.titulo, a.inicio, a.cupo_total AS "cupoTotal", a.cupos_ocupados AS "cuposOcupados", aso.nombre AS asociacion
           FROM actividades a JOIN asociaciones aso ON aso.id = a.asociacion_id
           WHERE a.estado = 'publicada' AND a.inicio > now() ORDER BY a.inicio LIMIT 8"""
    )
    return ok({**r.rows[0], "proximas": proximas.rows})


# ---------------- Asociaciones ----------------


@router.get("/v1/admin/asociaciones", summary="Todas las asociaciones")
async def asociaciones(
    s: Svc, u: Admin, q: Busqueda = None, ciudadId: UuidQuery = None, limite: LimiteAdmin = 50, desplazamiento: Desplazamiento = 0
):
    r = await s.db.query(
        """SELECT aso.id, aso.nombre, aso.verificada, aso.activa, ci.nombre AS ciudad, ca.nombre AS categoria,
                  (SELECT count(*)::int FROM actividades x WHERE x.asociacion_id = aso.id AND x.estado = 'publicada') AS "actividadesPublicadas"
           FROM asociaciones aso JOIN ciudades ci ON ci.id = aso.ciudad_id JOIN categorias ca ON ca.id = aso.categoria_id
           WHERE ($1::text IS NULL OR aso.nombre ILIKE $1) AND ($2::uuid IS NULL OR aso.ciudad_id = $2)
           ORDER BY aso.verificada, aso.nombre LIMIT $3 OFFSET $4""",
        [_patron(q), ciudadId, limite, desplazamiento],
    )
    return ok(r.rows)


@router.get("/v1/admin/asociaciones/{asociacionId}", summary="Ficha completa de una asociación")
async def asociacion(asociacionId: IdRuta, s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT id, nombre, descripcion, mision, necesidades, familias_beneficiadas AS "familiasBeneficiadas",
                  categoria_id AS "categoriaId", ciudad_id AS "ciudadId", direccion, latitud::float8 AS latitud,
                  longitud::float8 AS longitud, telefono, whatsapp, correo, sitio_web AS "sitioWeb", foto_clave AS "fotoClave",
                  verificada, activa
           FROM asociaciones WHERE id = $1""",
        [asociacionId],
    )
    if not r.rows:
        raise no_encontrado("Asociación")
    return ok(r.rows[0])


# ---------------- Actividades ----------------


@router.get("/v1/admin/actividades", summary="Todas las actividades")
async def actividades(
    s: Svc,
    u: Admin,
    q: Busqueda = None,
    estado: Annotated[Literal["borrador", "publicada", "finalizada", "cancelada"] | None, Query()] = None,
    asociacionId: UuidQuery = None,
    limite: LimiteAdmin = 50,
    desplazamiento: Desplazamiento = 0,
):
    r = await s.db.query(
        """SELECT a.id, a.titulo, a.inicio, a.fin, a.estado, a.tipo, a.cupo_total AS "cupoTotal", a.cupos_ocupados AS "cuposOcupados",
                  aso.nombre AS asociacion, ci.nombre AS ciudad
           FROM actividades a JOIN asociaciones aso ON aso.id = a.asociacion_id JOIN ciudades ci ON ci.id = a.ciudad_id
           WHERE ($1::text IS NULL OR a.titulo ILIKE $1 OR aso.nombre ILIKE $1)
             AND ($2::text IS NULL OR a.estado = $2) AND ($3::uuid IS NULL OR a.asociacion_id = $3)
           ORDER BY a.inicio DESC LIMIT $4 OFFSET $5""",
        [_patron(q), estado, asociacionId, limite, desplazamiento],
    )
    return ok(r.rows)


@router.get("/v1/admin/actividades/{actividadId}", summary="Ficha completa de una actividad")
async def actividad(actividadId: IdRuta, s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT id, asociacion_id AS "asociacionId", categoria_id AS "categoriaId", ciudad_id AS "ciudadId", titulo,
                  descripcion_corta AS "descripcionCorta", descripcion, recomendaciones, inicio, fin, direccion,
                  latitud::float8 AS latitud, longitud::float8 AS longitud, apta_ninos AS "aptaNinos", edad_minima AS "edadMinima",
                  cupo_total AS "cupoTotal", cupos_ocupados AS "cuposOcupados", foto_clave AS "fotoClave", tipo, estado,
                  motivo_cancelacion AS "motivoCancelacion"
           FROM actividades WHERE id = $1""",
        [actividadId],
    )
    if not r.rows:
        raise no_encontrado("Actividad")
    return ok(r.rows[0])


# ---------------- Proyectos y campañas ----------------


@router.get("/v1/admin/proyectos", summary="Todos los proyectos")
async def proyectos(s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT pr.id, pr.titulo, pr.estado, pr.fecha_inicio::text AS "fechaInicio", pr.fecha_fin::text AS "fechaFin",
                  aso.nombre AS asociacion, ci.nombre AS ciudad,
                  (SELECT count(*)::int FROM campanas c WHERE c.proyecto_id = pr.id) AS campanas
           FROM proyectos pr LEFT JOIN asociaciones aso ON aso.id = pr.asociacion_id LEFT JOIN ciudades ci ON ci.id = pr.ciudad_id
           ORDER BY pr.fecha_inicio DESC LIMIT 200"""
    )
    return ok(r.rows)


@router.get("/v1/admin/proyectos/{proyectoId}", summary="Ficha completa de un proyecto")
async def proyecto(proyectoId: IdRuta, s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT id, asociacion_id AS "asociacionId", ciudad_id AS "ciudadId", titulo, descripcion,
                  fecha_inicio::text AS "fechaInicio", fecha_fin::text AS "fechaFin", foto_clave AS "fotoClave", estado
           FROM proyectos WHERE id = $1""",
        [proyectoId],
    )
    if not r.rows:
        raise no_encontrado("Proyecto")
    return ok(r.rows[0])


@router.get("/v1/admin/campanas", summary="Todas las campañas")
async def campanas(s: Svc, u: Admin, estado: Annotated[Literal["borrador", "publicada", "finalizada", "cancelada"] | None, Query()] = None):
    r = await s.db.query(
        """SELECT cp.id, cp.titulo, cp.estado, cp.inicio, cp.fin, cp.urgente, aso.nombre AS asociacion, pr.titulo AS proyecto,
                  ci.nombre AS ciudad,
                  COALESCE((SELECT round(avg(LEAST(ar.cantidad_recibida / ar.cantidad_meta, 1)) * 100)::int
                            FROM campana_articulos ar WHERE ar.campana_id = cp.id), 0) AS avance
           FROM campanas cp LEFT JOIN asociaciones aso ON aso.id = cp.asociacion_id LEFT JOIN proyectos pr ON pr.id = cp.proyecto_id
           JOIN ciudades ci ON ci.id = cp.ciudad_id
           WHERE ($1::text IS NULL OR cp.estado = $1)
           ORDER BY cp.inicio DESC LIMIT 200""",
        [estado],
    )
    return ok(r.rows)


# ---------------- Personas ----------------


@router.get("/v1/admin/usuarios", summary="Buscar cuentas")
async def usuarios(
    s: Svc,
    u: Admin,
    q: Busqueda = None,
    rol: Annotated[Literal["familia", "admin"] | None, Query()] = None,
    estado: Annotated[Literal["activo", "suspendido", "pendiente_eliminacion"] | None, Query()] = None,
    limite: LimiteAdmin = 50,
    desplazamiento: Desplazamiento = 0,
):
    """Búsqueda de cuentas para suspender o reactivar. No incluye hashes ni datos de recuperación."""
    r = await s.db.query(
        """SELECT u.id, u.nombre, u.username, u.correo, u.telefono, u.rol, u.estado, u.creado_en AS "creadoEn",
                  u.ultimo_acceso_en AS "ultimoAcceso", ci.nombre AS ciudad
           FROM usuarios u LEFT JOIN ciudades ci ON ci.id = u.ciudad_id
           WHERE u.estado <> 'eliminado'
             AND ($1::text IS NULL OR u.nombre ILIKE $1 OR u.username ILIKE $1 OR u.correo ILIKE $1 OR u.telefono ILIKE $1)
             AND ($2::text IS NULL OR u.rol = $2) AND ($3::text IS NULL OR u.estado = $3)
           ORDER BY u.creado_en DESC LIMIT $4 OFFSET $5""",
        [_patron(q), rol, estado, limite, desplazamiento],
    )
    return ok(r.rows)


# ---------------- Reconocimientos ----------------


@router.get("/v1/admin/niveles", summary="Niveles de reconocimiento")
async def niveles(s: Svc, u: Admin):
    r = await s.db.query(
        'SELECT id, nombre, descripcion, participaciones_minimas AS "participacionesMinimas" FROM niveles ORDER BY participaciones_minimas'
    )
    return ok(r.rows)


@router.get("/v1/admin/insignias", summary="Insignias")
async def insignias(s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT i.id, i.nombre, i.descripcion, i.participaciones_requeridas AS "participacionesRequeridas", i.activa,
                  ca.nombre AS categoria
           FROM insignias i LEFT JOIN categorias ca ON ca.id = i.categoria_id ORDER BY i.participaciones_requeridas"""
    )
    return ok(r.rows)


@router.get("/v1/admin/avisos-privacidad", summary="Versiones del aviso de privacidad")
async def avisos(s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT id, version, publicado_en AS "publicadoEn", length(contenido)::int AS caracteres,
                  (SELECT count(*)::int FROM aceptaciones_privacidad ap WHERE ap.aviso_id = av.id) AS aceptaciones
           FROM avisos_privacidad av ORDER BY publicado_en DESC"""
    )
    return ok(r.rows)
