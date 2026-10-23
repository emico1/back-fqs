"""Mi perfil, datos de contacto, sesiones, preferencias, privacidad, historial y dispositivos."""

from typing import Annotated, Literal

from fastapi import Query, Request
from pydantic import Field

from ..errores import HttpError
from ..http.dependencias import Svc, Usuario
from ..limites import VERIFICACION, cuenta_de, limiter
from ..seguridad.bitacora import registrar_evento
from ..seguridad.contrasenas import hash_contrasena, problema_contrasena, verificar_contrasena
from ..seguridad.sesiones import UsuarioSesion, listar_sesiones, revocar_familia, revocar_todas
from ..seguridad.verificacion import (
    VERIFICACION_INTENTOS,
    VERIFICACION_MINUTOS,
    codigo_coincide,
    enmascarar_correo,
    enmascarar_telefono,
    hash_verificacion,
    nuevo_codigo,
)
from ..servicios import Servicios
from ..tareas import en_segundo_plano
from ..validacion import (
    Booleano,
    ClaveCategoria,
    Contrasena,
    Correo,
    Fecha,
    Modelo,
    Telefono,
    Texto,
    Uuid,
    edad_en_anios,
    telefono_canonico,
)
from .comun import IdRuta, aceptado, ip, nuevo_router, ok, rid, sin_contenido
from .consultas import exigir_archivo_propio, perfil_completo

router = nuevo_router("perfil")


class EditarPerfil(Modelo):
    nombre: Texto(2, 120) | None = None
    ciudadId: Uuid | None = None
    fechaNacimiento: Fecha | None = None
    fotoClave: Uuid | None = None
    correo: Correo | None = None
    telefono: Telefono | None = None
    # Obligatoria solo para cambiar correo o teléfono, que son los datos de recuperación
    passwordActual: Contrasena | None = None


class Preferencias(Modelo):
    quiereDonar: Booleano
    quiereParticipar: Booleano
    quiereProponer: Booleano
    recibirRecordatorios: Booleano
    recibirSugerencias: Booleano
    categorias: Annotated[list[ClaveCategoria], Field(max_length=20)]


class CambioContrasena(Modelo):
    actual: Contrasena
    nueva: Contrasena


class Confirmar(Modelo):
    password: Contrasena


class Dispositivo(Modelo):
    tokenFcm: Texto(20, 4096)


class AceptarAviso(Modelo):
    avisoId: Uuid


class CodigoVerificacion(Modelo):
    codigo: Annotated[str, Field(pattern=r"^\d{8}$")]


async def _exigir_contrasena(s: Servicios, usuario_id: str, clave: str | None) -> None:
    if not clave:
        raise HttpError(400, "requiere_contrasena", "Confirma tu contraseña actual")
    r = await s.db.query("SELECT password_hash FROM usuarios WHERE id = $1", [usuario_id])
    if not await verificar_contrasena(clave, r.rows[0]["password_hash"] if r.rows else ""):
        raise HttpError(403, "contrasena_incorrecta", "La contraseña actual no es correcta")


@router.get("/v1/yo", summary="Mi perfil")
async def yo(s: Svc, u: Usuario):
    return ok(await perfil_completo(s.db, u.id))


async def _iniciar_cambio(s: Servicios, usuario_id: str, canal: str, nuevo: str) -> str:
    """
    Un correo o teléfono nuevo no se aplica hasta que se confirma con el código que le llega.
    Así nadie puede poner en su cuenta el dato de contacto de otra persona.
    """
    await s.db.query(
        "UPDATE verificaciones_contacto SET usado_en = now() WHERE usuario_id = $1 AND tipo = 'cambio' AND canal = $2 AND usado_en IS NULL",
        [usuario_id, canal],
    )
    ocupado = await s.db.query(
        "SELECT 1 FROM usuarios WHERE lower(correo) = $1" if canal == "correo" else "SELECT 1 FROM usuarios WHERE telefono = $1", [nuevo]
    )
    if ocupado.rows:
        # Misma respuesta que si estuviera libre. A un correo le llega un aviso, a un teléfono nada
        if canal == "correo":
            en_segundo_plano(s.correo.enviar_correo_ya_registrado(nuevo), "el correo de cuenta existente")
    else:
        codigo = nuevo_codigo()
        r = await s.db.query(
            """INSERT INTO verificaciones_contacto (tipo, canal, usuario_id, destino, codigo_hash, expira_en)
               VALUES ('cambio', $1, $2, $3, '0000000000000000000000000000000000000000000000000000000000000000',
                       now() + make_interval(mins => $4)) RETURNING id""",
            [canal, usuario_id, nuevo, VERIFICACION_MINUTOS],
        )
        ident = r.rows[0]["id"]
        await s.db.query("UPDATE verificaciones_contacto SET codigo_hash = $2 WHERE id = $1", [ident, hash_verificacion(ident, codigo)])
        if canal == "correo":
            en_segundo_plano(s.correo.enviar_verificacion(nuevo, codigo), "el correo de verificación")
        else:
            await s.sms.enviar_codigo(nuevo, codigo, "verificacion")
    return enmascarar_correo(nuevo) if canal == "correo" else enmascarar_telefono(nuevo)


