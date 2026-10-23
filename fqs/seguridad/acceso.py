"""
Inicio de sesión compartido por la app (tokens en el cuerpo) y el panel web (tokens en
cookies). Aquí viven los límites por cuenta, el mensaje único para cuenta inexistente o
contraseña equivocada, el segundo factor y los eventos de bitácora, así ninguna de las dos
entradas puede quedar más débil que la otra.
"""

from dataclasses import dataclass

from starlette.requests import Request

from .. import metricas
from ..errores import HttpError
from ..validacion import telefono_canonico
from .bitacora import registrar_evento
from .contrasenas import hash_contrasena, necesita_rehash, senuelo, verificar_contrasena
from .sesiones import duraciones_de, emitir_sesion


def normalizar_identificador(v: str) -> str:
    """Correo en minúsculas o teléfono en formato único (+52 y 10 dígitos), para buscar y para los límites."""
    t = v.strip()
    return t.lower() if "@" in t else telefono_canonico(t)


@dataclass
class CuentaVerificada:
    id: str
    rol: str


def agente_de(request: Request) -> str | None:
    return request.headers.get("user-agent")


def ip(request: Request) -> str:
    return request.state.ip


def request_id(request: Request) -> str:
    return request.state.request_id


async def verificar_credenciales(s, request: Request, identificador: str, password: str) -> CuentaVerificada:  # noqa: ANN001
    """Revisa correo o teléfono y contraseña. Lanza 401, 403 o 429 con el mensaje adecuado."""
    db = s.db
    limites = s.limites
    ident = normalizar_identificador(identificador)
    clave_cuenta = f"cuenta {ident}"
    if limites.login_cuenta.bloqueado(clave_cuenta):
        metricas.inicio_sesion("cuenta_bloqueada")
        raise HttpError(429, "cuenta_bloqueada", "Demasiados intentos fallidos, espera 15 minutos")
    r = await db.query(
        """SELECT id, password_hash, estado, rol FROM usuarios
           WHERE estado <> 'eliminado' AND (lower(correo) = $1 OR telefono = $1)""",
        [ident],
    )
    u = r.rows[0] if r.rows else None
    valida = await verificar_contrasena(password, u["password_hash"] if u else await senuelo())
    if not u or not valida:
        limites.login_cuenta.consumir(clave_cuenta)
        metricas.inicio_sesion("credenciales")
        # Los intentos fallidos contra una cuenta de administración quedan en la bitácora
        if u and u["rol"] == "admin":
            await registrar_evento(
                db, "login_admin_fallido", actor_id=u["id"], actor_rol="admin", ip=ip(request), request_id=request_id(request)
            )
        raise HttpError(401, "credenciales", "Correo, teléfono o contraseña incorrectos")
    limites.login_cuenta.reiniciar(clave_cuenta)
    if u["estado"] == "suspendido":
        metricas.inicio_sesion("suspendida")
        raise HttpError(403, "suspendida", "Tu cuenta está suspendida, contacta a soporte")
    if u["estado"] == "pendiente_eliminacion":
        metricas.inicio_sesion("en_eliminacion")
        raise HttpError(403, "en_eliminacion", "Tu cuenta tiene una solicitud de eliminación en curso")
    if necesita_rehash(u["password_hash"]):
        await db.query("UPDATE usuarios SET password_hash = $1 WHERE id = $2", [await hash_contrasena(password), u["id"]])
    return CuentaVerificada(u["id"], u["rol"])


