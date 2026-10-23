"""Datos públicos que la app necesita antes de iniciar sesión (registro)."""

import asyncio

from .comun import ok, nuevo_router
from ..http.dependencias import Svc

router = nuevo_router("catálogo")


@router.get("/v1/salud", summary="Estado del servicio")
async def salud(s: Svc):
    await s.db.query("SELECT 1")
    return ok({"ok": True})


@router.get("/v1/catalogos", summary="Ciudades, categorías y aviso de privacidad vigente")
async def catalogos(s: Svc):
    ciudades, categorias, aviso = await asyncio.gather(
        s.db.query('SELECT id, nombre, estado, zona_horaria AS "zonaHoraria" FROM ciudades ORDER BY nombre'),
        s.db.query("SELECT id, clave, nombre, descripcion FROM categorias WHERE activa ORDER BY nombre"),
        s.db.query('SELECT id, version, contenido, publicado_en AS "publicadoEn" FROM aviso_privacidad_vigente'),
    )
    return ok({"ciudades": ciudades.rows, "categorias": categorias.rows, "avisoPrivacidad": aviso.rows[0] if aviso.rows else None})
