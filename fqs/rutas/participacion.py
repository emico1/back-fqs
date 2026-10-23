"""
Asociaciones, actividades, inscripciones, favoritos, campañas y entregas de donativos.

Las familias solo ven asociaciones verificadas y de su ciudad (RF-01, RF-02). La persona
administradora ve todas para poder revisarlas.
"""

import asyncio
from typing import Annotated, Literal

from fastapi import Query, Request
from pydantic import Field

from ..avisos_acompanantes import avisar_inscripcion
from ..errores import HttpError, no_encontrado
from ..http.dependencias import Svc, Usuario
from ..limites import ESCRITURA, cuenta_de, limiter
from ..tareas import en_segundo_plano
from ..validacion import Booleano, Desplazamiento, Limite, Modelo, Numero, TextoOpcional, Uuid, UuidQuery
from .comun import IdRuta, creado, nuevo_router, ok, sin_contenido
from .consultas import (
    CAMPANA_VERIFICADA,
    COLUMNAS_ACTIVIDAD,
    COLUMNAS_ASOCIACION,
    COLUMNAS_CAMPANA,
    FROM_ACTIVIDAD,
    FROM_CAMPANA,
    calidad_asociacion,
    ciudad_del_usuario,
    ciudad_visible,
)

router = nuevo_router("participación")

Categoria = Annotated[str | None, Query(pattern=r"^[A-Z][A-Z_]{1,40}$")]
Busqueda = Annotated[str | None, Query(max_length=80)]


def _busqueda(q: str | None) -> str | None:
    q = (q or "").strip()
    return q or None


class Inscripcion(Modelo):
    titularAsiste: Booleano
    miembros: Annotated[list[Uuid], Field(max_length=20)] = []


class Favorito(Modelo):
    notificacionesActivas: Booleano = False


class Entrega(Modelo):
    articuloId: Uuid
    puntoEntregaId: Uuid
    cantidad: Annotated[Numero, Field(gt=0, le=1_000_000)]
    comentario: TextoOpcional(500)


# ---------------- Asociaciones ----------------


@router.get("/v1/asociaciones", summary="Asociaciones de mi ciudad, ordenadas por calidad")
async def asociaciones(
    s: Svc,
    u: Usuario,
    ciudadId: UuidQuery = None,
    categoria: Categoria = None,
    q: Busqueda = None,
    limite: Limite = 20,
    desplazamiento: Desplazamiento = 0,
):
    # position() en lugar de LIKE para que % y _ del usuario no actúen como comodines
    r = await s.db.query(
        f"""SELECT {COLUMNAS_ASOCIACION}
            FROM asociaciones aso
            JOIN categorias ca ON ca.id = aso.categoria_id
            JOIN ciudades ci ON ci.id = aso.ciudad_id
            WHERE aso.activa
              AND ($6 OR aso.verificada)
              AND ($1::uuid IS NULL OR aso.ciudad_id = $1)
              AND ($2::text IS NULL OR ca.clave = $2)
              AND ($3::text IS NULL OR position(lower($3::text) IN lower(aso.nombre || ' ' || aso.descripcion)) > 0)
            ORDER BY aso.verificada DESC, {calidad_asociacion('aso')} DESC, aso.nombre
            LIMIT $4 OFFSET $5""",
        [await ciudad_visible(s.db, u, ciudadId), categoria, _busqueda(q), limite, desplazamiento, u.rol == "admin"],
    )
    return ok(r.rows)


