"""
SMS para verificar teléfonos y recuperar contraseñas.

Cada SMS cuesta dinero y un atacante puede usar un formulario de registro para mandar miles a
números caros (fraude de bombeo de SMS). Por eso
  solo se mandan a números de México,
  máximo SMS_MAX_NUMERO_DIA por número al día,
  máximo SMS_MAX_DIA en total al día (al llegar al tope se avisa en el log y se detiene),
  y del número solo se guarda su SHA-256.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from .config import Config
from .db import Db
from .errores import HttpError
from .http_cliente import Http, http_real
from .log import log
from .tareas import en_segundo_plano
from .validacion import es_telefono_mexicano


class Sms(Protocol):
    async def enviar(self, destino: str, texto: str) -> None: ...


@dataclass
class SmsEnviado:
    destino: str
    texto: str


@dataclass
class SmsBitacora:
    """Sin proveedor. En desarrollo escribe el mensaje en la consola para probar el flujo."""

    mostrar: bool
    enviados: list[SmsEnviado] = field(default_factory=list)

    async def enviar(self, destino: str, texto: str) -> None:
        self.enviados.append(SmsEnviado(destino, texto))
        if self.mostrar:
            log.info("SMS (solo desarrollo, no se envió)", {"destino": destino, "texto": texto})
        else:
            log.warn("No hay proveedor de SMS configurado, el SMS no se envió")


URL_SMS = "https://api.brevo.com/v3/transactionalSMS/send"


class SmsBrevo:
    """
    SMS transaccional de Brevo (POST https://api.brevo.com/v3/transactionalSMS/send con la
    misma llave api-key del correo, responde 201 con messageId). El remitente es de máximo 11
    letras o números y el número va con lada de país y sin el signo +.
    """

    def __init__(self, api_key: str, remitente: str, http: Http = http_real) -> None:
        self.api_key = api_key
        self.remitente = remitente
        self.http = http

    async def enviar(self, destino: str, texto: str) -> None:
        cuerpo = {
            "sender": self.remitente,
            "recipient": destino.lstrip("+"),
            "content": texto,
            "type": "transactional",
            "tag": "codigo",
        }
        r = await self.http(
            "POST",
            URL_SMS,
            {"api-key": self.api_key, "content-type": "application/json", "accept": "application/json"},
            json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            10.0,
        )
        if r.status != 201:
            raise RuntimeError(f"Brevo SMS respondió {r.status} {r.texto[:300]}")


class ControlSms:
    def __init__(self, db: Db, sms: Sms, config: Config, disponible: bool) -> None:
        self.db = db
        self.sms = sms
        self.config = config
        self.disponible = disponible

    @staticmethod
    def _hash(destino: str) -> str:
        return hashlib.sha256(f"sms|{destino}".encode()).hexdigest()

    def exigir_disponible(self, destino: str) -> None:
        """Lanza 503 si no hay proveedor configurado y 422 si el número no es de México."""
        if not self.disponible:
            raise HttpError(503, "sms_no_disponible", "Por ahora no podemos mandar SMS. Regístrate con un correo.")
        if not es_telefono_mexicano(destino):
            raise HttpError(422, "telefono_no_soportado", "Por ahora solo aceptamos teléfonos de México (10 dígitos).")

    async def enviar_codigo(self, destino: str, codigo: str, motivo: str) -> bool:
        """
        Manda el código si no se pasó ningún límite. Devuelve False si se omitió por límite, así
        quien llama responde igual y no revela nada.
        """
        if not es_telefono_mexicano(destino):
            return False
        h = self._hash(destino)
        r = await self.db.query(
            """SELECT count(*) FILTER (WHERE destino_hash = $1) AS numero, count(*) AS total
               FROM sms_enviados WHERE creado_en > now() - interval '1 day'""",
            [h],
        )
        f = r.rows[0]
        if int(f["numero"]) >= self.config.SMS_MAX_NUMERO_DIA:
            log.warn("Límite diario de SMS por número alcanzado", {"motivo": motivo})
            return False
        if int(f["total"]) >= self.config.SMS_MAX_DIA:
            log.error("Se alcanzó el tope diario de SMS, no se mandan más hasta mañana", {"tope": self.config.SMS_MAX_DIA})
            return False
        await self.db.query("INSERT INTO sms_enviados (destino_hash, motivo) VALUES ($1, $2)", [h, motivo])
        texto = (
            f"Familias que Suman. Tu código de verificación es {codigo}. Vence en 30 minutos. No lo compartas con nadie."
            if motivo == "verificacion"
            else f"Familias que Suman. Tu código para cambiar la contraseña es {codigo}. Vence en 30 minutos. Si no lo pediste, ignóralo."
        )

        # El envío no se espera, así la respuesta tarda lo mismo haya o no SMS
        en_segundo_plano(self.sms.enviar(destino, texto), f"el envío del SMS de {motivo}")
        return True

    async def purgar(self) -> None:
        await self.db.query("DELETE FROM sms_enviados WHERE creado_en < now() - interval '2 days'")
