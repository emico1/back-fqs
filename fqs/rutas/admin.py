"""
Administración. Altas y cambios de catálogos, asociaciones, actividades, proyectos, campañas,
encuestas, moderación y derechos ARCO. Todas exigen rol de administración y, si está en
obligatorio, segundo factor. Cada cambio queda en la bitácora (ver http/ruta.py).
"""

import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Query
from pydantic import AfterValidator, Field, model_validator

from ..avisos_acompanantes import avisar_cancelacion, destinatarios_actividad
from ..errores import HttpError, no_encontrado
from ..http.dependencias import Admin, Svc
from ..seguridad.sesiones import revocar_todas
from ..tareas import en_segundo_plano
from ..validacion import (
    Booleano,
    ClaveCategoria,
    Correo,
    Desplazamiento,
    Entero,
    Fecha,
    Instante,
    Modelo,
    Numero,
    Telefono,
    Texto,
    TextoOpcional,
    Uuid,
    error_validacion,
)
from .comun import IdRuta, creado, nuevo_router, ok, sin_contenido
from .consultas import calidad_asociacion, exigir_archivo_de_administracion, votos_asociacion

router = nuevo_router("admin")

Latitud = Annotated[Numero, Field(ge=-90, le=90)]
Longitud = Annotated[Numero, Field(ge=-180, le=180)]


def _sitio_web(v: str) -> str:
    if not re.fullmatch(r"https://[^\s/$.?#][^\s]*", v):
        raise ValueError("Debe ser una dirección https válida")
    return v


SitioWeb = Annotated[str, Field(max_length=300), AfterValidator(_sitio_web)]
LimiteAdmin = Annotated[int, Query(ge=1, le=50)]


class Ciudad(Modelo):
    nombre: Texto(2, 100)
    estado: Texto(2, 100)
    zonaHoraria: Texto(3, 60)


class Categoria(Modelo):
    clave: ClaveCategoria
    nombre: Texto(2, 60)
    descripcion: TextoOpcional(300)
    activa: Booleano = True


class Aviso(Modelo):
    version: Texto(1, 30)
    contenido: Texto(50, 100_000)


class Nivel(Modelo):
    nombre: Texto(2, 80)
    descripcion: TextoOpcional(500)
    participacionesMinimas: Annotated[Entero, Field(ge=0, le=100_000)]


class Insignia(Modelo):
    nombre: Texto(2, 80)
    descripcion: Texto(5, 500)
    imagenClave: Uuid | None = None
    categoriaId: Uuid | None = None
    participacionesRequeridas: Annotated[Entero, Field(ge=1, le=100_000)]


class Asociacion(Modelo):
    nombre: Texto(2, 150)
    descripcion: Texto(10, 2000)
    mision: TextoOpcional(3000)
    necesidades: TextoOpcional(3000)
    familiasBeneficiadas: Annotated[Entero, Field(ge=0, le=10_000_000)] = 0
    categoriaId: Uuid
    ciudadId: Uuid
    direccion: Texto(5, 300)
    latitud: Latitud | None = None
    longitud: Longitud | None = None
    telefono: Telefono | None = None
    whatsapp: Telefono | None = None
    correo: Correo | None = None
    sitioWeb: SitioWeb | None = None
    fotoClave: Uuid | None = None
    verificada: Booleano = False
    activa: Booleano = True


class Actividad(Modelo):
    asociacionId: Uuid
    categoriaId: Uuid
    ciudadId: Uuid
    titulo: Texto(3, 150)
    descripcionCorta: Texto(5, 200)
    descripcion: Texto(10, 5000)
    recomendaciones: TextoOpcional(2000)
    inicio: Instante
    fin: Instante
    direccion: Texto(5, 300)
    latitud: Latitud | None = None
    longitud: Longitud | None = None
    aptaNinos: Booleano = False
    edadMinima: Annotated[Entero, Field(ge=0, le=120)] | None = None
    cupoTotal: Annotated[Entero, Field(ge=1, le=100_000)]
    fotoClave: Uuid | None = None
    # voluntariado (Participar) o visita (Visiteo)
    tipo: Literal["voluntariado", "visita"] = "voluntariado"


class Proyecto(Modelo):
    asociacionId: Uuid | None = None
    ciudadId: Uuid
    titulo: Texto(3, 150)
    descripcion: Texto(10, 3000)
    fechaInicio: Fecha
    fechaFin: Fecha | None = None
    fotoClave: Uuid | None = None


class Articulo(Modelo):
    nombre: Texto(2, 120)
    descripcion: TextoOpcional(500)
    unidad: Texto(1, 30)
    cantidadMeta: Annotated[Numero, Field(gt=0, le=1_000_000_000)]
    prioridad: Literal["baja", "media", "alta", "urgente"] = "media"