@router.patch("/v1/yo", summary="Editar mi perfil")
async def editar(d: EditarPerfil, s: Svc, u: Usuario):
    presentes = d.model_fields_set
    if "correo" in presentes or "telefono" in presentes:
        await _exigir_contrasena(s, u.id, d.passwordActual)
    if d.fechaNacimiento and edad_en_anios(d.fechaNacimiento) < 18:
        raise HttpError(422, "edad", "La persona titular debe ser mayor de edad")
    telefono_nuevo = telefono_canonico(d.telefono) if d.telefono else None
    if telefono_nuevo:
        s.sms.exigir_disponible(telefono_nuevo)
    await exigir_archivo_propio(s.db, d.fotoClave, u.id)
    # Lista fija de columnas permitidas, el nombre de columna nunca sale del cliente
    columnas: list[tuple[str, object]] = []
    if d.nombre is not None:
        columnas.append(("nombre", d.nombre))
    if d.ciudadId is not None:
        columnas.append(("ciudad_id", d.ciudadId))
    if d.fechaNacimiento is not None:
        columnas.append(("fecha_nacimiento", d.fechaNacimiento))
    if "fotoClave" in presentes:
        columnas.append(("foto_clave", d.fotoClave))
    # Quitar el correo o el teléfono se aplica de inmediato (la base exige que quede uno)
    if "correo" in presentes and d.correo is None:
        columnas += [("correo", None), ("correo_verificado_en", None)]
    if "telefono" in presentes and d.telefono is None:
        columnas += [("telefono", None), ("telefono_verificado_en", None)]
    if columnas:
        sets = ", ".join(f"{c} = ${i + 2}" for i, (c, _) in enumerate(columnas))
        await s.db.query(f"UPDATE usuarios SET {sets} WHERE id = $1", [u.id, *[v for _, v in columnas]])
    actual = await s.db.query("SELECT correo, telefono FROM usuarios WHERE id = $1", [u.id])
    fila = actual.rows[0] if actual.rows else {}
    correo_pendiente = None
    telefono_pendiente = None
    if d.correo and (fila.get("correo") or "").lower() != d.correo:
        correo_pendiente = await _iniciar_cambio(s, u.id, "correo", d.correo)
    if telefono_nuevo and fila.get("telefono") != telefono_nuevo:
        telefono_pendiente = await _iniciar_cambio(s, u.id, "sms", telefono_nuevo)
    return ok({**(await perfil_completo(s.db, u.id)), "correoPendiente": correo_pendiente, "telefonoPendiente": telefono_pendiente})