@router.get("/v1/asociaciones/{asociacionId}", summary="Detalle de una asociación con sus próximas actividades")
async def asociacion(asociacionId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(
        f"""SELECT {COLUMNAS_ASOCIACION},
                   (f.usuario_id IS NOT NULL) AS "esFavorita",
                   COALESCE(f.notificaciones_activas, false) AS "notificacionesActivas"
            FROM asociaciones aso
            JOIN categorias ca ON ca.id = aso.categoria_id
            JOIN ciudades ci ON ci.id = aso.ciudad_id
            LEFT JOIN favoritos_asociaciones f ON f.asociacion_id = aso.id AND f.usuario_id = $2
            WHERE aso.id = $1 AND aso.activa
              AND ($3 OR (aso.verificada AND aso.ciudad_id = {ciudad_del_usuario(2)}))""",
        [asociacionId, u.id, u.rol == "admin"],
    )
    if not r.rows:
        raise no_encontrado("Asociación")
    actividades = await s.db.query(
        f"""SELECT {COLUMNAS_ACTIVIDAD} {FROM_ACTIVIDAD}
            WHERE a.asociacion_id = $1 AND a.estado = 'publicada' AND a.fin > now()
            ORDER BY a.inicio LIMIT 10""",
        [asociacionId],
    )
    return ok({**r.rows[0], "proximasActividades": actividades.rows})


@router.put("/v1/asociaciones/{asociacionId}/favorito", summary="Marcar una asociación como favorita")
async def favorito_asociacion(asociacionId: IdRuta, d: Favorito, s: Svc, u: Usuario):
    existe = await s.db.query("SELECT 1 FROM asociaciones WHERE id = $1 AND activa AND verificada", [asociacionId])
    if existe.rowcount == 0:
        raise no_encontrado("Asociación")
    await s.db.query(
        """INSERT INTO favoritos_asociaciones (usuario_id, asociacion_id, notificaciones_activas) VALUES ($1, $2, $3)
           ON CONFLICT (usuario_id, asociacion_id) DO UPDATE SET notificaciones_activas = EXCLUDED.notificaciones_activas""",
        [u.id, asociacionId, d.notificacionesActivas],
    )
    return ok({"esFavorita": True, "notificacionesActivas": d.notificacionesActivas})


@router.delete("/v1/asociaciones/{asociacionId}/favorito", summary="Quitar una asociación de favoritos")
async def quitar_favorito_asociacion(asociacionId: IdRuta, s: Svc, u: Usuario):
    await s.db.query("DELETE FROM favoritos_asociaciones WHERE usuario_id = $1 AND asociacion_id = $2", [u.id, asociacionId])
    return sin_contenido()


# ---------------- Actividades e inscripciones ----------------


@router.get("/v1/actividades", summary="Actividades publicadas de mi ciudad")
async def actividades(
    s: Svc,
    u: Usuario,
    ciudadId: UuidQuery = None,
    categoria: Categoria = None,
    asociacionId: UuidQuery = None,
    q: Busqueda = None,
    tipo: Literal["voluntariado", "visita"] | None = None,
    orden: Literal["fecha", "calidad"] = "fecha",
    limite: Limite = 20,
    desplazamiento: Desplazamiento = 0,
):
    # voluntariado es Participar y visita es Visiteo en el filtro inicial de la app
    orden_sql = f"{calidad_asociacion('aso')} DESC, a.inicio" if orden == "calidad" else "a.inicio"
    r = await s.db.query(
        f"""SELECT {COLUMNAS_ACTIVIDAD} {FROM_ACTIVIDAD}
            WHERE a.estado = 'publicada' AND a.fin > now() AND aso.activa
              AND ($7 OR aso.verificada)
              AND ($1::uuid IS NULL OR a.ciudad_id = $1)
              AND ($2::text IS NULL OR ca.clave = $2)
              AND ($3::uuid IS NULL OR a.asociacion_id = $3)
              AND ($4::text IS NULL OR position(lower($4::text) IN lower(a.titulo || ' ' || a.descripcion_corta)) > 0)
              AND ($8::text IS NULL OR a.tipo = $8)
            ORDER BY {orden_sql}
            LIMIT $5 OFFSET $6""",
        [await ciudad_visible(s.db, u, ciudadId), categoria, asociacionId, _busqueda(q), limite, desplazamiento, u.rol == "admin", tipo],
    )
    return ok(r.rows)


@router.get("/v1/actividades/{actividadId}", summary="Detalle de una actividad con mi inscripción")
async def actividad(actividadId: IdRuta, s: Svc, u: Usuario):
    # Visible si está publicada en la ciudad de la familia y es de una asociación verificada,
    # o si la familia tiene inscripción (su historial), o si es admin
    r = await s.db.query(
        f"""SELECT {COLUMNAS_ACTIVIDAD} {FROM_ACTIVIDAD}
            WHERE a.id = $1 AND (
              $3
              OR EXISTS (SELECT 1 FROM inscripciones i WHERE i.actividad_id = a.id AND i.usuario_id = $2)
              OR (a.estado IN ('publicada','finalizada') AND aso.verificada AND a.ciudad_id = {ciudad_del_usuario(2)}))""",
        [actividadId, u.id, u.rol == "admin"],
    )
    if not r.rows:
        raise no_encontrado("Actividad")
    fav = await s.db.query("SELECT 1 FROM favoritos_actividades WHERE usuario_id = $1 AND actividad_id = $2", [u.id, actividadId])
    ins = await s.db.query(
        """SELECT i.id, i.estado, i.cantidad_personas AS "cantidadPersonas",
                  EXISTS (SELECT 1 FROM inscripcion_participantes p WHERE p.inscripcion_id = i.id AND p.es_titular) AS "titularAsiste",
                  COALESCE((SELECT json_agg(p.miembro_comunidad_id) FROM inscripcion_participantes p
                            WHERE p.inscripcion_id = i.id AND NOT p.es_titular), '[]') AS miembros
           FROM inscripciones i WHERE i.actividad_id = $1 AND i.usuario_id = $2""",
        [actividadId, u.id],
    )
    return ok({**r.rows[0], "esFavorita": fav.rowcount > 0, "miInscripcion": ins.rows[0] if ins.rows else None})


# ---------------- Favoritos (RF20) ----------------


@router.put("/v1/actividades/{actividadId}/favorito", summary="Marcar una actividad como favorita")
async def favorito_actividad(actividadId: IdRuta, s: Svc, u: Usuario):
    visible = await s.db.query(
        f"""SELECT 1 FROM actividades a JOIN asociaciones aso ON aso.id = a.asociacion_id
            WHERE a.id = $1 AND a.estado IN ('publicada','finalizada') AND aso.verificada AND a.ciudad_id = {ciudad_del_usuario(2)}""",
        [actividadId, u.id],
    )
    if visible.rowcount == 0:
        raise no_encontrado("Actividad")
    await s.db.query(
        "INSERT INTO favoritos_actividades (usuario_id, actividad_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", [u.id, actividadId]
    )
    return ok({"esFavorita": True})


@router.delete("/v1/actividades/{actividadId}/favorito", summary="Quitar una actividad de favoritos")
async def quitar_favorito_actividad(actividadId: IdRuta, s: Svc, u: Usuario):
    await s.db.query("DELETE FROM favoritos_actividades WHERE usuario_id = $1 AND actividad_id = $2", [u.id, actividadId])
    return sin_contenido()


@router.get("/v1/yo/favoritos", summary="Mis asociaciones y actividades favoritas")
async def favoritos(s: Svc, u: Usuario):
    """Solo las que la familia todavía puede ver."""
    asoc, acts = await asyncio.gather(
        s.db.query(
            f"""SELECT {COLUMNAS_ASOCIACION}, f.notificaciones_activas AS "notificacionesActivas", true AS "esFavorita"
                FROM favoritos_asociaciones f
                JOIN asociaciones aso ON aso.id = f.asociacion_id
                JOIN categorias ca ON ca.id = aso.categoria_id
                JOIN ciudades ci ON ci.id = aso.ciudad_id
                WHERE f.usuario_id = $1 AND aso.activa AND aso.verificada AND aso.ciudad_id = {ciudad_del_usuario(1)}
                ORDER BY aso.nombre""",
            [u.id],
        ),
        s.db.query(
            f"""SELECT {COLUMNAS_ACTIVIDAD} {FROM_ACTIVIDAD}
                JOIN favoritos_actividades f ON f.actividad_id = a.id AND f.usuario_id = $1
                WHERE a.estado = 'publicada' AND a.fin > now() AND aso.verificada AND a.ciudad_id = {ciudad_del_usuario(1)}
                ORDER BY a.inicio""",
            [u.id],
        ),
    )
    return ok({"asociaciones": asoc.rows, "actividades": acts.rows})


@router.post("/v1/actividades/{actividadId}/inscripcion", summary="Inscribirme con mis acompañantes")
async def inscribir(actividadId: IdRuta, d: Inscripcion, s: Svc, u: Usuario):
    # La cuenta de administración sirve para gestionar, no para participar
    if u.rol != "familia":
        raise HttpError(
            403,
            "solo_familias",
            "Las cuentas de administración no se pueden inscribir a actividades. Inicia sesión con una cuenta de familia.",
        )
    # Solo se inscribe a actividades que la familia puede ver
    visible = await s.db.query(
        f"""SELECT 1 FROM actividades a JOIN asociaciones aso ON aso.id = a.asociacion_id
            WHERE a.id = $1 AND aso.verificada AND aso.activa AND a.ciudad_id = {ciudad_del_usuario(2)}""",
        [actividadId, u.id],
    )
    if visible.rowcount == 0:
        raise no_encontrado("Actividad")
    # inscribir_familia valida cupo, edad mínima, dueño de cada acompañante y estado de la
    # actividad, todo dentro de la misma transacción con bloqueo de fila. Si dos familias piden
    # el último lugar al mismo tiempo, una lo obtiene y la otra recibe un 409 con el mensaje
    # claro de que ya no hay lugares (RF-05).
    r = await s.db.query("SELECT inscribir_familia($1, $2, $3, $4::uuid[]) AS id", [u.id, actividadId, d.titularAsiste, d.miembros])
    cupos = await s.db.query(
        """SELECT cupo_total AS "cupoTotal", cupos_ocupados AS "cuposOcupados", cupo_total - cupos_ocupados AS "cuposDisponibles"
           FROM actividades WHERE id = $1""",
        [actividadId],
    )
    inscripcion_id = r.rows[0]["id"] if r.rows else None
    # Confirmación por correo a los acompañantes adultos que tienen correo
    if inscripcion_id:
        en_segundo_plano(avisar_inscripcion(s, actividadId, inscripcion_id), "el aviso a acompañantes")
    return creado({"inscripcionId": inscripcion_id, **(cupos.rows[0] if cupos.rows else {})})


@router.delete("/v1/actividades/{actividadId}/inscripcion", summary="Cancelar mi inscripción")
async def cancelar_inscripcion(actividadId: IdRuta, s: Svc, u: Usuario):
    await s.db.query("SELECT cancelar_inscripcion($1, $2)", [u.id, actividadId])
    return sin_contenido()


# ---------------- Campañas y entregas ----------------


@router.get("/v1/campanas", summary="Campañas de donación abiertas en mi ciudad")
async def campanas(
    s: Svc,
    u: Usuario,
    ciudadId: UuidQuery = None,
    proyectoId: UuidQuery = None,
    limite: Limite = 20,
    desplazamiento: Desplazamiento = 0,
):
    r = await s.db.query(
        f"""SELECT {COLUMNAS_CAMPANA} {FROM_CAMPANA}
            WHERE cp.estado = 'publicada' AND cp.fin > now()
              AND ($4 OR ({CAMPANA_VERIFICADA}))
              AND ($1::uuid IS NULL OR cp.ciudad_id = $1)
              AND ($5::uuid IS NULL OR cp.proyecto_id = $5)
            ORDER BY cp.urgente DESC, cp.fin
            LIMIT $2 OFFSET $3""",
        [await ciudad_visible(s.db, u, ciudadId), limite, desplazamiento, u.rol == "admin", proyectoId],
    )
    return ok(r.rows)


@router.get("/v1/campanas/{campanaId}", summary="Detalle de una campaña con artículos y puntos de entrega")
async def campana(campanaId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(
        f"""SELECT {COLUMNAS_CAMPANA} {FROM_CAMPANA}
            WHERE cp.id = $1 AND (
              $2
              OR EXISTS (SELECT 1 FROM entregas_donacion e JOIN campana_articulos ar ON ar.id = e.articulo_id
                         WHERE ar.campana_id = cp.id AND e.usuario_id = $3)
              OR (cp.estado IN ('publicada','finalizada') AND cp.ciudad_id = {ciudad_del_usuario(3)} AND {CAMPANA_VERIFICADA}))""",
        [campanaId, u.rol == "admin", u.id],
    )
    if not r.rows:
        raise no_encontrado("Campaña")
    articulos, puntos = await asyncio.gather(
        s.db.query(
            """SELECT id, nombre, descripcion, unidad, prioridad,
                      cantidad_meta::float8 AS "cantidadMeta", cantidad_recibida::float8 AS "cantidadRecibida",
                      LEAST(round(cantidad_recibida / cantidad_meta, 4), 1)::float8 AS progreso
               FROM campana_articulos WHERE campana_id = $1
               ORDER BY CASE prioridad WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, nombre""",
            [campanaId],
        ),
        s.db.query(
            """SELECT id, nombre, direccion, horarios, indicaciones, latitud::float8 AS latitud, longitud::float8 AS longitud
               FROM puntos_entrega WHERE campana_id = $1 ORDER BY nombre""",
            [campanaId],
        ),
    )
    return ok({**r.rows[0], "articulos": articulos.rows, "puntosEntrega": puntos.rows})


@router.post("/v1/campanas/{campanaId}/entregas", summary="Registrar una entrega de donativo")
@limiter.shared_limit(ESCRITURA, scope="escritura", key_func=cuenta_de)
async def registrar_entrega(request: Request, campanaId: IdRuta, d: Entrega, s: Svc, u: Usuario):
    # El artículo y el punto de entrega deben ser de esta campaña, y la campaña debe seguir
    # abierta y ser visible para la familia
    valida = await s.db.query(
        f"""SELECT 1
            FROM campanas cp
            LEFT JOIN asociaciones aso ON aso.id = cp.asociacion_id
            LEFT JOIN proyectos pr ON pr.id = cp.proyecto_id
            WHERE cp.id = $1 AND cp.estado = 'publicada' AND cp.fin > now()
              AND cp.ciudad_id = {ciudad_del_usuario(4)} AND {CAMPANA_VERIFICADA}
              AND EXISTS (SELECT 1 FROM campana_articulos ar WHERE ar.id = $2 AND ar.campana_id = cp.id)
              AND EXISTS (SELECT 1 FROM puntos_entrega pe WHERE pe.id = $3 AND pe.campana_id = cp.id)""",
        [campanaId, d.articuloId, d.puntoEntregaId, u.id],
    )
    if valida.rowcount == 0:
        raise HttpError(422, "entrega_invalida", "El artículo o el punto de entrega no corresponden a una campaña abierta")
    r = await s.db.query(
        """INSERT INTO entregas_donacion (usuario_id, articulo_id, punto_entrega_id, cantidad, comentario)
           VALUES ($1, $2, $3, $4, $5) RETURNING id, estado, cantidad::float8 AS cantidad, creado_en AS "creadoEn\"""",
        [u.id, d.articuloId, d.puntoEntregaId, d.cantidad, d.comentario],
    )
    return creado(r.rows[0])


@router.delete("/v1/yo/entregas/{entregaId}", summary="Cancelar una entrega que todavía no se recibe")
async def cancelar_entrega(entregaId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(
        "UPDATE entregas_donacion SET estado = 'cancelada' WHERE id = $1 AND usuario_id = $2 AND estado = 'registrada'",
        [entregaId, u.id],
    )
    if r.rowcount == 0:
        raise no_encontrado("Entrega pendiente")
    return sin_contenido()