class PuntoEntrega(Modelo):
    ciudadId: Uuid
    nombre: Texto(2, 150)
    direccion: Texto(5, 300)
    horarios: Texto(3, 500)
    indicaciones: TextoOpcional(500)
    latitud: Latitud | None = None
    longitud: Longitud | None = None


class Campana(Modelo):
    asociacionId: Uuid | None = None
    proyectoId: Uuid | None = None
    ciudadId: Uuid
    titulo: Texto(3, 150)
    descripcion: Texto(10, 3000)
    inicio: Instante
    fin: Instante
    urgente: Booleano = False
    fotoClave: Uuid | None = None
    articulos: Annotated[list[Articulo], Field(min_length=1, max_length=50)]
    puntosEntrega: Annotated[list[PuntoEntrega], Field(min_length=1, max_length=20)]


class Pregunta(Modelo):
    texto: Texto(3, 500)
    tipo: Literal["texto", "opcion_unica"]
    obligatoria: Booleano = True
    opciones: Annotated[list[Texto(1, 200)], Field(max_length=20)] = []

    @model_validator(mode="after")
    def _opciones(self) -> "Pregunta":
        if (len(self.opciones) < 2) if self.tipo == "opcion_unica" else (len(self.opciones) != 0):
            raise ValueError("Las preguntas de opción única llevan al menos 2 opciones y las de texto ninguna")
        return self


class Encuesta(Modelo):
    actividadId: Uuid
    titulo: Texto(3, 150)
    momento: Literal["antes", "despues"]
    preguntas: Annotated[list[Pregunta], Field(min_length=1, max_length=30)]


class Motivo(Modelo):
    motivo: Texto(3, 500)


class EstadoActividad(Modelo):
    estado: Literal["borrador", "publicada", "finalizada"]


class EstadoProyecto(Modelo):
    estado: Literal["borrador", "publicado", "finalizado", "cancelado"]


class EstadoCampana(Modelo):
    estado: Literal["borrador", "publicada", "finalizada", "cancelada"]


class Asistencia(Modelo):
    estado: Literal["pendiente", "asistio", "no_asistio"]


class EstadoEntrega(Modelo):
    estado: Literal["recibida", "cancelada", "registrada"]


class RevisionPropuesta(Modelo):
    estado: Literal["necesita_cambios", "aprobada", "rechazada", "completada"]
    comentario: TextoOpcional(2000)


class RevisionTestimonio(Modelo):
    estado: Literal["aprobado", "rechazado"]
    comentario: TextoOpcional(1000)


class AtencionReporte(Modelo):
    estado: Literal["en_revision", "resuelto"]
    respuesta: TextoOpcional(2000)


class EstadoUsuario(Modelo):
    estado: Literal["activo", "suspendido"]


class EstadoEncuesta(Modelo):
    activa: Booleano


async def _notificar(s, usuario_id: str, tipo: str, titulo: str, mensaje: str, propuesta_id: str | None = None) -> None:  # noqa: ANN001
    await s.db.query(
        """INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, actividad_id, propuesta_id, campana_id)
           VALUES ($1, $2, $3, $4, NULL, $5, NULL)""",
        [usuario_id, tipo, titulo, mensaje, propuesta_id],
    )


# ---------------- Catálogos y privacidad ----------------


@router.post("/v1/admin/ciudades", summary="Agregar una ciudad")
async def nueva_ciudad(d: Ciudad, s: Svc, u: Admin):
    zona = await s.db.query("SELECT 1 FROM pg_timezone_names WHERE name = $1", [d.zonaHoraria])
    if not zona.rows:
        raise HttpError(422, "zona_invalida", "Zona horaria desconocida")
    r = await s.db.query(
        "INSERT INTO ciudades (nombre, estado, zona_horaria) VALUES ($1, $2, $3) RETURNING id", [d.nombre, d.estado, d.zonaHoraria]
    )
    return creado(r.rows[0])


@router.post("/v1/admin/categorias", summary="Agregar una categoría")
async def nueva_categoria(d: Categoria, s: Svc, u: Admin):
    r = await s.db.query(
        "INSERT INTO categorias (clave, nombre, descripcion, activa) VALUES ($1, $2, $3, $4) RETURNING id",
        [d.clave, d.nombre, d.descripcion, d.activa],
    )
    return creado(r.rows[0])


@router.post("/v1/admin/avisos-privacidad", summary="Publicar una versión nueva del aviso de privacidad")
async def nuevo_aviso(d: Aviso, s: Svc, u: Admin):
    r = await s.db.query(
        'INSERT INTO avisos_privacidad (version, contenido) VALUES ($1, $2) RETURNING id, publicado_en AS "publicadoEn"',
        [d.version, d.contenido],
    )
    return creado(r.rows[0])


