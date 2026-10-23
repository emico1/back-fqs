"""Mi Comunidad. Todas las consultas filtran por el usuario de la sesión (sin IDOR)."""

from ..errores import HttpError, no_encontrado
from ..http.dependencias import Svc, Usuario
from ..validacion import Correo, Fecha, Modelo, Telefono, Texto, edad_en_anios
from .comun import IdRuta, creado, nuevo_router, ok

router = nuevo_router("comunidad")

COLUMNAS = 'id, nombre, relacion, fecha_nacimiento::text AS "fechaNacimiento", correo, telefono'
MAX_MIEMBROS = 30


class Miembro(Modelo):
    nombre: Texto(2, 120)
    relacion: Texto(2, 40)
    fechaNacimiento: Fecha
    correo: Correo | None = None
    telefono: Telefono | None = None


@router.get("/v1/yo/comunidad", summary="Miembros de mi comunidad")
async def listar(s: Svc, u: Usuario):
    r = await s.db.query(f"SELECT {COLUMNAS} FROM miembros_comunidad WHERE usuario_id = $1 AND activo ORDER BY creado_en", [u.id])
    return ok(r.rows)


@router.post("/v1/yo/comunidad", summary="Agregar un miembro")
async def agregar(d: Miembro, s: Svc, u: Usuario):
    if edad_en_anios(d.fechaNacimiento) > 120:
        raise HttpError(422, "edad", "Fecha de nacimiento inválida")
    total = await s.db.query("SELECT count(*)::int AS n FROM miembros_comunidad WHERE usuario_id = $1 AND activo", [u.id])
    if (total.rows[0]["n"] if total.rows else 0) >= MAX_MIEMBROS:
        raise HttpError(422, "limite", f"Puedes registrar hasta {MAX_MIEMBROS} miembros")
    r = await s.db.query(
        f"""INSERT INTO miembros_comunidad (usuario_id, nombre, relacion, fecha_nacimiento, correo, telefono)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING {COLUMNAS}""",
        [u.id, d.nombre, d.relacion, d.fechaNacimiento, d.correo, d.telefono],
    )
    return creado(r.rows[0])


@router.put("/v1/yo/comunidad/{miembroId}", summary="Editar un miembro")
async def editar(miembroId: IdRuta, d: Miembro, s: Svc, u: Usuario):
    r = await s.db.query(
        f"""UPDATE miembros_comunidad SET nombre = $3, relacion = $4, fecha_nacimiento = $5, correo = $6, telefono = $7
            WHERE id = $1 AND usuario_id = $2 AND activo RETURNING {COLUMNAS}""",
        [miembroId, u.id, d.nombre, d.relacion, d.fechaNacimiento, d.correo, d.telefono],
    )
    if not r.rows:
        raise no_encontrado("Miembro")
    return ok(r.rows[0])


@router.delete("/v1/yo/comunidad/{miembroId}", summary="Eliminar un miembro")
async def eliminar(miembroId: IdRuta, s: Svc, u: Usuario):
    # La función decide si se borra o solo se desactiva cuando ya tiene historial
    r = await s.db.query("SELECT eliminar_miembro($1, $2) AS resultado", [u.id, miembroId])
    return ok({"resultado": r.rows[0]["resultado"] if r.rows else None})
