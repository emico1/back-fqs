"""Registro, verificación, inicio de sesión, segundo factor, renovación, cierre y recuperación."""

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Request
from pydantic import Field

from ..db import Consultable
from ..errores import HttpError
from ..http.dependencias import Svc
from ..limites import LOGIN, RECUPERACION, REFRESH, REGISTRO, VERIFICACION, limiter
from ..seguridad.acceso import abrir_sesion, agente_de, canjear_desafio, normalizar_identificador, verificar_credenciales
from ..seguridad.bitacora import registrar_evento
from ..seguridad.contrasenas import hash_contrasena, problema_contrasena
from ..seguridad.sesiones import duraciones_de, emitir_sesion, revocar_por_refresh, revocar_todas, rotar_sesion
from ..seguridad.verificacion import (
    VERIFICACION_INTENTOS,
    VERIFICACION_MINUTOS,
    VERIFICACION_REENVIOS,
    codigo_coincide,
    enmascarar_correo,
    enmascarar_telefono,
    hash_verificacion,
    nuevo_codigo,
)
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
    Username,
    Uuid,
    edad_en_anios,
    error_validacion,
    telefono_canonico,
)
from .comun import aceptado, creado, ip, nuevo_router, ok, rid, sin_contenido
from .consultas import perfil_completo

router = nuevo_router("auth")

Codigo8 = Annotated[str, Field(pattern=r"^\d{8}$")]


class PreferenciasRegistro(Modelo):
    quiereDonar: Booleano = False
    quiereParticipar: Booleano = False
    quiereProponer: Booleano = False


class Registro(Modelo):
    nombre: Texto(2, 120)
    username: Username
    correo: Correo | None = None
    telefono: Telefono | None = None
    password: Contrasena
    fechaNacimiento: Fecha
    ciudadId: Uuid
    avisoPrivacidadId: Uuid
    preferencias: PreferenciasRegistro = Field(default_factory=PreferenciasRegistro)
    categorias: Annotated[list[ClaveCategoria], Field(max_length=20)] = []


class Login(Modelo):
    identificador: Texto(3, 254)
    password: Contrasena


class Refresh(Modelo):
    refreshToken: Annotated[str, Field(max_length=200)]


class SegundoPaso(Modelo):
    desafio: Annotated[str, Field(max_length=120)]
    codigo: Texto(6, 12)


class Recuperar(Modelo):
    identificador: Texto(3, 254)


class Restablecer(Modelo):
    identificador: Texto(3, 254)
    codigo: Codigo8
    password: Contrasena


class VerificarRegistro(Modelo):
    registroId: Uuid
    codigo: Codigo8


class Reenviar(Modelo):
    registroId: Uuid


