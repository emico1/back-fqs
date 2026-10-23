"""Propuestas, reportes, notificaciones, testimonios, valoraciones y encuestas."""

from typing import Annotated, Literal

from fastapi import Request
from pydantic import Field, model_validator

from ..errores import HttpError, no_encontrado
from ..http.dependencias import Svc, Usuario
from ..idempotencia import con_idempotencia
from ..limites import ESCRITURA, cuenta_de, limiter
from ..validacion import Correo, Desplazamiento, Limite, Modelo, Telefono, Texto, TextoOpcional, Uuid
from .comun import ClaveIdempotencia, IdRuta, creado, nuevo_router, ok, sin_contenido
from .consultas import ciudad_del_usuario, exigir_archivo_propio

router = nuevo_router("comunidad y propuestas")


class Propuesta(Modelo):
    tipo: Literal["actividad", "asociacion", "iniciativa_vecinal"]
    titulo: Texto(3, 150)
    descripcion: Texto(10, 3000)
    ciudadId: Uuid | None = None
    ubicacion: TextoOpcional(200)
    contactoNombre: TextoOpcional(120)
    contactoCorreo: Correo | None = None
    contactoTelefono: Telefono | None = None


class Reporte(Modelo):
    tipo: Literal[
        "problema_actividad",
        "problema_asociacion",
        "problema_campana",
        "problema_aplicacion",
        "comportamiento_inapropiado",
        "otro",
    ]
    nivelSatisfaccion: Annotated[int, Field(ge=1, le=5)] | None = None
    descripcion: Texto(10, 3000)
    actividadId: Uuid | None = None
    asociacionId: Uuid | None = None
    campanaId: Uuid | None = None
    fotoClave: Uuid | None = None


class Testimonio(Modelo):
    texto: Texto(10, 1500)
    fotoClave: Uuid


class Valoracion(Modelo):
    valor: Literal[1, -1]


class Respuesta(Modelo):
    preguntaId: Uuid
    opcionId: Uuid | None = None
    texto: TextoOpcional(2000)

    @model_validator(mode="after")
    def _una_forma(self) -> "Respuesta":
        if bool(self.opcionId) == bool(self.texto):
            raise ValueError("Responde con una opción o con texto, no ambos")
        return self


class Respuestas(Modelo):
    respuestas: Annotated[list[Respuesta], Field(min_length=1, max_length=50)]


COLUMNAS_PROPUESTA = """p.id, p.tipo, p.titulo, p.descripcion, p.ciudad_id AS "ciudadId", p.ubicacion,
  p.contacto_nombre AS "contactoNombre", p.contacto_correo AS "contactoCorreo", p.contacto_telefono AS "contactoTelefono",
  p.estado, p.comentario_admin AS "comentarioAdmin", p.creado_en AS "creadoEn", p.revisado_en AS "revisadoEn\""""


async def _inscripcion_propia(s, inscripcion_id: str, usuario_id: str) -> dict:  # noqa: ANN001
    """Devuelve la inscripción solo si pertenece al usuario de la sesión."""
    r = await s.db.query("SELECT id, actividad_id FROM inscripciones WHERE id = $1 AND usuario_id = $2", [inscripcion_id, usuario_id])
    if not r.rows:
        raise no_encontrado("Inscripción")
    return r.rows[0]


# ---------------- Propuestas ----------------


@router.get("/v1/propuestas", summary="Mis propuestas")
async def propuestas(s: Svc, u: Usuario):
    r = await s.db.query(f"SELECT {COLUMNAS_PROPUESTA} FROM propuestas p WHERE p.usuario_id = $1 ORDER BY p.creado_en DESC LIMIT 100", [u.id])
    return ok(r.rows)


