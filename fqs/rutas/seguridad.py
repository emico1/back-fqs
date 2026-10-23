"""
Rutas de seguridad de la cuenta de administración.

Las que empiezan con /v1/admin/2fa son las únicas de administración que se pueden usar con una
sesión sin segundo factor, porque son las que sirven para activarlo.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Query, Request

from ..errores import HttpError
from ..http.dependencias import Admin, Svc
from ..jsonfmt import iso
from ..seguridad.bitacora import registrar_evento
from ..seguridad.contrasenas import verificar_contrasena
from ..seguridad.qr import svg_qr
from ..seguridad.sesiones import revocar_todas
from ..validacion import Contrasena, Modelo, Texto, UuidQuery, error_validacion
from .comun import ip, nuevo_router, ok, rid, solo_parametros

router = nuevo_router("seguridad")


class Iniciar2fa(Modelo):
    password: Contrasena


class Codigo2fa(Modelo):
    codigo: Texto(6, 12)


@router.get("/v1/admin/2fa", summary="Estado de mi segundo factor")
async def estado(s: Svc, u: Admin):
    return ok({**(await s.segundo_factor.estado(u.id)), "obligatorio": s.config.ADMIN_2FA == "obligatorio"})


@router.post("/v1/admin/2fa/iniciar", summary="Iniciar la activación del segundo factor")
async def iniciar(request: Request, d: Iniciar2fa, s: Svc, u: Admin):
    """
    Paso 1. Pide otra vez la contraseña, así una sesión robada no basta para amarrar la cuenta
    a la app de autenticación de otra persona.
    """
    clave = f"2fa-iniciar {u.id}"
    s.limites.login_cuenta.consumir(clave)
    r = await s.db.query("SELECT password_hash, correo, username FROM usuarios WHERE id = $1", [u.id])
    fila = r.rows[0]
    if not await verificar_contrasena(d.password, fila["password_hash"]):
        raise HttpError(400, "contrasena_incorrecta", "La contraseña no es correcta")
    s.limites.login_cuenta.reiniciar(clave)
    datos = await s.segundo_factor.iniciar(u.id, fila["correo"] or fila["username"])
    await registrar_evento(s.db, "2fa_iniciado", actor_id=u.id, actor_rol="admin", ip=ip(request), request_id=rid(request))
    return ok(
        {
            **datos,
            # El QR se dibuja aquí mismo, la clave nunca sale a un servicio externo de QR
            "qrSvg": svg_qr(datos["uri"]),
            "instrucciones": "Escanea el código QR (o escribe la clave) en tu app de autenticación y después confirma con el código de 6 dígitos que muestra.",
        }
    )


@router.post("/v1/admin/2fa/confirmar", summary="Confirmar el segundo factor con el primer código")
async def confirmar(request: Request, d: Codigo2fa, s: Svc, u: Admin):
    """
    Paso 2. El primer código correcto activa el segundo factor. La sesión actual queda
    verificada y las demás sesiones de la cuenta se cierran.
    """
    clave = f"2fa-confirmar {u.id}"
    s.limites.login_cuenta.consumir(clave)
    codigos = await s.segundo_factor.confirmar(u.id, d.codigo)
    s.limites.login_cuenta.reiniciar(clave)
    await s.db.query("UPDATE sesiones SET segundo_factor = true WHERE familia_id = $1", [u.familia_id])
    await revocar_todas(s.db, u.id, u.familia_id)
    await registrar_evento(s.db, "2fa_activado", actor_id=u.id, actor_rol="admin", ip=ip(request), request_id=rid(request))
    return ok(
        {
            "codigosRespaldo": codigos,
            "aviso": "Guarda estos códigos en un lugar seguro. Cada uno sirve una sola vez si pierdes el teléfono y no se volverán a mostrar.",
        }
    )


@router.post("/v1/admin/2fa/codigos-respaldo", summary="Generar códigos de respaldo nuevos")
async def codigos_respaldo(request: Request, d: Codigo2fa, s: Svc, u: Admin):
    if not u.segundo_factor:
        raise HttpError(403, "requiere_2fa", "Inicia sesión con tu código para hacer esto")
    clave = f"2fa-codigos {u.id}"
    s.limites.login_cuenta.consumir(clave)
    codigos = await s.segundo_factor.regenerar_codigos(u.id, d.codigo)
    s.limites.login_cuenta.reiniciar(clave)
    await registrar_evento(s.db, "2fa_codigos_regenerados", actor_id=u.id, actor_rol="admin", ip=ip(request), request_id=rid(request))
    return ok({"codigosRespaldo": codigos})


@router.get("/v1/admin/bitacora", summary="Consultar la bitácora de seguridad", dependencies=[solo_parametros("accion", "actorId", "antesDe", "limite")])
async def bitacora(
    s: Svc,
    u: Admin,
    accion: Annotated[str | None, Query(pattern=r"^[a-z0-9_]{3,40}$")] = None,
    actorId: UuidQuery = None,
    antesDe: Annotated[int | None, Query(gt=0)] = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """De la más reciente a la más vieja, paginada por id."""
    r = await s.db.query(
        """SELECT b.id::text AS id, b.creado_en AS "creadoEn", b.accion, b.ruta, b.actor_id AS "actorId",
                  b.actor_rol AS "actorRol", u.username AS "actorUsername", b.entidad_id AS "entidadId",
                  b.detalles, b.ip, b.request_id AS "requestId", b.hash
           FROM bitacora_seguridad b LEFT JOIN usuarios u ON u.id = b.actor_id
           WHERE ($1::text IS NULL OR b.accion = $1)
             AND ($2::uuid IS NULL OR b.actor_id = $2)
             AND ($3::bigint IS NULL OR b.id < $3)
           ORDER BY b.id DESC LIMIT $4""",
        [accion, actorId.lower() if actorId else None, antesDe, limite],
    )
    return ok({"eventos": r.rows, "siguiente": r.rows[-1]["id"] if r.rows and len(r.rows) == limite else None})


@router.get("/v1/admin/bitacora/verificar", summary="Verificar la cadena de la bitácora", dependencies=[solo_parametros("hastaId", "hash")])
async def verificar(
    s: Svc,
    u: Admin,
    hastaId: Annotated[int | None, Query(gt=0)] = None,
    hash: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
):
    """
    Recalcula toda la cadena de hashes. Si alguien editó o borró una fila aparece aquí. Con
    hastaId y hash (los del correo del ancla) además confirma que esa fila sigue igual.
    """
    if (hastaId is None) != (hash is None):
        raise error_validacion("", "Indica hastaId y hash juntos")
    r = await s.db.query("SELECT * FROM verificar_bitacora()")
    f = r.rows[0]
    coincide_ancla = None
    if hastaId is not None and hash is not None:
        c = await s.db.query("SELECT coincide_ancla($1, $2) AS ok", [hastaId, hash])
        coincide_ancla = c.rows[0]["ok"]
    cortes = await s.db.query("SELECT hasta_id::text, filas::text, creado_en FROM bitacora_cortes ORDER BY hasta_id")
    return ok(
        {
            "revisadas": int(f["revisadas"]),
            "valida": f["valida"] and coincide_ancla is not False,
            "cadenaValida": f["valida"],
            "primerError": f["primer_error"],
            "ultimoHash": f["ultimo_hash"],
            "coincideAncla": coincide_ancla,
            "cortes": [{"hastaId": c["hasta_id"], "filas": int(c["filas"]), "creadoEn": iso(c["creado_en"])} for c in cortes.rows],
            "verificadoEn": iso(datetime.now(timezone.utc)),
        }
    )


@router.post("/v1/admin/bitacora/anclar", summary="Enviar el ancla de la bitácora ahora")
async def anclar(s: Svc, u: Admin):
    return ok(await s.vigilancia.anclar(True))


@router.get("/v1/admin/alertas", summary="Alertas de seguridad enviadas")
async def alertas(s: Svc, u: Admin):
    r = await s.db.query(
        """SELECT id, regla, clave, detalle, destinatarios, creado_en AS "creadoEn"
           FROM alertas_seguridad ORDER BY creado_en DESC LIMIT 100"""
    )
    return ok(r.rows)