def _hash_codigo(usuario_id: str, codigo: str) -> str:
    return hashlib.sha256(f"{usuario_id}|{codigo}".encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


async def _exigir_aviso_vigente(db: Consultable, aviso_id: str) -> None:
    aviso = await db.query("SELECT id FROM aviso_privacidad_vigente")
    if not aviso.rows:
        raise HttpError(503, "registro_no_disponible", "El registro aún no está disponible")
    if aviso.rows[0]["id"] != aviso_id:
        raise HttpError(409, "aviso_actualizado", "El aviso de privacidad cambió, revísalo y acéptalo de nuevo")


async def _crear_cuenta(c: Consultable, d: dict, canal: str, destino: str) -> str:
    """
    Crea la cuenta dentro de una transacción. Todas las cuentas son individuales por decisión
    del socio formador. La familia se arma con acompañantes dentro de la cuenta.
    """
    await _exigir_aviso_vigente(c, d["avisoPrivacidadId"])
    u = await c.query(
        # El dato de contacto ya se comprobó con el código, se guarda como verificado
        """INSERT INTO usuarios (nombre, username, correo, telefono, password_hash, tipo_cuenta, fecha_nacimiento, ciudad_id,
                                 correo_verificado_en, telefono_verificado_en)
           VALUES ($1, $2, $3, $4, $5, 'individual', $6, $7,
                   CASE WHEN $3::text IS NULL THEN NULL ELSE now() END, CASE WHEN $4::text IS NULL THEN NULL ELSE now() END)
           RETURNING id""",
        [
            d["nombre"],
            d["username"],
            destino if canal == "correo" else None,
            destino if canal == "sms" else None,
            d["passwordHash"],
            d["fechaNacimiento"],
            d["ciudadId"],
        ],
    )
    ident = u.rows[0]["id"]
    p = d["preferencias"]
    await c.query(
        "INSERT INTO usuario_preferencias (usuario_id, quiere_donar, quiere_participar, quiere_proponer) VALUES ($1, $2, $3, $4)",
        [ident, p["quiereDonar"], p["quiereParticipar"], p["quiereProponer"]],
    )
    await c.query(
        """INSERT INTO usuario_categorias (usuario_id, categoria_id)
           SELECT $1, id FROM categorias WHERE activa AND clave = ANY($2::text[])""",
        [ident, d["categorias"]],
    )
    await c.query("INSERT INTO aceptaciones_privacidad (usuario_id, aviso_id) VALUES ($1, $2)", [ident, d["avisoPrivacidadId"]])
    return ident


@router.post("/v1/auth/registro", summary="Registro de una cuenta nueva")
@limiter.limit(REGISTRO)
async def registro(request: Request, d: Registro, s: Svc):
    """
    La cuenta no se crea hasta que la persona escribe el código que le llega por correo o por
    SMS, así nadie puede apartar el correo o el teléfono de otra persona. La respuesta es la
    misma exista o no una cuenta con ese dato. Si ya existe, a un correo le llega un aviso y a
    un teléfono no se le manda nada (cada SMS cuesta).
    """
    # Un solo dato de contacto al registrarse, porque es el que se verifica. El otro se agrega
    # después desde el perfil y también se verifica
    if bool(d.correo) == bool(d.telefono):
        raise error_validacion("correo", "Indica un correo o un teléfono, solo uno. El otro lo puedes agregar después en tu perfil")
    problema = problema_contrasena(d.password, [d.nombre, d.username, d.correo or ""])
    if problema:
        raise HttpError(422, "contrasena_debil", problema)
    # La cuenta titular es de una persona adulta. Los menores participan como acompañantes
    # registrados por su familia (ver miembros_comunidad)
    edad = edad_en_anios(d.fechaNacimiento)
    if edad < 18:
        raise HttpError(422, "edad", "Debes ser mayor de edad para crear una cuenta")
    if edad > 120:
        raise HttpError(422, "edad", "Fecha de nacimiento inválida")
    canal = "correo" if d.correo else "sms"
    destino = d.correo or telefono_canonico(d.telefono or "")
    if canal == "sms":
        s.sms.exigir_disponible(destino)
    await s.filtradas.exigir_no_filtrada(d.password)
    await _exigir_aviso_vigente(s.db, d.avisoPrivacidadId)
    en_uso = await s.db.query("SELECT 1 FROM usuarios WHERE username = $1", [d.username])
    if en_uso.rows:
        raise HttpError(409, "duplicado", "Ese username ya está en uso")

    datos = {
        "nombre": d.nombre,
        "username": d.username,
        "passwordHash": await hash_contrasena(d.password),
        "fechaNacimiento": d.fechaNacimiento,
        "ciudadId": d.ciudadId,
        "avisoPrivacidadId": d.avisoPrivacidadId,
        "preferencias": d.preferencias.model_dump(),
        "categorias": d.categorias,
    }
    existente = await s.db.query(
        "SELECT 1 FROM usuarios WHERE lower(correo) = $1" if canal == "correo" else "SELECT 1 FROM usuarios WHERE telefono = $1",
        [destino],
    )
    registro_id = str(uuid.uuid4())
    expira_en = _iso(datetime.now(timezone.utc) + timedelta(minutes=VERIFICACION_MINUTOS))
    if existente.rows:
        # Mismo formato de respuesta con un id que no existe, el código nunca funcionará
        if canal == "correo":
            en_segundo_plano(s.correo.enviar_correo_ya_registrado(destino), "el correo de cuenta existente")
    else:
        codigo = nuevo_codigo()
        r = await s.db.query(
            """INSERT INTO verificaciones_contacto (id, tipo, canal, destino, datos, codigo_hash, expira_en)
               VALUES ($1, 'registro', $2, $3, $4::jsonb, $5, now() + make_interval(mins => $6)) RETURNING expira_en""",
            [registro_id, canal, destino, json.dumps(datos), hash_verificacion(registro_id, codigo), VERIFICACION_MINUTOS],
        )
        expira_en = _iso(r.rows[0]["expira_en"])
        if canal == "correo":
            en_segundo_plano(s.correo.enviar_verificacion(destino, codigo), "el correo de verificación")
        else:
            await s.sms.enviar_codigo(destino, codigo, "verificacion")
    return aceptado(
        {
            "registroId": registro_id,
            "canal": canal,
            "destino": enmascarar_correo(destino) if canal == "correo" else enmascarar_telefono(destino),
            "expiraEn": expira_en,
            "mensaje": "Te enviamos un código de 8 dígitos a tu correo. Escríbelo para terminar tu registro."
            if canal == "correo"
            else "Te enviamos un código de 8 dígitos por SMS. Escríbelo para terminar tu registro.",
        }
    )


@router.post("/v1/auth/registro/verificar", summary="Terminar el registro con el código")
@limiter.shared_limit(VERIFICACION, scope="verificacion")
async def verificar_registro(request: Request, d: VerificarRegistro, s: Svc):
    resultado = None
    async with s.db.transaccion() as c:
        r = await c.query(
            """SELECT destino, canal, datos, codigo_hash FROM verificaciones_contacto
               WHERE id = $1 AND tipo = 'registro' AND usado_en IS NULL AND expira_en > now() AND intentos < $2 FOR UPDATE""",
            [d.registroId, VERIFICACION_INTENTOS],
        )
        v = r.rows[0] if r.rows else None
        if v:
            if not codigo_coincide(d.registroId, d.codigo, v["codigo_hash"]):
                await c.query("UPDATE verificaciones_contacto SET intentos = intentos + 1 WHERE id = $1", [d.registroId])
            else:
                # Este y los demás registros pendientes con el mismo dato ya no sirven
                await c.query(
                    """UPDATE verificaciones_contacto SET usado_en = now()
                       WHERE tipo = 'registro' AND lower(destino) = lower($1) AND usado_en IS NULL""",
                    [v["destino"]],
                )
                ident = await _crear_cuenta(c, v["datos"], v["canal"], v["destino"])
                tokens = await emitir_sesion(c, ident, duraciones_de(s.config), agente=agente_de(request))
                resultado = {"tokens": tokens, "usuario": await perfil_completo(c, ident)}
    if not resultado:
        raise HttpError(400, "codigo_invalido", "El código es incorrecto o ya expiró")
    return creado(resultado)


@router.post("/v1/auth/registro/reenviar", summary="Reenviar el código del registro")
@limiter.shared_limit(VERIFICACION, scope="verificacion")
async def reenviar(request: Request, d: Reenviar, s: Svc):
    codigo = nuevo_codigo()
    r = await s.db.query(
        """UPDATE verificaciones_contacto
           SET codigo_hash = $2, expira_en = now() + make_interval(mins => $3), reenvios = reenvios + 1
           WHERE id = $1 AND tipo = 'registro' AND usado_en IS NULL AND reenvios < $4 AND intentos < $5
           RETURNING destino, canal""",
        [d.registroId, hash_verificacion(d.registroId, codigo), VERIFICACION_MINUTOS, VERIFICACION_REENVIOS, VERIFICACION_INTENTOS],
    )
    fila = r.rows[0] if r.rows else None
    if fila and fila["canal"] == "correo":
        en_segundo_plano(s.correo.enviar_verificacion(fila["destino"], codigo), "el correo de verificación")
    if fila and fila["canal"] == "sms":
        await s.sms.enviar_codigo(fila["destino"], codigo, "verificacion")
    # Misma respuesta siempre, no revela si el id existe
    return aceptado({"mensaje": "Si el registro sigue pendiente, enviamos un código nuevo"})


@router.post("/v1/auth/login", summary="Iniciar sesión")
@limiter.shared_limit(LOGIN, scope="login")
async def login(request: Request, d: Login, s: Svc):
    cuenta = await verificar_credenciales(s, request, d.identificador, d.password)
    r = await abrir_sesion(s, request, cuenta)
    # Administración con segundo factor activo, la contraseña sola no basta. Se entrega un
    # desafío de un solo uso que vence en 5 minutos y se canjea con el código de la app
    if r["tipo"] == "desafio":
        return ok({"requiere2fa": True, "desafio": r["desafio"], "desafioExpiraEn": r["expiraEn"]})
    respuesta = {"tokens": r["tokens"], "usuario": await perfil_completo(s.db, r["usuarioId"])}
    if r["rol"] == "admin":
        # La app y el panel usan esto para llevar a la persona a activar su app de autenticación
        respuesta["configurar2fa"] = s.config.ADMIN_2FA == "obligatorio"
    return ok(respuesta)


@router.post("/v1/auth/2fa", summary="Segundo paso del inicio de sesión de administración")
@limiter.shared_limit(LOGIN, scope="login")
async def segundo_paso(request: Request, d: SegundoPaso, s: Svc):
    r = await canjear_desafio(s, request, d.desafio, d.codigo)
    return ok({"tokens": r["tokens"], "usuario": await perfil_completo(s.db, r["usuarioId"])})


@router.post("/v1/auth/refresh", summary="Renovar la sesión")
@limiter.shared_limit(REFRESH, scope="refresh")
async def refresh(request: Request, d: Refresh, s: Svc):
    tokens = await rotar_sesion(s.db, d.refreshToken, duraciones_de(s.config), agente_de(request), ip(request))
    return ok({"tokens": tokens})


@router.post("/v1/auth/logout", summary="Cerrar sesión")
async def logout(d: Refresh, s: Svc):
    # Funciona aunque el access token ya haya expirado, solo necesita el refresh
    await revocar_por_refresh(s.db, d.refreshToken)
    return sin_contenido()


@router.post("/v1/auth/recuperar", summary="Pedir un código para recuperar la contraseña")
@limiter.shared_limit(RECUPERACION, scope="recuperacion")
async def recuperar(request: Request, d: Recuperar, s: Svc):
    """
    Siempre responde igual exista o no la cuenta, para no revelar quién está registrado. El
    código va al dato con el que se pidió, solo si está verificado. Por correo o por SMS.
    """
    ident = normalizar_identificador(d.identificador)
    s.limites.recuperacion_cuenta.consumir(f"cuenta {ident}")
    por_correo = "@" in ident
    r = await s.db.query(
        """SELECT id, correo AS destino FROM usuarios
           WHERE estado = 'activo' AND correo_verificado_en IS NOT NULL AND lower(correo) = $1"""
        if por_correo
        else """SELECT id, telefono AS destino FROM usuarios
                WHERE estado = 'activo' AND telefono_verificado_en IS NOT NULL AND telefono = $1""",
        [ident],
    )
    u = r.rows[0] if r.rows else None
    if u and (por_correo or s.sms.disponible):
        codigo = f"{secrets.randbelow(100_000_000):08d}"
        async with s.db.transaccion() as c:
            await c.query("UPDATE tokens_recuperacion SET usado_en = now() WHERE usuario_id = $1 AND usado_en IS NULL", [u["id"]])
            await c.query(
                "INSERT INTO tokens_recuperacion (usuario_id, token_hash, expira_en) VALUES ($1, $2, now() + interval '30 minutes')",
                [u["id"], _hash_codigo(u["id"], codigo)],
            )
        # El envío no se espera. Así la respuesta tarda lo mismo exista o no la cuenta y el
        # tiempo de respuesta no revela quién está registrado
        if por_correo:
            en_segundo_plano(s.correo.enviar_recuperacion(u["destino"], codigo), "el correo de recuperación")
        else:
            await s.sms.enviar_codigo(u["destino"], codigo, "recuperacion")
        await registrar_evento(
            s.db,
            "recuperacion_solicitada",
            actor_id=u["id"],
            ip=ip(request),
            request_id=rid(request),
            detalles={"canal": "correo" if por_correo else "sms"},
        )
    return aceptado({"mensaje": "Si la cuenta existe, enviamos un código a su correo o por SMS"})


@router.post("/v1/auth/restablecer", summary="Poner una contraseña nueva con el código")
@limiter.shared_limit(RECUPERACION, scope="recuperacion")
async def restablecer(request: Request, d: Restablecer, s: Svc):
    ident = normalizar_identificador(d.identificador)
    # Máximo 5 intentos por cuenta cada 15 minutos, así un código de 8 dígitos que vence en
    # 30 minutos no se puede adivinar por fuerza bruta
    s.limites.login_cuenta.consumir(f"codigo {ident}")
    invalido = HttpError(400, "codigo_invalido", "El código es incorrecto o ya expiró")
    # Se revisa antes del código para no gastarlo con una contraseña que se va a rechazar
    await s.filtradas.exigir_no_filtrada(d.password)
    async with s.db.transaccion() as c:
        u = await c.query(
            "SELECT id, nombre, username, correo FROM usuarios WHERE estado = 'activo' AND (lower(correo) = $1 OR telefono = $1)",
            [ident],
        )
        if not u.rows:
            raise invalido
        usuario = u.rows[0]
        t = await c.query(
            """SELECT id FROM tokens_recuperacion
               WHERE usuario_id = $1 AND token_hash = $2 AND usado_en IS NULL AND expira_en > now() FOR UPDATE""",
            [usuario["id"], _hash_codigo(usuario["id"], d.codigo)],
        )
        if not t.rows:
            raise invalido
        problema = problema_contrasena(d.password, [usuario["nombre"], usuario["username"], usuario["correo"] or ""])
        if problema:
            raise HttpError(422, "contrasena_debil", problema)
        await c.query("UPDATE usuarios SET password_hash = $1 WHERE id = $2", [await hash_contrasena(d.password), usuario["id"]])
        await c.query("UPDATE tokens_recuperacion SET usado_en = now() WHERE id = $1", [t.rows[0]["id"]])
        await revocar_todas(c, usuario["id"])
    s.limites.login_cuenta.reiniciar(f"codigo {ident}")
    s.limites.login_cuenta.reiniciar(f"cuenta {ident}")
    await registrar_evento(s.db, "contrasena_restablecida", actor_id=usuario["id"], ip=ip(request), request_id=rid(request))
    return sin_contenido()