async def _revisar_duplicado(s, tipo: str, titulo: str, ciudad_id: str | None, usuario_id: str) -> None:  # noqa: ANN001
    """
    Error diseñado de CP-01. Si se propone una asociación que ya está registrada en la ciudad, o
    que la misma familia ya propuso y sigue abierta, se avisa en lugar de crear un duplicado.
    La comparación ignora mayúsculas, acentos, signos y "A.C.".
    """
    if tipo == "asociacion":
        a = await s.db.query(
            """SELECT id, nombre, verificada FROM asociaciones
               WHERE activa AND ($2::uuid IS NULL OR ciudad_id = $2) AND normalizar_nombre(nombre) = normalizar_nombre($1)
               LIMIT 1""",
            [titulo, ciudad_id],
        )
        if a.rows:
            e = a.rows[0]
            raise HttpError(
                409,
                "asociacion_existente",
                f"{e['nombre']} ya está registrada en Familias que Suman, puedes encontrarla en Explorar"
                if e["verificada"]
                else f"{e['nombre']} ya está registrada y el equipo la está revisando",
                {"asociacionId": e["id"] if e["verificada"] else None, "nombre": e["nombre"]},
            )
    p = await s.db.query(
        """SELECT id FROM propuestas
           WHERE usuario_id = $1 AND tipo = $2 AND estado IN ('en_revision','necesita_cambios')
             AND normalizar_nombre(titulo) = normalizar_nombre($3)
           LIMIT 1""",
        [usuario_id, tipo, titulo],
    )
    if p.rows:
        raise HttpError(409, "propuesta_duplicada", "Ya enviaste una propuesta con ese nombre y sigue en revisión", {"propuestaId": p.rows[0]["id"]})


@router.post("/v1/propuestas", summary="Proponer una actividad, asociación o iniciativa")
@limiter.shared_limit(ESCRITURA, scope="escritura", key_func=cuenta_de)
async def proponer(request: Request, d: Propuesta, s: Svc, u: Usuario, clave: ClaveIdempotencia = None):
    async def hacer():  # noqa: ANN202
        # Si la app no manda ciudad se usa la del perfil
        c = await s.db.query("SELECT ciudad_id FROM usuarios WHERE id = $1", [u.id])
        ciudad_id = d.ciudadId or (c.rows[0]["ciudad_id"] if c.rows else None)
        await _revisar_duplicado(s, d.tipo, d.titulo, ciudad_id, u.id)
        r = await s.db.query(
            f"""INSERT INTO propuestas AS p (usuario_id, tipo, titulo, descripcion, ciudad_id, ubicacion, contacto_nombre, contacto_correo, contacto_telefono)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING {COLUMNAS_PROPUESTA}""",
            [u.id, d.tipo, d.titulo, d.descripcion, ciudad_id, d.ubicacion, d.contactoNombre, d.contactoCorreo, d.contactoTelefono],
        )
        return creado(r.rows[0])

    return await con_idempotencia(request, s.db, u.id, d, hacer)