@router.post("/v1/admin/niveles", summary="Agregar un nivel de reconocimiento")
async def nuevo_nivel(d: Nivel, s: Svc, u: Admin):
    r = await s.db.query(
        "INSERT INTO niveles (nombre, descripcion, participaciones_minimas) VALUES ($1, $2, $3) RETURNING id",
        [d.nombre, d.descripcion, d.participacionesMinimas],
    )
    return creado(r.rows[0])


@router.post("/v1/admin/insignias", summary="Agregar una insignia")
async def nueva_insignia(d: Insignia, s: Svc, u: Admin):
    await exigir_archivo_de_administracion(s.db, d.imagenClave)
    r = await s.db.query(
        """INSERT INTO insignias (nombre, descripcion, imagen_clave, categoria_id, participaciones_requeridas)
           VALUES ($1, $2, $3, $4, $5) RETURNING id""",
        [d.nombre, d.descripcion, d.imagenClave, d.categoriaId, d.participacionesRequeridas],
    )
    return creado(r.rows[0])


# ---------------- Asociaciones ----------------


async def _guardar_asociacion(s, u, d: Asociacion, asociacion_id: str | None):  # noqa: ANN001, ANN202
    await exigir_archivo_de_administracion(s.db, d.fotoClave)
    valores = [
        d.nombre, d.descripcion, d.mision, d.necesidades, d.familiasBeneficiadas, d.categoriaId,
        d.ciudadId, d.direccion, d.latitud, d.longitud, d.telefono, d.whatsapp,
        d.correo, d.sitioWeb, d.fotoClave, d.verificada, d.activa,
    ]  # fmt: skip
    if not asociacion_id:
        r = await s.db.query(
            """INSERT INTO asociaciones (nombre, descripcion, mision, necesidades, familias_beneficiadas, categoria_id, ciudad_id,
                 direccion, latitud, longitud, telefono, whatsapp, correo, sitio_web, foto_clave, verificada, activa, creado_por)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) RETURNING id""",
            [*valores, u.id],
        )
        return creado(r.rows[0])
    r = await s.db.query(
        """UPDATE asociaciones SET nombre=$1, descripcion=$2, mision=$3, necesidades=$4, familias_beneficiadas=$5, categoria_id=$6,
             ciudad_id=$7, direccion=$8, latitud=$9, longitud=$10, telefono=$11, whatsapp=$12, correo=$13, sitio_web=$14,
             foto_clave=$15, verificada=$16, activa=$17
           WHERE id = $18 RETURNING id""",
        [*valores, asociacion_id],
    )
    if not r.rows:
        raise no_encontrado("Asociación")
    return ok(r.rows[0])


@router.post("/v1/admin/asociaciones", summary="Agregar una asociación")
async def nueva_asociacion(d: Asociacion, s: Svc, u: Admin):
    return await _guardar_asociacion(s, u, d, None)


@router.put("/v1/admin/asociaciones/{asociacionId}", summary="Editar una asociación")
async def editar_asociacion(asociacionId: IdRuta, d: Asociacion, s: Svc, u: Admin):
    return await _guardar_asociacion(s, u, d, asociacionId)


# ---------------- Actividades ----------------


async def _guardar_actividad(s, u, d: Actividad, actividad_id: str | None):  # noqa: ANN001, ANN202
    await exigir_archivo_de_administracion(s.db, d.fotoClave)
    valores = [
        d.asociacionId, d.categoriaId, d.ciudadId, d.titulo, d.descripcionCorta, d.descripcion, d.recomendaciones,
        d.inicio, d.fin, d.direccion, d.latitud, d.longitud, d.aptaNinos, d.edadMinima,
        d.cupoTotal, d.fotoClave, d.tipo,
    ]  # fmt: skip
    if not actividad_id:
        r = await s.db.query(
            """INSERT INTO actividades (asociacion_id, categoria_id, ciudad_id, titulo, descripcion_corta, descripcion,
                 recomendaciones, inicio, fin, direccion, latitud, longitud, apta_ninos, edad_minima, cupo_total, foto_clave, tipo, creado_por)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) RETURNING id, estado""",
            [*valores, u.id],
        )
        return creado(r.rows[0])
    r = await s.db.query(
        """UPDATE actividades SET asociacion_id=$1, categoria_id=$2, ciudad_id=$3, titulo=$4, descripcion_corta=$5, descripcion=$6,
             recomendaciones=$7, inicio=$8, fin=$9, direccion=$10, latitud=$11, longitud=$12, apta_ninos=$13, edad_minima=$14,
             cupo_total=$15, foto_clave=$16, tipo=$17
           WHERE id = $18 AND estado <> 'cancelada' RETURNING id, estado""",
        [*valores, actividad_id],
    )
    if not r.rows:
        raise no_encontrado("Actividad editable")
    return ok(r.rows[0])


