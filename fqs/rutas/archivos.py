"""
Subida y descarga de imágenes. La app envía la imagen como cuerpo binario con Content-Type
image/jpeg o image/png (sin multipart). Lo que se guarda es la versión sin metadatos, y un
archivo solo lo puede ver su dueño, un admin, o cualquiera con sesión si ya forma parte de
contenido público.
"""

import hashlib
import uuid

from fastapi import Request
from fastapi.responses import Response

from ..errores import HttpError, no_encontrado
from ..http.dependencias import Svc, Usuario
from ..limites import SUBIDAS, cuenta_de, limiter
from ..seguridad.imagenes import validar_y_limpiar
from .comun import IdRuta, creado, nuevo_router

router = nuevo_router("archivos")

LIMITE = 5 * 1024 * 1024


@router.post("/v1/archivos", summary="Subir una imagen JPEG o PNG (cuerpo binario, máximo 5 MB)", status_code=201)
@limiter.limit(SUBIDAS, key_func=cuenta_de)
async def subir(request: Request, s: Svc, u: Usuario):
    declarado = request.headers.get("content-type", "").split(";")[0].strip().lower()
    crudo = await request.body()
    if len(crudo) > LIMITE:
        raise HttpError(413, "demasiado_grande", "El contenido excede el tamaño permitido")
    tipo, datos = validar_y_limpiar(crudo, declarado or None)
    ident = str(uuid.uuid4())
    await s.almacen.guardar(ident, datos)
    try:
        await s.db.query(
            "INSERT INTO archivos (id, usuario_id, tipo_mime, tamano, sha256) VALUES ($1, $2, $3, $4, $5)",
            [ident, u.id, tipo, len(datos), hashlib.sha256(datos).hexdigest()],
        )
    except Exception:
        await s.almacen.borrar(ident)
        raise
    return creado({"clave": ident, "tipo": tipo, "tamano": len(datos)})


@router.get("/v1/archivos/{archivoId}", summary="Descargar una imagen")
async def descargar(archivoId: IdRuta, s: Svc, u: Usuario):
    r = await s.db.query(
        """SELECT ar.tipo_mime FROM archivos ar
           WHERE ar.id = $1 AND (
             ar.usuario_id = $2 OR $3
             OR EXISTS (SELECT 1 FROM asociaciones x WHERE x.foto_clave = $4 AND x.activa)
             OR EXISTS (SELECT 1 FROM actividades x WHERE x.foto_clave = $4 AND x.estado IN ('publicada','finalizada'))
             OR EXISTS (SELECT 1 FROM campanas x WHERE x.foto_clave = $4 AND x.estado IN ('publicada','finalizada'))
             OR EXISTS (SELECT 1 FROM proyectos x WHERE x.foto_clave = $4 AND x.estado IN ('publicado','finalizado'))
             OR EXISTS (SELECT 1 FROM insignias x WHERE x.imagen_clave = $4)
             OR EXISTS (SELECT 1 FROM testimonios x WHERE x.foto_clave = $4 AND x.estado = 'aprobado'))""",
        [archivoId, u.id, u.rol == "admin", archivoId],
    )
    # 404 tanto si no existe como si no hay permiso, para no confirmar su existencia
    if not r.rows:
        raise no_encontrado("Archivo")
    try:
        datos = await s.almacen.leer(archivoId)
    except Exception:  # noqa: BLE001
        raise no_encontrado("Archivo") from None
    return Response(
        content=datos,
        media_type=r.rows[0]["tipo_mime"],
        headers={"Cache-Control": "private, max-age=86400", "Content-Disposition": "inline"},
    )