@router.get("/v1/propuestas/{propuestaId}", summary="Detalle de mi propuesta con su historial")
async def propuesta(propuestaId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(f"SELECT {COLUMNAS_PROPUESTA} FROM propuestas p WHERE p.id = $1 AND p.usuario_id = $2", [propuestaId, u.id])
    if not r.rows:
        raise no_encontrado("Propuesta")
    h = await s.db.query(
        """SELECT estado, comentario, cambiado_en AS "cambiadoEn" FROM propuesta_historial
           WHERE propuesta_id = $1 ORDER BY cambiado_en, id""",
        [propuestaId],
    )
    return ok({**r.rows[0], "historial": h.rows})


@router.put("/v1/propuestas/{propuestaId}", summary="Corregir una propuesta cuando el equipo pidió cambios")
async def editar_propuesta(propuestaId: IdRuta, d: Propuesta, s: Svc, u: Usuario):
    # Solo se puede editar cuando el equipo pidió cambios, y al guardar vuelve a revisión
    r = await s.db.query(
        f"""UPDATE propuestas p SET tipo = $3, titulo = $4, descripcion = $5, ciudad_id = $6, ubicacion = $7,
                   contacto_nombre = $8, contacto_correo = $9, contacto_telefono = $10, estado = 'en_revision'
            WHERE p.id = $1 AND p.usuario_id = $2 AND p.estado = 'necesita_cambios'
            RETURNING {COLUMNAS_PROPUESTA}""",
        [propuestaId, u.id, d.tipo, d.titulo, d.descripcion, d.ciudadId, d.ubicacion, d.contactoNombre, d.contactoCorreo, d.contactoTelefono],
    )
    if not r.rows:
        raise HttpError(409, "no_editable", "La propuesta no existe o no está esperando cambios")
    return ok(r.rows[0])


# ---------------- Reportes ----------------


@router.post("/v1/reportes", summary="Reportar una experiencia o un problema")
@limiter.shared_limit(ESCRITURA, scope="escritura", key_func=cuenta_de)
async def reportar(request: Request, d: Reporte, s: Svc, u: Usuario, clave: ClaveIdempotencia = None):
    async def hacer():  # noqa: ANN202
        await exigir_archivo_propio(s.db, d.fotoClave, u.id)
        r = await s.db.query(
            """INSERT INTO reportes_experiencia (usuario_id, tipo, nivel_satisfaccion, descripcion, actividad_id, asociacion_id, campana_id, foto_clave)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id, estado, creado_en AS "creadoEn\"""",
            [u.id, d.tipo, d.nivelSatisfaccion, d.descripcion, d.actividadId, d.asociacionId, d.campanaId, d.fotoClave],
        )
        return creado(r.rows[0])

    return await con_idempotencia(request, s.db, u.id, d, hacer)


# ---------------- Notificaciones ----------------


@router.get("/v1/notificaciones", summary="Mis notificaciones")
async def notificaciones(s: Svc, u: Usuario, limite: Limite = 50, desplazamiento: Desplazamiento = 0):
    r = await s.db.query(
        """SELECT id, tipo, titulo, mensaje, (leida_en IS NOT NULL) AS leida, creado_en AS "creadoEn",
                  actividad_id AS "actividadId", asociacion_id AS "asociacionId",
                  propuesta_id AS "propuestaId", campana_id AS "campanaId"
           FROM notificaciones WHERE usuario_id = $1 ORDER BY creado_en DESC LIMIT $2 OFFSET $3""",
        [u.id, limite, desplazamiento],
    )
    return ok(r.rows)


@router.post("/v1/notificaciones/{notificacionId}/leida", summary="Marcar una notificación como leída")
async def marcar_leida(notificacionId: IdRuta, s: Svc, u: Usuario):
    await s.db.query("UPDATE notificaciones SET leida_en = now() WHERE id = $1 AND usuario_id = $2 AND leida_en IS NULL", [notificacionId, u.id])
    return sin_contenido()


@router.post("/v1/notificaciones/leer-todas", summary="Marcar todas como leídas")
async def leer_todas(s: Svc, u: Usuario):
    await s.db.query("UPDATE notificaciones SET leida_en = now() WHERE usuario_id = $1 AND leida_en IS NULL", [u.id])
    return sin_contenido()


@router.delete("/v1/notificaciones/{notificacionId}", summary="Borrar una notificación")
async def borrar_notificacion(notificacionId: IdRuta, s: Svc, u: Usuario):
    await s.db.query("DELETE FROM notificaciones WHERE id = $1 AND usuario_id = $2", [notificacionId, u.id])
    return sin_contenido()


# ---------------- Testimonios y valoraciones ----------------


@router.post("/v1/yo/inscripciones/{inscripcionId}/testimonio", summary="Publicar mi experiencia de una actividad")
@limiter.shared_limit(ESCRITURA, scope="escritura", key_func=cuenta_de)
async def testimonio(request: Request, inscripcionId: IdRuta, d: Testimonio, s: Svc, u: Usuario, clave: ClaveIdempotencia = None):
    async def hacer():  # noqa: ANN202
        await _inscripcion_propia(s, inscripcionId, u.id)
        await exigir_archivo_propio(s.db, d.fotoClave, u.id)
        # El trigger exige asistencia confirmada por un administrador
        r = await s.db.query(
            """INSERT INTO testimonios (inscripcion_id, texto, foto_clave) VALUES ($1, $2, $3)
               RETURNING id, estado, creado_en AS "creadoEn\"""",
            [inscripcionId, d.texto, d.fotoClave],
        )
        return creado(r.rows[0])

    return await con_idempotencia(request, s.db, u.id, d, hacer)


@router.put("/v1/yo/inscripciones/{inscripcionId}/valoracion", summary="Me gustó o no me gustó")
async def valorar(inscripcionId: IdRuta, d: Valoracion, s: Svc, u: Usuario):
    await _inscripcion_propia(s, inscripcionId, u.id)
    await s.db.query(
        """INSERT INTO valoraciones_actividades (inscripcion_id, valor) VALUES ($1, $2)
           ON CONFLICT (inscripcion_id) DO UPDATE SET valor = EXCLUDED.valor""",
        [inscripcionId, d.valor],
    )
    return sin_contenido()


@router.delete("/v1/yo/inscripciones/{inscripcionId}/valoracion", summary="Quitar mi valoración")
async def quitar_valoracion(inscripcionId: IdRuta, s: Svc, u: Usuario):
    await _inscripcion_propia(s, inscripcionId, u.id)
    await s.db.query("DELETE FROM valoraciones_actividades WHERE inscripcion_id = $1", [inscripcionId])
    return sin_contenido()


@router.get("/v1/testimonios", summary="Historias de la comunidad de mi ciudad")
async def testimonios(s: Svc, u: Usuario, limite: Limite = 20, desplazamiento: Desplazamiento = 0):
    """Historias de la comunidad (RF-12). Solo testimonios aprobados de la ciudad de la familia."""
    r = await s.db.query(
        f"""SELECT t.id, t.texto, t.foto_clave AS "fotoClave", t.creado_en AS "creadoEn", u.username,
                   json_build_object('id', a.id, 'titulo', a.titulo, 'tipo', a.tipo) AS actividad,
                   aso.nombre AS asociacion
            FROM testimonios t
            JOIN inscripciones i ON i.id = t.inscripcion_id
            JOIN usuarios u ON u.id = i.usuario_id
            JOIN actividades a ON a.id = i.actividad_id
            JOIN asociaciones aso ON aso.id = a.asociacion_id
            WHERE t.estado = 'aprobado' AND u.estado = 'activo'
              AND ($4 OR a.ciudad_id = {ciudad_del_usuario(3)})
            ORDER BY t.revisado_en DESC, t.id
            LIMIT $1 OFFSET $2""",
        [limite, desplazamiento, u.id, u.rol == "admin"],
    )
    return ok(r.rows)


@router.get("/v1/actividades/{actividadId}/testimonios", summary="Testimonios aprobados de una actividad")
async def testimonios_actividad(actividadId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(
        """SELECT t.id, t.texto, t.foto_clave AS "fotoClave", t.creado_en AS "creadoEn", u.username
           FROM testimonios t
           JOIN inscripciones i ON i.id = t.inscripcion_id
           JOIN usuarios u ON u.id = i.usuario_id
           WHERE i.actividad_id = $1 AND t.estado = 'aprobado' AND u.estado = 'activo'
           ORDER BY t.creado_en DESC LIMIT 50""",
        [actividadId],
    )
    return ok(r.rows)


# ---------------- Encuestas ----------------


@router.get("/v1/actividades/{actividadId}/encuestas", summary="Encuestas activas de una actividad")
async def encuestas(actividadId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(
        """SELECT e.id, e.titulo, e.momento,
                  COALESCE((SELECT json_agg(json_build_object(
                      'id', p.id, 'texto', p.texto, 'tipo', p.tipo, 'obligatoria', p.obligatoria, 'orden', p.orden,
                      'opciones', COALESCE((SELECT json_agg(json_build_object('id', o.id, 'texto', o.texto) ORDER BY o.orden)
                                            FROM opciones_pregunta o WHERE o.pregunta_id = p.id), '[]'),
                      'respondida', EXISTS (SELECT 1 FROM respuestas_encuesta re JOIN inscripciones i ON i.id = re.inscripcion_id
                                            WHERE re.pregunta_id = p.id AND i.usuario_id = $2)
                    ) ORDER BY p.orden) FROM preguntas_encuesta p WHERE p.encuesta_id = e.id), '[]') AS preguntas
           FROM encuestas e WHERE e.actividad_id = $1 AND e.activa ORDER BY e.momento""",
        [actividadId, u.id],
    )
    return ok(r.rows)


@router.post("/v1/yo/inscripciones/{inscripcionId}/respuestas", summary="Responder una encuesta")
@limiter.shared_limit(ESCRITURA, scope="escritura", key_func=cuenta_de)
async def responder(request: Request, inscripcionId: IdRuta, d: Respuestas, s: Svc, u: Usuario):
    await _inscripcion_propia(s, inscripcionId, u.id)
    # El trigger valida que la encuesta sea de esa actividad, esté activa y el momento
    async with s.db.transaccion() as c:
        for r in d.respuestas:
            await c.query(
                "INSERT INTO respuestas_encuesta (inscripcion_id, pregunta_id, opcion_id, respuesta_texto) VALUES ($1, $2, $3, $4)",
                [inscripcionId, r.preguntaId, r.opcionId, r.texto],
            )
    return sin_contenido()
