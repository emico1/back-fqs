"""
Segundo factor de las cuentas de administración. El secreto TOTP se guarda cifrado y solo se
descifra en memoria para comparar el código.
"""

import re

from ..db import Consultable, Db
from ..errores import HttpError
from ..jsonfmt import iso
from .tokens import formato_valido, hash_token, nuevo_token
from .totp import (
    CifradoSecretos,
    base32,
    hash_codigo_respaldo,
    normalizar_codigo_respaldo,
    nuevo_secreto,
    nuevos_codigos_respaldo,
    uri_otpauth,
    verificar_totp,
)

# Minutos que tiene la persona para escribir el código después de la contraseña
DESAFIO_MINUTOS = 5
# Intentos de código por desafío. Después hay que volver a escribir la contraseña
DESAFIO_INTENTOS = 5


class SegundoFactor:
    def __init__(self, db: Db, cifrado: CifradoSecretos | None) -> None:
        self.db = db
        self.cifrado = cifrado

    @property
    def disponible(self) -> bool:
        return self.cifrado is not None

    def _exigir_cifrado(self) -> CifradoSecretos:
        if self.cifrado is None:
            raise HttpError(503, "2fa_no_configurado", "El segundo factor no está configurado en el servidor (falta CLAVE_CIFRADO_2FA)")
        return self.cifrado

    async def activo(self, db: Consultable, usuario_id: str) -> bool:
        r = await db.query("SELECT activo FROM usuarios_2fa WHERE usuario_id = $1", [usuario_id])
        return bool(r.rows and r.rows[0]["activo"])

    async def estado(self, usuario_id: str) -> dict:
        r = await self.db.query(
            """SELECT coalesce(f.activo, false) AS activo, f.activado_en,
                      (SELECT count(*) FROM codigos_respaldo_2fa c WHERE c.usuario_id = $1 AND c.usado_en IS NULL) AS restantes
               FROM (SELECT $1::uuid AS id) u LEFT JOIN usuarios_2fa f ON f.usuario_id = u.id""",
            [usuario_id],
        )
        f = r.rows[0]
        return {"activo": f["activo"], "activadoEn": iso(f["activado_en"]), "codigosRespaldoRestantes": int(f["restantes"])}

    async def iniciar(self, usuario_id: str, cuenta: str) -> dict:
        """
        Genera un secreto nuevo sin activarlo. Se activa hasta que la persona demuestra que su
        app ya genera códigos correctos (confirmar). Si ya está activo no se puede reemplazar.
        """
        cifrado = self._exigir_cifrado()
        secreto = nuevo_secreto()
        r = await self.db.query(
            """INSERT INTO usuarios_2fa (usuario_id, secreto_cifrado) VALUES ($1, $2)
               ON CONFLICT (usuario_id) DO UPDATE SET secreto_cifrado = EXCLUDED.secreto_cifrado, ultimo_paso = 0
               WHERE NOT usuarios_2fa.activo""",
            [usuario_id, cifrado.cifrar(secreto, usuario_id)],
        )
        if r.rowcount == 0:
            raise HttpError(409, "2fa_ya_activo", "El segundo factor ya está activo en esta cuenta")
        return {"secreto": base32(secreto), "uri": uri_otpauth(secreto, cuenta)}

    async def confirmar(self, usuario_id: str, codigo: str) -> list[str]:
        """Activa el segundo factor con el primer código correcto y entrega los códigos de respaldo."""
        cifrado = self._exigir_cifrado()
        async with self.db.transaccion() as c:
            r = await c.query("SELECT secreto_cifrado, activo FROM usuarios_2fa WHERE usuario_id = $1 FOR UPDATE", [usuario_id])
            if not r.rows:
                raise HttpError(409, "2fa_sin_iniciar", "Primero genera el código QR")
            f = r.rows[0]
            if f["activo"]:
                raise HttpError(409, "2fa_ya_activo", "El segundo factor ya está activo en esta cuenta")
            paso = verificar_totp(cifrado.descifrar(f["secreto_cifrado"], usuario_id), codigo)
            if paso is None:
                raise HttpError(400, "codigo_2fa", "El código no coincide. Revisa que la hora del teléfono sea automática")
            await c.query(
                "UPDATE usuarios_2fa SET activo = true, activado_en = now(), ultimo_paso = $2 WHERE usuario_id = $1",
                [usuario_id, paso],
            )
            return await self._reemplazar_codigos(c, usuario_id)

    async def _reemplazar_codigos(self, c: Consultable, usuario_id: str) -> list[str]:
        codigos = nuevos_codigos_respaldo()
        await c.query("DELETE FROM codigos_respaldo_2fa WHERE usuario_id = $1", [usuario_id])
        await c.query(
            "INSERT INTO codigos_respaldo_2fa (usuario_id, codigo_hash) SELECT $1, unnest($2::text[])",
            [usuario_id, [hash_codigo_respaldo(usuario_id, k) for k in codigos]],
        )
        return codigos

    async def verificar(self, c: Consultable, usuario_id: str, codigo: str) -> str | None:
        """
        Revisa un código de la app (6 dígitos) o un código de respaldo. Un código TOTP de un paso
        ya aceptado se rechaza y un código de respaldo se marca como usado. Debe correr dentro
        de una transacción. Devuelve 'totp', 'respaldo' o None.
        """
        cifrado = self._exigir_cifrado()
        r = await c.query(
            "SELECT secreto_cifrado, ultimo_paso FROM usuarios_2fa WHERE usuario_id = $1 AND activo FOR UPDATE", [usuario_id]
        )
        if not r.rows:
            return None
        f = r.rows[0]
        limpio = re.sub(r"\s", "", codigo.strip())
        if re.fullmatch(r"\d{6}", limpio):
            paso = verificar_totp(cifrado.descifrar(f["secreto_cifrado"], usuario_id), limpio)
            if paso is None or paso <= int(f["ultimo_paso"]):
                return None
            await c.query("UPDATE usuarios_2fa SET ultimo_paso = $2 WHERE usuario_id = $1", [usuario_id, paso])
            return "totp"
        if len(normalizar_codigo_respaldo(limpio)) != 8:
            return None
        u = await c.query(
            """UPDATE codigos_respaldo_2fa SET usado_en = now()
               WHERE usuario_id = $1 AND codigo_hash = $2 AND usado_en IS NULL""",
            [usuario_id, hash_codigo_respaldo(usuario_id, limpio)],
        )
        return "respaldo" if u.rowcount == 1 else None

    async def regenerar_codigos(self, usuario_id: str, codigo: str) -> list[str]:
        async with self.db.transaccion() as c:
            if not await self.verificar(c, usuario_id, codigo):
                raise HttpError(400, "codigo_2fa", "El código no es válido")
            return await self._reemplazar_codigos(c, usuario_id)

    async def reiniciar(self, db: Consultable, usuario_id: str) -> None:
        """Borra el segundo factor de una cuenta. Solo lo usa el script de soporte."""
        await db.query("DELETE FROM usuarios_2fa WHERE usuario_id = $1", [usuario_id])
        await db.query("DELETE FROM codigos_respaldo_2fa WHERE usuario_id = $1", [usuario_id])
        await db.query("UPDATE desafios_2fa SET usado_en = now() WHERE usuario_id = $1 AND usado_en IS NULL", [usuario_id])

    async def crear_desafio(self, usuario_id: str, agente: str | None) -> dict:
        desafio = nuevo_token("2f")
        r = await self.db.query(
            """INSERT INTO desafios_2fa (usuario_id, desafio_hash, expira_en, agente)
               VALUES ($1, $2, now() + make_interval(mins => $3), $4) RETURNING expira_en""",
            [usuario_id, hash_token(desafio), DESAFIO_MINUTOS, agente[:200] if agente else None],
        )
        return {"desafio": desafio, "expiraEn": iso(r.rows[0]["expira_en"])}

    async def tomar_desafio(self, c: Consultable, desafio: str) -> dict | None:
        """
        Toma el desafío para revisarlo, bloqueado hasta terminar la transacción. Devuelve None si
        no existe, ya se usó, expiró o se agotaron los intentos.
        """
        if not formato_valido(desafio, "2f"):
            return None
        r = await c.query(
            """SELECT d.id, d.usuario_id, d.intentos FROM desafios_2fa d
               JOIN usuarios u ON u.id = d.usuario_id AND u.estado = 'activo' AND u.rol = 'admin'
               WHERE d.desafio_hash = $1 AND d.usado_en IS NULL AND d.expira_en > now() AND d.intentos < $2
               FOR UPDATE OF d""",
            [hash_token(desafio), DESAFIO_INTENTOS],
        )
        return r.rows[0] if r.rows else None