async def abrir_sesion(s, request: Request, cuenta: CuentaVerificada) -> dict:  # noqa: ANN001
    """
    Con la cuenta ya verificada, entrega la sesión o, si es administración con segundo factor
    activo, un desafío que se canjea con el código.
    Devuelve {"tipo": "sesion", ...} o {"tipo": "desafio", ...}.
    """
    db = s.db
    ag = agente_de(request)
    if cuenta.rol == "admin" and await s.segundo_factor.activo(db, cuenta.id):
        d = await s.segundo_factor.crear_desafio(cuenta.id, ag)
        metricas.inicio_sesion("desafio_2fa")
        await registrar_evento(db, "2fa_desafio", actor_id=cuenta.id, actor_rol="admin", ip=ip(request), request_id=request_id(request))
        return {"tipo": "desafio", "desafio": d["desafio"], "expiraEn": d["expiraEn"]}
    tokens = await emitir_sesion(db, cuenta.id, duraciones_de(s.config), agente=ag)
    metricas.inicio_sesion("correcto")
    if cuenta.rol == "admin":
        await registrar_evento(
            db,
            "login_admin",
            actor_id=cuenta.id,
            actor_rol="admin",
            ip=ip(request),
            request_id=request_id(request),
            detalles={"segundoFactor": False, "dispositivo": ag[:120] if ag else None},
        )
    return {"tipo": "sesion", "usuarioId": cuenta.id, "rol": cuenta.rol, "tokens": tokens}


async def canjear_desafio(s, request: Request, desafio: str, codigo: str) -> dict:  # noqa: ANN001
    """Segundo paso del inicio de sesión de administración."""
    db = s.db
    limites = s.limites
    ag = agente_de(request)
    resultado: dict
    async with db.transaccion() as c:
        d = await s.segundo_factor.tomar_desafio(c, desafio)
        if not d:
            resultado = {"tipo": "invalido"}
        else:
            # Además del tope por desafío, máximo 5 códigos equivocados por cuenta cada 15 minutos
            clave_codigo = f"2fa {d['usuario_id']}"
            if limites.login_cuenta.bloqueado(clave_codigo):
                resultado = {"tipo": "bloqueado"}
            else:
                metodo = await s.segundo_factor.verificar(c, d["usuario_id"], codigo)
                if not metodo:
                    await c.query("UPDATE desafios_2fa SET intentos = intentos + 1 WHERE id = $1", [d["id"]])
                    limites.login_cuenta.consumir(clave_codigo)
                    resultado = {"tipo": "codigo", "usuarioId": d["usuario_id"], "restantes": 5 - d["intentos"] - 1}
                else:
                    limites.login_cuenta.reiniciar(clave_codigo)
                    await c.query("UPDATE desafios_2fa SET usado_en = now() WHERE id = $1", [d["id"]])
                    tokens = await emitir_sesion(c, d["usuario_id"], duraciones_de(s.config), agente=ag, segundo_factor=True)
                    resultado = {"tipo": "ok", "usuarioId": d["usuario_id"], "metodo": metodo, "tokens": tokens}

    metricas.inicio_sesion(
        {"invalido": "2fa_expirado", "bloqueado": "2fa_bloqueado", "codigo": "2fa_fallido", "ok": "2fa_correcto"}[resultado["tipo"]]
    )
    if resultado["tipo"] == "invalido":
        raise HttpError(401, "desafio_invalido", "La verificación expiró, vuelve a escribir tu contraseña")
    if resultado["tipo"] == "bloqueado":
        raise HttpError(429, "cuenta_bloqueada", "Demasiados códigos incorrectos, espera 15 minutos")
    base = {"actor_id": resultado["usuarioId"], "actor_rol": "admin", "ip": ip(request), "request_id": request_id(request)}
    if resultado["tipo"] == "codigo":
        await registrar_evento(db, "2fa_fallido", **base)
        raise HttpError(401, "codigo_2fa", "El código no es correcto", {"intentosRestantes": max(0, resultado["restantes"])})
    await registrar_evento(
        db,
        "2fa_codigo_respaldo_usado" if resultado["metodo"] == "respaldo" else "2fa_correcto",
        detalles={"dispositivo": ag[:120] if ag else None},
        **base,
    )
    return {"usuarioId": resultado["usuarioId"], "tokens": resultado["tokens"]}
