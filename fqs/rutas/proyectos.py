"""
Proyectos (RF-09). Un proyecto agrupa varias campañas de donación con un mismo fin, por
ejemplo equipar un comedor. La familia ve el avance conjunto y entra a cada campaña para
registrar su donación.
"""

from ..errores import no_encontrado
from ..http.dependencias import Svc, Usuario
from ..validacion import Desplazamiento, Limite, UuidQuery
from .comun import IdRuta, nuevo_router, ok
from .consultas import (
    CAMPANA_VERIFICADA,
    COLUMNAS_CAMPANA,
    COLUMNAS_PROYECTO,
    FROM_CAMPANA,
    FROM_PROYECTO,
    PROYECTO_VERIFICADO,
    ciudad_del_usuario,
    ciudad_visible,
)

router = nuevo_router("proyectos")


@router.get("/v1/proyectos", summary="Proyectos vigentes de mi ciudad")
async def listar(s: Svc, u: Usuario, ciudadId: UuidQuery = None, limite: Limite = 20, desplazamiento: Desplazamiento = 0):
    r = await s.db.query(
        f"""SELECT {COLUMNAS_PROYECTO} {FROM_PROYECTO}
            WHERE pr.estado = 'publicado' AND (pr.fecha_fin IS NULL OR pr.fecha_fin >= current_date)
              AND ($4 OR {PROYECTO_VERIFICADO})
              AND ($1::uuid IS NULL OR pr.ciudad_id = $1)
            ORDER BY pr.fecha_inicio DESC, pr.titulo
            LIMIT $2 OFFSET $3""",
        [await ciudad_visible(s.db, u, ciudadId), limite, desplazamiento, u.rol == "admin"],
    )
    return ok(r.rows)


@router.get("/v1/proyectos/{proyectoId}", summary="Detalle de un proyecto con sus campañas")
async def detalle(proyectoId: IdRuta, s: Svc, u: Usuario):
    es_admin = u.rol == "admin"
    r = await s.db.query(
        f"""SELECT {COLUMNAS_PROYECTO} {FROM_PROYECTO}
            WHERE pr.id = $1 AND ($2 OR (pr.estado IN ('publicado','finalizado')
                                         AND {PROYECTO_VERIFICADO} AND pr.ciudad_id = {ciudad_del_usuario(3)}))""",
        [proyectoId, es_admin, u.id],
    )
    if not r.rows:
        raise no_encontrado("Proyecto")
    campanas = await s.db.query(
        f"""SELECT {COLUMNAS_CAMPANA} {FROM_CAMPANA}
            WHERE cp.proyecto_id = $1 AND ($2 OR (cp.estado IN ('publicada','finalizada') AND {CAMPANA_VERIFICADA}))
            ORDER BY (cp.estado = 'publicada' AND cp.fin > now()) DESC, cp.urgente DESC, cp.fin""",
        [proyectoId, es_admin],
    )
    return ok({**r.rows[0], "campanas": campanas.rows})