async def _confirmar_cambio(s: Servicios, request: Request, u: UsuarioSesion, canal: str, codigo: str):
    """Confirma el dato nuevo con el código. Al correo anterior le llega un aviso del cambio."""
    columna = "correo" if canal == "correo" else "telefono"
    resultado = None
    async with s.db.transaccion() as c:
        r = await c.query(
            """SELECT id, destino, codigo_hash FROM verificaciones_contacto
               WHERE usuario_id = $1 AND tipo = 'cambio' AND canal = $2 AND usado_en IS NULL AND expira_en > now() AND intentos < $3
               ORDER BY creado_en DESC LIMIT 1 FOR UPDATE""",
            [u.id, canal, VERIFICACION_INTENTOS],
        )
        v = r.rows[0] if r.rows else None
        if v:
            if not codigo_coincide(v["id"], codigo, v["codigo_hash"]):
                await c.query("UPDATE verificaciones_contacto SET intentos = intentos + 1 WHERE id = $1", [v["id"]])
            else:
                await c.query("UPDATE verificaciones_contacto SET usado_en = now() WHERE id = $1", [v["id"]])
                anterior = await c.query("SELECT correo, telefono, correo_verificado_en FROM usuarios WHERE id = $1", [u.id])
                a = anterior.rows[0]
                # La columna sale de una lista fija, nunca del cliente
                await c.query(f"UPDATE usuarios SET {columna} = $2, {columna}_verificado_en = now() WHERE id = $1", [u.id, v["destino"]])
                resultado = {
                    "correoAviso": a["correo"] if a["correo_verificado_en"] else None,
                    "anterior": a["correo"] if canal == "correo" else a["telefono"],
                    "nuevo": v["destino"],
                }
    if not resultado:
        raise HttpError(400, "codigo_invalido", "El código es incorrecto o ya expiró")
    if resultado["correoAviso"] and resultado["anterior"] != resultado["nuevo"]:
        que = "el correo" if canal == "correo" else "el teléfono"
        visible = enmascarar_correo(resultado["nuevo"]) if canal == "correo" else enmascarar_telefono(resultado["nuevo"])
        en_segundo_plano(
            s.correo.enviar_aviso(
                resultado["correoAviso"],
                f"Cambiaste {que} de tu cuenta",
                [
                    f"{que[0].upper()}{que[1:]} de tu cuenta de Familias que Suman ahora es {visible}.",
                    "Si no fuiste tú, escríbenos de inmediato para recuperar tu cuenta.",
                ],
            ),
            "el aviso de cambio",
        )
    await registrar_evento(
        s.db, "correo_cambiado" if canal == "correo" else "telefono_cambiado", actor_id=u.id, actor_rol=u.rol, ip=ip(request), request_id=rid(request)
    )
    return ok(await perfil_completo(s.db, u.id))


@router.post("/v1/yo/correo/verificar", summary="Confirmar mi correo nuevo con el código")
@limiter.shared_limit(VERIFICACION, scope="verificacion_cuenta", key_func=cuenta_de)
async def verificar_correo(request: Request, d: CodigoVerificacion, s: Svc, u: Usuario):
    return await _confirmar_cambio(s, request, u, "correo", d.codigo)


@router.post("/v1/yo/telefono/verificar", summary="Confirmar mi teléfono nuevo con el código")
@limiter.shared_limit(VERIFICACION, scope="verificacion_cuenta", key_func=cuenta_de)
async def verificar_telefono(request: Request, d: CodigoVerificacion, s: Svc, u: Usuario):
    return await _confirmar_cambio(s, request, u, "sms", d.codigo)


# ---------------- Sesiones por dispositivo ----------------


@router.get("/v1/yo/sesiones", summary="Mis sesiones abiertas")
async def sesiones(s: Svc, u: Usuario):
    return ok(await listar_sesiones(s.db, u.id, u.familia_id))


@router.delete("/v1/yo/sesiones/{sesionId}", summary="Cerrar una sesión de otro dispositivo")
async def cerrar_sesion(request: Request, sesionId: IdRuta, s: Svc, u: Usuario):
    if not await revocar_familia(s.db, sesionId, u.id):
        raise HttpError(404, "no_encontrado", "Sesión no encontrada")
    await registrar_evento(s.db, "sesion_cerrada_remota", actor_id=u.id, actor_rol=u.rol, entidad_id=sesionId, ip=ip(request), request_id=rid(request))
    return sin_contenido()


@router.post("/v1/yo/sesiones/cerrar-otras", summary="Cerrar todas las demás sesiones")
async def cerrar_otras(request: Request, s: Svc, u: Usuario):
    await revocar_todas(s.db, u.id, u.familia_id)
    await registrar_evento(
        s.db, "sesion_cerrada_remota", actor_id=u.id, actor_rol=u.rol, detalles={"todasLasDemas": True}, ip=ip(request), request_id=rid(request)
    )
    return sin_contenido()


