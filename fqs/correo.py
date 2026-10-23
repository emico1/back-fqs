"""
Correos transaccionales. Todos llevan solo lo indispensable, nunca contraseñas ni enlaces que
inicien sesión por sí solos.
"""

import html
import json
from dataclasses import dataclass, field
from typing import Protocol

from .http_cliente import Http, http_real
from .log import log


class Correo(Protocol):
    async def enviar_recuperacion(self, destino: str, codigo: str) -> None: ...
    async def enviar_verificacion(self, destino: str, codigo: str) -> None: ...
    async def enviar_correo_ya_registrado(self, destino: str) -> None: ...
    async def enviar_aviso(self, destino: str, asunto: str, parrafos: list[str]) -> None: ...


@dataclass
class Enviado:
    tipo: str
    destino: str
    token: str
    asunto: str | None = None
    texto: str | None = None


@dataclass
class CorreoBitacora:
    """
    Sin proveedor configurado. En desarrollo escribe los códigos en la consola para poder
    probar los flujos, en cualquier otro entorno solo avisa que no se mandó.
    """

    mostrar_token: bool
    enviados: list[Enviado] = field(default_factory=list)

    def _registrar(self, tipo: str, destino: str, token: str, asunto: str | None = None, texto: str | None = None) -> None:
        self.enviados.append(Enviado(tipo, destino, token, asunto, texto))
        if self.mostrar_token:
            log.info("Correo (solo desarrollo, no se envió)", {"tipo": tipo, "destino": destino, "codigo": token or None, "asunto": asunto})
        else:
            log.warn("No hay proveedor de correo configurado, el correo no se envió", {"tipo": tipo})

    async def enviar_recuperacion(self, destino: str, codigo: str) -> None:
        self._registrar("recuperacion", destino, codigo)

    async def enviar_verificacion(self, destino: str, codigo: str) -> None:
        self._registrar("verificacion", destino, codigo)

    async def enviar_correo_ya_registrado(self, destino: str) -> None:
        self._registrar("ya_registrado", destino, "")

    async def enviar_aviso(self, destino: str, asunto: str, parrafos: list[str]) -> None:
        self._registrar("aviso", destino, "", asunto, "\n".join(parrafos))


_NO_FUISTE = "Si no fuiste tú, ignora este correo. Nunca te pediremos este código por teléfono ni por mensaje."


def _escapar(t: str) -> str:
    return html.escape(t, quote=True).replace("&#x27;", "&#39;")


def plantilla(titulo: str, parrafos: list[str], codigo: str | None = None) -> str:
    cuerpo = "\n".join(f"<p>{_escapar(p)}</p>" for p in parrafos)
    bloque = (
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:4px">{_escapar(f"{codigo[:4]} {codigo[4:]}")}</p>'
        if codigo
        else ""
    )
    return (
        '<!doctype html><html lang="es"><body style="font-family:Arial,sans-serif;color:#1b1b1f;max-width:520px;margin:auto">\n'
        '<h2 style="color:#1556d6">Familias que Suman</h2>\n'
        f"<h3>{_escapar(titulo)}</h3>\n{cuerpo}\n{bloque}\n</body></html>"
    )


URL_BREVO = "https://api.brevo.com/v3/smtp/email"


class CorreoBrevo:
    """
    Correo por la API transaccional de Brevo (POST https://api.brevo.com/v3/smtp/email,
    autenticación con el encabezado api-key, responde 201 con messageId). La llave nunca se
    escribe en la bitácora. Si Brevo falla se lanza un error y quien llama decide qué hacer.
    """

    def __init__(self, api_key: str, remitente: str, remitente_nombre: str, http: Http = http_real) -> None:
        self.api_key = api_key
        self.remitente = remitente
        self.remitente_nombre = remitente_nombre
        self.http = http

    async def _enviar(self, destino: str, asunto: str, contenido: str, etiqueta: str) -> None:
        cuerpo = {
            "sender": {"name": self.remitente_nombre, "email": self.remitente},
            "to": [{"email": destino}],
            "subject": asunto,
            "htmlContent": contenido,
            "tags": [etiqueta],
        }
        r = await self.http(
            "POST",
            URL_BREVO,
            {"api-key": self.api_key, "content-type": "application/json", "accept": "application/json"},
            json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            10.0,
        )
        if r.status != 201:
            # El cuerpo de error de Brevo no trae datos sensibles, ayuda a diagnosticar
            raise RuntimeError(f"Brevo respondió {r.status} {r.texto[:300]}")

    async def enviar_recuperacion(self, destino: str, codigo: str) -> None:
        await self._enviar(
            destino,
            "Tu código para cambiar la contraseña",
            plantilla(
                "Cambio de contraseña",
                [
                    "Recibimos una solicitud para cambiar la contraseña de tu cuenta. Tu código es el siguiente. Vence en 30 minutos y sirve una sola vez.",
                    _NO_FUISTE + " Tu contraseña no cambia mientras nadie use el código.",
                ],
                codigo,
            ),
            "recuperacion",
        )

    async def enviar_verificacion(self, destino: str, codigo: str) -> None:
        await self._enviar(
            destino,
            "Confirma tu correo",
            plantilla(
                "Confirma tu correo",
                [
                    "Escribe este código en la app para confirmar que este correo es tuyo. Vence en 30 minutos.",
                    _NO_FUISTE + " Sin el código nadie puede usar tu correo en Familias que Suman.",
                ],
                codigo,
            ),
            "verificacion",
        )

    async def enviar_correo_ya_registrado(self, destino: str) -> None:
        await self._enviar(
            destino,
            "Ya tienes una cuenta",
            plantilla(
                "Ya tienes una cuenta",
                [
                    "Alguien intentó crear una cuenta o cambiar su correo usando esta dirección, pero ya hay una cuenta con ella.",
                    "Si fuiste tú, inicia sesión en la app. Si olvidaste la contraseña, usa la opción para recuperarla.",
                    "Si no fuiste tú, no tienes que hacer nada. Tu cuenta no cambió.",
                ],
            ),
            "ya_registrado",
        )

    async def enviar_aviso(self, destino: str, asunto: str, parrafos: list[str]) -> None:
        await self._enviar(destino, asunto, plantilla(asunto, parrafos), "aviso")