@router.post("/v1/admin/actividades", summary="Agregar una actividad")
async def nueva_actividad(d: Actividad, s: Svc, u: Admin):
    return await _guardar_actividad(s, u, d, None)


@router.put("/v1/admin/actividades/{actividadId}", summary="Editar una actividad")
async def editar_actividad(actividadId: IdRuta, d: Actividad, s: Svc, u: Admin):
    return await _guardar_actividad(s, u, d, actividadId)


@router.post("/v1/admin/actividades/{actividadId}/estado", summary="Cambiar el estado de una actividad")
async def estado_actividad(actividadId: IdRuta, d: EstadoActividad, s: Svc, u: Admin):
    r = await s.db.query(
        "UPDATE actividades SET estado = $2 WHERE id = $1 AND estado <> 'cancelada' RETURNING id, estado", [actividadId, d.estado]
    )
    if not r.rows:
        raise no_encontrado("Actividad")
    return ok(r.rows[0])


@router.post("/v1/admin/actividades/{actividadId}/cancelar", summary="Cancelar una actividad y avisar a las familias")
async def cancelar_actividad(actividadId: IdRuta, d: Motivo, s: Svc, u: Admin):
    # Se toma la lista antes de cancelar, después las inscripciones ya no están confirmadas
    acompanantes = await destinatarios_actividad(s.db, actividadId)
    r = await s.db.query("SELECT cancelar_actividad($1, $2, $3) AS n", [u.id, actividadId, d.motivo])
    en_segundo_plano(avisar_cancelacion(s, actividadId, acompanantes, d.motivo), "los avisos de cancelación a acompañantes")
    return ok({"inscripcionesCanceladas": (r.rows[0]["n"] if r.rows else 0) or 0, "acompanantesAvisados": len(acompanantes)})


@router.get("/v1/admin/actividades/{actividadId}/participantes", summary="Participantes de una actividad")
async def participantes(actividadId: IdRuta, s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT p.id, p.nombre, p.edad_al_evento AS "edadAlEvento", p.es_titular AS "esTitular",
                  p.estado_asistencia AS "estadoAsistencia", i.id AS "inscripcionId", i.estado AS "estadoInscripcion",
                  u.nombre AS "titularNombre", u.telefono AS "titularTelefono", u.correo AS "titularCorreo"
           FROM inscripcion_participantes p
           JOIN inscripciones i ON i.id = p.inscripcion_id
           JOIN usuarios u ON u.id = i.usuario_id
           WHERE i.actividad_id = $1 ORDER BY u.nombre, p.es_titular DESC, p.nombre""",
        [actividadId],
    )
    return ok(r.rows)


@router.put("/v1/admin/participantes/{participanteId}/asistencia", summary="Registrar la asistencia de un participante")
async def asistencia(participanteId: IdRuta, d: Asistencia, s: Svc, u: Admin):
    r = await s.db.query(
        """UPDATE inscripcion_participantes SET estado_asistencia = $2,
                  asistencia_registrada_por = CASE WHEN $2 = 'pendiente' THEN NULL ELSE $3::uuid END,
                  asistencia_registrada_en = CASE WHEN $2 = 'pendiente' THEN NULL ELSE now() END
           WHERE id = $1 RETURNING id, estado_asistencia AS "estadoAsistencia\"""",
        [participanteId, d.estado, u.id],
    )
    if not r.rows:
        raise no_encontrado("Participante")
    return ok(r.rows[0])


@router.post("/v1/admin/encuestas", summary="Crear una encuesta")
async def nueva_encuesta(d: Encuesta, s: Svc, u: Admin):
    async with s.db.transaccion() as c:
        e = await c.query("INSERT INTO encuestas (actividad_id, titulo, momento) VALUES ($1, $2, $3) RETURNING id", [d.actividadId, d.titulo, d.momento])
        eid = e.rows[0]["id"]
        for i, p in enumerate(d.preguntas):
            q = await c.query(
                "INSERT INTO preguntas_encuesta (encuesta_id, texto, tipo, obligatoria, orden) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                [eid, p.texto, p.tipo, p.obligatoria, i + 1],
            )
            for j, o in enumerate(p.opciones):
                await c.query("INSERT INTO opciones_pregunta (pregunta_id, texto, orden) VALUES ($1, $2, $3)", [q.rows[0]["id"], o, j + 1])
    return creado({"id": eid})