@router.put("/v1/yo/preferencias", summary="Mis preferencias e intereses")
async def preferencias(d: Preferencias, s: Svc, u: Usuario):
    async with s.db.transaccion() as c:
        await c.query(
            """INSERT INTO usuario_preferencias (usuario_id, quiere_donar, quiere_participar, quiere_proponer, recibir_recordatorios, recibir_sugerencias)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (usuario_id) DO UPDATE SET quiere_donar = EXCLUDED.quiere_donar, quiere_participar = EXCLUDED.quiere_participar,
                 quiere_proponer = EXCLUDED.quiere_proponer, recibir_recordatorios = EXCLUDED.recibir_recordatorios,
                 recibir_sugerencias = EXCLUDED.recibir_sugerencias""",
            [u.id, d.quiereDonar, d.quiereParticipar, d.quiereProponer, d.recibirRecordatorios, d.recibirSugerencias],
        )
        await c.query("DELETE FROM usuario_categorias WHERE usuario_id = $1", [u.id])
        await c.query(
            """INSERT INTO usuario_categorias (usuario_id, categoria_id)
               SELECT $1, id FROM categorias WHERE activa AND clave = ANY($2::text[])""",
            [u.id, d.categorias],
        )
    return ok(await perfil_completo(s.db, u.id))


@router.post("/v1/yo/contrasena", summary="Cambiar mi contraseña")
async def cambiar_contrasena(request: Request, d: CambioContrasena, s: Svc, u: Usuario):
    await _exigir_contrasena(s, u.id, d.actual)
    r = await s.db.query("SELECT nombre, username, correo FROM usuarios WHERE id = $1", [u.id])
    datos = r.rows[0]
    problema = problema_contrasena(d.nueva, [datos["nombre"], datos["username"], datos["correo"] or ""])
    if problema:
        raise HttpError(422, "contrasena_debil", problema)
    await s.filtradas.exigir_no_filtrada(d.nueva)
    await s.db.query("UPDATE usuarios SET password_hash = $1 WHERE id = $2", [await hash_contrasena(d.nueva), u.id])
    # Cierra las sesiones de otros dispositivos, conserva la actual
    await revocar_todas(s.db, u.id, u.familia_id)
    await registrar_evento(s.db, "contrasena_cambiada", actor_id=u.id, actor_rol=u.rol, ip=ip(request), request_id=rid(request))
    return sin_contenido()


@router.post("/v1/yo/eliminacion", summary="Solicitar la eliminación de mi cuenta (ARCO)")
async def eliminacion(d: Confirmar, s: Svc, u: Usuario):
    await _exigir_contrasena(s, u.id, d.password)
    async with s.db.transaccion() as c:
        await c.query("INSERT INTO solicitudes_eliminacion (usuario_id) VALUES ($1)", [u.id])
        await c.query("UPDATE usuarios SET estado = 'pendiente_eliminacion' WHERE id = $1", [u.id])
        await revocar_todas(c, u.id)
    s.cupos.desconectar(u.id)
    return aceptado({"mensaje": "Recibimos tu solicitud, tu cuenta quedó desactivada mientras la atendemos"})


# ---------------- Privacidad (RF-15) ----------------


@router.get("/v1/yo/privacidad", summary="Aviso de privacidad vigente y mi aceptación")
async def privacidad(s: Svc, u: Usuario):
    r = await s.db.query(
        """SELECT CASE WHEN v.id IS NULL THEN NULL ELSE json_build_object(
                    'id', v.id, 'version', v.version, 'contenido', v.contenido, 'publicadoEn', v.publicado_en) END AS aviso,
                  ap.aceptado_en AS "aceptadoEn",
                  (SELECT json_build_object('estado', se.estado, 'solicitadaEn', se.solicitada_en)
                   FROM solicitudes_eliminacion se WHERE se.usuario_id = $1 AND se.estado <> 'resuelta') AS "solicitudEliminacion"
           FROM (SELECT 1) uno
           LEFT JOIN aviso_privacidad_vigente v ON true
           LEFT JOIN aceptaciones_privacidad ap ON ap.aviso_id = v.id AND ap.usuario_id = $1""",
        [u.id],
    )
    fila = r.rows[0]
    return ok({**fila, "aceptado": fila["aceptadoEn"] is not None})


@router.post("/v1/yo/privacidad/aceptar", summary="Aceptar el aviso de privacidad vigente")
async def aceptar_aviso(d: AceptarAviso, s: Svc, u: Usuario):
    v = await s.db.query("SELECT id FROM aviso_privacidad_vigente")
    if not v.rows or v.rows[0]["id"] != d.avisoId:
        raise HttpError(409, "aviso_actualizado", "El aviso de privacidad cambió, revísalo y acéptalo de nuevo")
    await s.db.query("INSERT INTO aceptaciones_privacidad (usuario_id, aviso_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", [u.id, d.avisoId])
    return ok(await perfil_completo(s.db, u.id))


