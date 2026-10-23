"""
Notificaciones push con Firebase Cloud Messaging (RF16), API HTTP v1.

El backend se autentica con una cuenta de servicio de Firebase. Con su llave privada firma un
JWT (RS256) y lo cambia por un token OAuth de una hora con alcance solo de mensajería. No se
usa el SDK de Firebase para no agregar dependencias.

Cada notificación se marca con push_enviada_en antes de mandarla, en la misma sentencia que
la reclama, así nunca sale dos veces aunque haya varios procesos. Si Firebase responde que un
token ya no existe, se borra de dispositivos.
"""

import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .db import Db
from .http_cliente import Http, http_real
from .log import log

ALCANCE = "https://www.googleapis.com/auth/firebase.messaging"
URI_TOKEN = "https://oauth2.googleapis.com/token"


def cargar_cuenta_servicio(ruta: str | None) -> dict | None:
    """Lee el JSON de la cuenta de servicio. Devuelve None si no se configuró."""
    if not ruta:
        return None
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    # Un archivo con {} sirve para levantar Docker Compose sin Firebase, el push queda apagado
    if datos == {}:
        return None
    if not datos.get("project_id") or not datos.get("client_email") or not datos.get("private_key"):
        raise RuntimeError("El archivo de la cuenta de servicio de Firebase no tiene project_id, client_email o private_key")
    return datos


def _b64url(b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode("utf-8")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Push:
    def __init__(self, db: Db, cuenta: dict | None, http: Http = http_real) -> None:
        self.db = db
        self.cuenta = cuenta
        self.http = http
        self._token: tuple[str, float] | None = None

    @property
    def activo(self) -> bool:
        return self.cuenta is not None

    async def _token_oauth(self) -> str:
        """Token OAuth vigente, se renueva un minuto antes de que venza."""
        ahora = int(time.time())
        if self._token and self._token[1] - 60 > ahora:
            return self._token[0]
        c = self.cuenta or {}
        aud = c.get("token_uri") or URI_TOKEN
        cabecera = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")))
        cuerpo = _b64url(
            json.dumps({"iss": c["client_email"], "scope": ALCANCE, "aud": aud, "iat": ahora, "exp": ahora + 3600}, separators=(",", ":"))
        )
        llave = serialization.load_pem_private_key(c["private_key"].encode(), password=None)
        firma = llave.sign(f"{cabecera}.{cuerpo}".encode(), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[call-arg, union-attr]
        jwt = f"{cabecera}.{cuerpo}.{_b64url(firma)}"
        r = await self.http(
            "POST",
            aud,
            {"content-type": "application/x-www-form-urlencoded"},
            urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode(),
            10.0,
        )
        if not 200 <= r.status < 300:
            raise RuntimeError(f"Google rechazó la cuenta de servicio (HTTP {r.status})")
        d = json.loads(r.texto)
        self._token = (d["access_token"], ahora + int(d["expires_in"]))
        return d["access_token"]

    async def procesar(self, notificacion_id: str) -> None:
        """Reclama y manda una notificación. No lanza, los errores van a la bitácora."""
        try:
            r = await self.db.query(
                """UPDATE notificaciones SET push_enviada_en = now()
                   WHERE id = $1 AND push_enviada_en IS NULL
                   RETURNING id, usuario_id, tipo, titulo, mensaje, actividad_id, asociacion_id, propuesta_id, campana_id""",
                [notificacion_id],
            )
            if not r.rows or not self.cuenta:
                return
            n = r.rows[0]
            dispositivos = await self.db.query(
                """SELECT d.token_fcm FROM dispositivos d JOIN usuarios u ON u.id = d.usuario_id
                   WHERE d.usuario_id = $1 AND u.estado = 'activo'""",
                [n["usuario_id"]],
            )
            for d in dispositivos.rows:
                await self._mandar(n, d["token_fcm"])
        except Exception as e:  # noqa: BLE001
            log.warn("No se pudo enviar una notificación push", {"error": str(e)})

    async def pendientes(self) -> None:
        """Manda lo que quedó pendiente de la última hora (por ejemplo si el backend estuvo apagado)."""
        r = await self.db.query(
            """SELECT id FROM notificaciones WHERE push_enviada_en IS NULL AND creado_en > now() - interval '1 hour'
               ORDER BY creado_en LIMIT 500"""
        )
        for f in r.rows:
            await self.procesar(f["id"])
        # Las más viejas ya no tienen sentido como push, siguen visibles en la app
        await self.db.query(
            "UPDATE notificaciones SET push_enviada_en = now() WHERE push_enviada_en IS NULL AND creado_en <= now() - interval '1 hour'"
        )

    async def _mandar(self, n: dict, token_dispositivo: str) -> None:
        c = self.cuenta or {}
        # Solo identificadores en data, la app vuelve a pedir el detalle con su sesión
        data = {"notificacionId": n["id"], "tipo": n["tipo"]}
        for campo, clave in (("actividad_id", "actividadId"), ("campana_id", "campanaId"), ("propuesta_id", "propuestaId"), ("asociacion_id", "asociacionId")):
            if n[campo]:
                data[clave] = n[campo]
        mensaje = {
            "message": {
                "token": token_dispositivo,
                "notification": {"title": n["titulo"], "body": n["mensaje"]},
                "data": data,
                "android": {
                    "priority": "high" if n["tipo"] in ("recordatorio", "actividad_cancelada") else "normal",
                    "notification": {"channel_id": "fqs_avisos"},
                },
            }
        }
        r = await self.http(
            "POST",
            f"https://fcm.googleapis.com/v1/projects/{quote(c['project_id'], safe='')}/messages:send",
            {"authorization": f"Bearer {await self._token_oauth()}", "content-type": "application/json"},
            json.dumps(mensaje, ensure_ascii=False).encode("utf-8"),
            10.0,
        )
        if 200 <= r.status < 300:
            return
        try:
            cuerpo = json.loads(r.texto)
        except ValueError:
            cuerpo = None
        error = (cuerpo or {}).get("error") or {}
        codigo = next((x.get("errorCode") for x in error.get("details") or [] if x.get("errorCode")), None)
        token_invalido = codigo == "UNREGISTERED" or (
            error.get("status") == "INVALID_ARGUMENT" and re.search(r"registration token", error.get("message") or "", re.IGNORECASE)
        )
        if token_invalido:
            # El teléfono desinstaló la app o el token cambió, se deja de usar
            await self.db.query("DELETE FROM dispositivos WHERE token_fcm = $1", [token_dispositivo])
            return
        log.warn("Firebase rechazó una notificación", {"status": r.status, "codigo": codigo or error.get("status")})