@router.get("/v1/admin/actividades/{actividadId}/encuestas", summary="Encuestas de una actividad con su avance")
async def encuestas_actividad(actividadId: IdRuta, s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT e.id, e.titulo, e.momento, e.activa,
                  (SELECT count(DISTINCT re.inscripcion_id)::int FROM respuestas_encuesta re
                   JOIN preguntas_encuesta q ON q.id = re.pregunta_id WHERE q.encuesta_id = e.id) AS respondieron,
                  (SELECT count(*)::int FROM inscripciones i WHERE i.actividad_id = e.actividad_id AND i.estado = 'confirmada') AS inscritas
           FROM encuestas e WHERE e.actividad_id = $1 ORDER BY e.momento""",
        [actividadId],
    )
    return ok(r.rows)


@router.get("/v1/admin/encuestas/{encuestaId}/resultados", summary="Resultados de una encuesta")
async def resultados(encuestaId: IdRuta, s: Svc, u: Admin):
    """
    Resultados de una encuesta (RF-13). Las de opción única se resumen en conteos y las de
    texto se listan sin el nombre de quien respondió.
    """
    e = await s.db.query(
        """SELECT e.id, e.titulo, e.momento, e.activa, a.id AS "actividadId", a.titulo AS actividad
           FROM encuestas e JOIN actividades a ON a.id = e.actividad_id WHERE e.id = $1""",
        [encuestaId],
    )
    if not e.rows:
        raise no_encontrado("Encuesta")
    preguntas = await s.db.query(
        """SELECT q.id, q.texto, q.tipo, q.orden,
                  (SELECT count(*)::int FROM respuestas_encuesta re WHERE re.pregunta_id = q.id) AS respuestas,
                  COALESCE((SELECT json_agg(json_build_object('id', o.id, 'texto', o.texto,
                              'total', (SELECT count(*)::int FROM respuestas_encuesta re WHERE re.opcion_id = o.id)) ORDER BY o.orden)
                            FROM opciones_pregunta o WHERE o.pregunta_id = q.id), '[]') AS opciones,
                  COALESCE((SELECT json_agg(t.respuesta_texto ORDER BY t.respondida_en DESC)
                            FROM (SELECT re.respuesta_texto, re.respondida_en FROM respuestas_encuesta re
                                  WHERE re.pregunta_id = q.id AND re.respuesta_texto IS NOT NULL
                                  ORDER BY re.respondida_en DESC LIMIT 200) t), '[]') AS textos
           FROM preguntas_encuesta q WHERE q.encuesta_id = $1 ORDER BY q.orden""",
        [encuestaId],
    )
    return ok({**e.rows[0], "preguntas": preguntas.rows})


@router.post("/v1/admin/encuestas/{encuestaId}/estado", summary="Activar o desactivar una encuesta")
async def estado_encuesta(encuestaId: IdRuta, d: EstadoEncuesta, s: Svc, u: Admin):
    r = await s.db.query("UPDATE encuestas SET activa = $2 WHERE id = $1 RETURNING id, activa", [encuestaId, d.activa])
    if not r.rows:
        raise no_encontrado("Encuesta")
    return ok(r.rows[0])


@router.get("/v1/admin/calidad", summary="Calidad de las asociaciones")
async def calidad(s: Svc, u: Admin):
    """
    Calidad de las asociaciones (RF21). Ordena de peor a mejor para que el equipo revise
    primero las que reciben más no me gusta o reportes.
    """
    r = await s.db.query(
        f"""SELECT aso.id, aso.nombre, aso.verificada, aso.activa,
                   {votos_asociacion('aso', 1)} AS "meGusta", {votos_asociacion('aso', -1)} AS "noMeGusta",
                   round({calidad_asociacion('aso')}::numeric, 3)::float8 AS calidad,
                   (SELECT count(*)::int FROM reportes_experiencia re
                    WHERE re.asociacion_id = aso.id OR re.actividad_id IN (SELECT x.id FROM actividades x WHERE x.asociacion_id = aso.id)) AS reportes
            FROM asociaciones aso
            ORDER BY calidad, reportes DESC, aso.nombre"""
    )
    return ok(r.rows)


# ---------------- Proyectos (RF-09) ----------------


async def _guardar_proyecto(s, u, d: Proyecto, proyecto_id: str | None):  # noqa: ANN001, ANN202
    if d.fechaFin and d.fechaFin < d.fechaInicio:
        raise error_validacion("fechaFin", "La fecha de fin no puede ser anterior al inicio")
    await exigir_archivo_de_administracion(s.db, d.fotoClave)
    if d.asociacionId:
        a = await s.db.query("SELECT 1 FROM asociaciones WHERE id = $1 AND ciudad_id = $2", [d.asociacionId, d.ciudadId])
        if not a.rows:
            raise HttpError(422, "asociacion_invalida", "La asociación no existe o es de otra ciudad")
    valores = [d.asociacionId, d.ciudadId, d.titulo, d.descripcion, d.fechaInicio, d.fechaFin, d.fotoClave]
    if not proyecto_id:
        r = await s.db.query(
            """INSERT INTO proyectos (asociacion_id, ciudad_id, titulo, descripcion, fecha_inicio, fecha_fin, foto_clave, creado_por)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id, estado""",
            [*valores, u.id],
        )
        return creado(r.rows[0])
    r = await s.db.query(
        """UPDATE proyectos SET asociacion_id=$1, ciudad_id=$2, titulo=$3, descripcion=$4, fecha_inicio=$5, fecha_fin=$6, foto_clave=$7
           WHERE id = $8 AND estado <> 'cancelado' RETURNING id, estado""",
        [*valores, proyecto_id],
    )
    if not r.rows:
        raise no_encontrado("Proyecto editable")
    return ok(r.rows[0])


@router.post("/v1/admin/proyectos", summary="Agregar un proyecto")
async def nuevo_proyecto(d: Proyecto, s: Svc, u: Admin):
    return await _guardar_proyecto(s, u, d, None)


@router.put("/v1/admin/proyectos/{proyectoId}", summary="Editar un proyecto")
async def editar_proyecto(proyectoId: IdRuta, d: Proyecto, s: Svc, u: Admin):
    return await _guardar_proyecto(s, u, d, proyectoId)


@router.post("/v1/admin/proyectos/{proyectoId}/estado", summary="Cambiar el estado de un proyecto")
async def estado_proyecto(proyectoId: IdRuta, d: EstadoProyecto, s: Svc, u: Admin):
    r = await s.db.query("UPDATE proyectos SET estado = $2 WHERE id = $1 RETURNING id, estado", [proyectoId, d.estado])
    if not r.rows:
        raise no_encontrado("Proyecto")
    return ok(r.rows[0])


# ---------------- Campañas y entregas ----------------


@router.post("/v1/admin/campanas", summary="Agregar una campaña de donación")
async def nueva_campana(d: Campana, s: Svc, u: Admin):
    await exigir_archivo_de_administracion(s.db, d.fotoClave)
    async with s.db.transaccion() as c:
        r = await c.query(
            """INSERT INTO campanas (asociacion_id, proyecto_id, ciudad_id, titulo, descripcion, inicio, fin, urgente, foto_clave, creado_por)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id""",
            [d.asociacionId, d.proyectoId, d.ciudadId, d.titulo, d.descripcion, d.inicio, d.fin, d.urgente, d.fotoClave, u.id],
        )
        cid = r.rows[0]["id"]
        for a in d.articulos:
            await c.query(
                "INSERT INTO campana_articulos (campana_id, nombre, descripcion, unidad, cantidad_meta, prioridad) VALUES ($1,$2,$3,$4,$5,$6)",
                [cid, a.nombre, a.descripcion, a.unidad, a.cantidadMeta, a.prioridad],
            )
        for p in d.puntosEntrega:
            await c.query(
                """INSERT INTO puntos_entrega (campana_id, ciudad_id, nombre, direccion, horarios, indicaciones, latitud, longitud)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                [cid, p.ciudadId, p.nombre, p.direccion, p.horarios, p.indicaciones, p.latitud, p.longitud],
            )
    return creado({"id": cid})