@router.get("/v1/yo/inscripciones", summary="Mis inscripciones")
async def inscripciones(s: Svc, u: Usuario, momento: Annotated[Literal["proximas", "pasadas", "todas"], Query()] = "todas"):
    orden = "ASC" if momento == "proximas" else "DESC"
    r = await s.db.query(
        f"""SELECT i.id, i.estado, i.cantidad_personas AS "cantidadPersonas", i.fecha_inscripcion AS "fechaInscripcion",
                   EXISTS (SELECT 1 FROM inscripcion_participantes p WHERE p.inscripcion_id = i.id AND p.es_titular) AS "titularAsiste",
                   COALESCE((SELECT json_agg(p.miembro_comunidad_id) FROM inscripcion_participantes p
                             WHERE p.inscripcion_id = i.id AND NOT p.es_titular), '[]') AS miembros,
                   EXISTS (SELECT 1 FROM inscripcion_participantes p WHERE p.inscripcion_id = i.id AND p.estado_asistencia = 'asistio') AS asistio,
                   (SELECT t.estado FROM testimonios t WHERE t.inscripcion_id = i.id) AS "estadoTestimonio",
                   (SELECT v.valor FROM valoraciones_actividades v WHERE v.inscripcion_id = i.id) AS valoracion,
                   json_build_object('id', a.id, 'titulo', a.titulo, 'inicio', a.inicio, 'fin', a.fin, 'direccion', a.direccion,
                                     'estado', a.estado, 'zonaHoraria', ci.zona_horaria,
                                     'asociacion', aso.nombre, 'categoriaClave', ca.clave, 'tipo', a.tipo) AS actividad
            FROM inscripciones i
            JOIN actividades a ON a.id = i.actividad_id
            JOIN asociaciones aso ON aso.id = a.asociacion_id
            JOIN categorias ca ON ca.id = a.categoria_id
            JOIN ciudades ci ON ci.id = a.ciudad_id
            WHERE i.usuario_id = $1
              AND ($2::text = 'todas' OR ($2::text = 'proximas' AND a.fin > now() AND i.estado = 'confirmada')
                   OR ($2::text = 'pasadas' AND a.fin <= now()))
            ORDER BY a.inicio {orden}
            LIMIT 200""",
        [u.id, momento],
    )
    return ok(r.rows)


@router.get("/v1/yo/entregas", summary="Mis entregas de donativos")
async def entregas(s: Svc, u: Usuario):
    r = await s.db.query(
        """SELECT e.id, e.cantidad, e.estado, e.comentario, e.creado_en AS "creadoEn", e.recibida_en AS "recibidaEn",
                  json_build_object('id', ar.id, 'nombre', ar.nombre, 'unidad', ar.unidad) AS articulo,
                  json_build_object('id', cp.id, 'titulo', cp.titulo) AS campana,
                  json_build_object('id', pe.id, 'nombre', pe.nombre, 'direccion', pe.direccion) AS "puntoEntrega"
           FROM entregas_donacion e
           JOIN campana_articulos ar ON ar.id = e.articulo_id
           JOIN campanas cp ON cp.id = ar.campana_id
           JOIN puntos_entrega pe ON pe.id = e.punto_entrega_id
           WHERE e.usuario_id = $1 ORDER BY e.creado_en DESC LIMIT 100""",
        [u.id],
    )
    return ok([{**f, "cantidad": float(f["cantidad"])} for f in r.rows])


@router.put("/v1/yo/dispositivos", summary="Registrar el token de notificaciones de este teléfono")
async def registrar_dispositivo(d: Dispositivo, s: Svc, u: Usuario):
    # Si el token estaba ligado a otra cuenta (otra persona usó el teléfono), pasa a esta
    await s.db.query(
        """INSERT INTO dispositivos (usuario_id, token_fcm) VALUES ($1, $2)
           ON CONFLICT (token_fcm) DO UPDATE SET usuario_id = EXCLUDED.usuario_id, ultima_conexion = now()""",
        [u.id, d.tokenFcm],
    )
    return sin_contenido()


@router.delete("/v1/yo/dispositivos", summary="Quitar el token de notificaciones de este teléfono")
async def quitar_dispositivo(d: Dispositivo, s: Svc, u: Usuario):
    await s.db.query("DELETE FROM dispositivos WHERE usuario_id = $1 AND token_fcm = $2", [u.id, d.tokenFcm])
    return sin_contenido()