@router.post("/v1/admin/campanas/{campanaId}/estado", summary="Cambiar el estado de una campaña")
async def estado_campana(campanaId: IdRuta, d: EstadoCampana, s: Svc, u: Admin):
    r = await s.db.query("UPDATE campanas SET estado = $2 WHERE id = $1 RETURNING id, estado", [campanaId, d.estado])
    if not r.rows:
        raise no_encontrado("Campaña")
    return ok(r.rows[0])


@router.get("/v1/admin/entregas", summary="Entregas de donativos")
async def entregas(
    s: Svc,
    u: Admin,
    estado: Annotated[Literal["registrada", "recibida", "cancelada"] | None, Query()] = None,
    limite: LimiteAdmin = 50,
    desplazamiento: Desplazamiento = 0,
):
    r = await s.db.query(
        """SELECT e.id, e.cantidad::float8 AS cantidad, e.estado, e.comentario, e.creado_en AS "creadoEn",
                  ar.nombre AS articulo, ar.unidad, cp.titulo AS campana, pe.nombre AS "puntoEntrega", u.nombre AS donante
           FROM entregas_donacion e
           JOIN campana_articulos ar ON ar.id = e.articulo_id
           JOIN campanas cp ON cp.id = ar.campana_id
           JOIN puntos_entrega pe ON pe.id = e.punto_entrega_id
           JOIN usuarios u ON u.id = e.usuario_id
           WHERE ($1::text IS NULL OR e.estado = $1) ORDER BY e.creado_en DESC LIMIT $2 OFFSET $3""",
        [estado, limite, desplazamiento],
    )
    return ok(r.rows)


@router.put("/v1/admin/entregas/{entregaId}", summary="Confirmar o cancelar una entrega")
async def actualizar_entrega(entregaId: IdRuta, d: EstadoEntrega, s: Svc, u: Admin):
    recibida = d.estado == "recibida"
    r = await s.db.query(
        "UPDATE entregas_donacion SET estado = $2, recibida_por = $3, recibida_en = $4 WHERE id = $1 RETURNING id, estado",
        [entregaId, d.estado, u.id if recibida else None, datetime.now(timezone.utc) if recibida else None],
    )
    if not r.rows:
        raise no_encontrado("Entrega")
    return ok(r.rows[0])


# ---------------- Moderación ----------------

_TEXTOS_PROPUESTA = {
    "necesita_cambios": "necesita algunos cambios",
    "aprobada": "fue aprobada",
    "rechazada": "no fue aprobada",
    "completada": "se marcó como completada",
}


@router.get("/v1/admin/propuestas", summary="Propuestas de las familias")
async def propuestas(
    s: Svc,
    u: Admin,
    estado: Annotated[Literal["en_revision", "necesita_cambios", "aprobada", "rechazada", "completada"] | None, Query()] = None,
    limite: LimiteAdmin = 50,
    desplazamiento: Desplazamiento = 0,
):
    r = await s.db.query(
        """SELECT p.id, p.tipo, p.titulo, p.descripcion, p.ubicacion, p.estado, p.comentario_admin AS "comentarioAdmin",
                  p.contacto_nombre AS "contactoNombre", p.contacto_correo AS "contactoCorreo", p.contacto_telefono AS "contactoTelefono",
                  p.creado_en AS "creadoEn", u.nombre AS autor
           FROM propuestas p JOIN usuarios u ON u.id = p.usuario_id
           WHERE ($1::text IS NULL OR p.estado = $1) ORDER BY p.creado_en DESC LIMIT $2 OFFSET $3""",
        [estado, limite, desplazamiento],
    )
    return ok(r.rows)


@router.put("/v1/admin/propuestas/{propuestaId}/revision", summary="Revisar una propuesta")
async def revisar_propuesta(propuestaId: IdRuta, d: RevisionPropuesta, s: Svc, u: Admin):
    r = await s.db.query(
        """UPDATE propuestas SET estado = $2, comentario_admin = $3, revisado_por = $4, revisado_en = now()
           WHERE id = $1 RETURNING usuario_id, titulo""",
        [propuestaId, d.estado, d.comentario, u.id],
    )
    if not r.rows:
        raise no_encontrado("Propuesta")
    p = r.rows[0]
    await _notificar(
        s, p["usuario_id"], "propuesta", "Actualización de tu propuesta", f'"{p["titulo"]}" {_TEXTOS_PROPUESTA[d.estado]}.', propuestaId
    )
    return sin_contenido()


@router.get("/v1/admin/testimonios", summary="Testimonios por moderar")
async def testimonios(s: Svc, u: Admin, estado: Annotated[Literal["pendiente", "aprobado", "rechazado"] | None, Query()] = None):
    r = await s.db.query(
        """SELECT t.id, t.texto, t.foto_clave AS "fotoClave", t.estado, t.creado_en AS "creadoEn", a.titulo AS actividad, u.nombre AS autor
           FROM testimonios t JOIN inscripciones i ON i.id = t.inscripcion_id
           JOIN actividades a ON a.id = i.actividad_id JOIN usuarios u ON u.id = i.usuario_id
           WHERE ($1::text IS NULL OR t.estado = $1) ORDER BY t.creado_en DESC LIMIT 100""",
        [estado],
    )
    return ok(r.rows)


@router.put("/v1/admin/testimonios/{testimonioId}", summary="Aprobar o rechazar un testimonio")
async def moderar_testimonio(testimonioId: IdRuta, d: RevisionTestimonio, s: Svc, u: Admin):
    r = await s.db.query(
        "UPDATE testimonios SET estado = $2, comentario_admin = $3, revisado_por = $4, revisado_en = now() WHERE id = $1 RETURNING id",
        [testimonioId, d.estado, d.comentario, u.id],
    )
    if not r.rows:
        raise no_encontrado("Testimonio")
    return sin_contenido()


@router.get("/v1/admin/reportes", summary="Reportes de experiencia")
async def reportes(s: Svc, u: Admin, estado: Annotated[Literal["pendiente", "en_revision", "resuelto"] | None, Query()] = None):
    r = await s.db.query(
        """SELECT r.id, r.tipo, r.nivel_satisfaccion AS "nivelSatisfaccion", r.descripcion, r.foto_clave AS "fotoClave", r.estado,
                  r.actividad_id AS "actividadId", r.asociacion_id AS "asociacionId", r.campana_id AS "campanaId",
                  r.creado_en AS "creadoEn", u.nombre AS autor
           FROM reportes_experiencia r JOIN usuarios u ON u.id = r.usuario_id
           WHERE ($1::text IS NULL OR r.estado = $1) ORDER BY r.creado_en DESC LIMIT 100""",
        [estado],
    )
    return ok(r.rows)


@router.put("/v1/admin/reportes/{reporteId}", summary="Atender un reporte")
async def atender_reporte(reporteId: IdRuta, d: AtencionReporte, s: Svc, u: Admin):
    r = await s.db.query(
        "UPDATE reportes_experiencia SET estado = $2, respuesta_admin = $3, atendido_por = $4, atendido_en = now() WHERE id = $1 RETURNING id",
        [reporteId, d.estado, d.respuesta, u.id],
    )
    if not r.rows:
        raise no_encontrado("Reporte")
    return sin_contenido()


# ---------------- Usuarios y derechos ARCO ----------------


@router.put("/v1/admin/usuarios/{usuarioId}/estado", summary="Suspender o reactivar una cuenta")
async def estado_usuario(usuarioId: IdRuta, d: EstadoUsuario, s: Svc, u: Admin):
    if usuarioId == u.id:
        raise HttpError(422, "propio", "No puedes cambiar el estado de tu propia cuenta")
    async with s.db.transaccion() as c:
        r = await c.query(
            "UPDATE usuarios SET estado = $2 WHERE id = $1 AND estado IN ('activo','suspendido') RETURNING id", [usuarioId, d.estado]
        )
        if not r.rows:
            raise no_encontrado("Usuario")
        if d.estado == "suspendido":
            await revocar_todas(c, usuarioId)
    if d.estado == "suspendido":
        s.cupos.desconectar(usuarioId)
    return sin_contenido()


@router.get("/v1/admin/solicitudes-eliminacion", summary="Solicitudes de eliminación abiertas")
async def solicitudes_eliminacion(s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT s.id, s.estado, s.solicitada_en AS "solicitadaEn", u.id AS "usuarioId", u.nombre, u.correo
           FROM solicitudes_eliminacion s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.estado <> 'resuelta' ORDER BY s.solicitada_en"""
    )
    return ok(r.rows)


@router.post("/v1/admin/solicitudes-eliminacion/{solicitudId}/resolver", summary="Atender una solicitud de eliminación")
async def resolver_eliminacion(solicitudId: IdRuta, s: Svc, u: Admin):
    async with s.db.transaccion() as c:
        r = await c.query("SELECT archivo FROM anonimizar_usuario($1, $2)", [u.id, solicitudId])
        claves = [f["archivo"] for f in r.rows if f["archivo"] and re.fullmatch(r"[0-9a-f-]{36}", f["archivo"])]
        # También las imágenes que subió y no forman parte de contenido de la organización
        sueltas = await c.query(
            """DELETE FROM archivos ar
               WHERE (ar.usuario_id = (SELECT usuario_id FROM solicitudes_eliminacion WHERE id = $1) OR ar.id::text = ANY($2::text[]))
                 AND NOT EXISTS (SELECT 1 FROM asociaciones x WHERE x.foto_clave = ar.id::text)
                 AND NOT EXISTS (SELECT 1 FROM actividades x WHERE x.foto_clave = ar.id::text)
                 AND NOT EXISTS (SELECT 1 FROM campanas x WHERE x.foto_clave = ar.id::text)
                 AND NOT EXISTS (SELECT 1 FROM proyectos x WHERE x.foto_clave = ar.id::text)
                 AND NOT EXISTS (SELECT 1 FROM insignias x WHERE x.imagen_clave = ar.id::text)
               RETURNING ar.id""",
            [solicitudId, claves],
        )
        archivos = list(dict.fromkeys([*claves, *(f["id"] for f in sueltas.rows)]))
    for k in archivos:
        await s.almacen.borrar(k)
    return ok({"archivosEliminados": len(archivos)})
