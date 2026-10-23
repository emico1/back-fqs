"""
Reintentos seguros de escrituras con el encabezado Idempotency-Key.

La app guarda sin conexión las propuestas, los reportes y los testimonios, y los manda cuando
vuelve la red. Cada uno lleva una clave aleatoria que se genera una sola vez. Si la respuesta
se pierde en el camino y la app reintenta con la misma clave, la API devuelve la respuesta que
ya había dado (con el encabezado Idempotent-Replayed) en lugar de crear un duplicado.

  Sin el encabezado la ruta funciona igual que siempre.
  La clave es de la cuenta, otra cuenta puede usar la misma sin ver nada ajeno.
  La misma clave con otra ruta u otro cuerpo responde 422.
  Si la primera petición sigue en proceso responde 409.
  Solo se guardan respuestas correctas. Si la ruta falla, la clave se libera y el
  reintento vuelve a validar todo.
  Las claves se borran a las 48 horas (tarea de limpieza).
"""

import hashlib
import json
import re
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import Response

from .errores import HttpError
from .jsonfmt import RespuestaJson
from .validacion import Modelo

ENCABEZADO = "idempotency-key"
CLAVE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
VIGENCIA = "48 hours"


def _huella(ruta: str, cuerpo: Modelo) -> str:
    texto = json.dumps(cuerpo.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{ruta}\n{texto}".encode("utf-8")).hexdigest()


async def con_idempotencia(
    request: Request,
    db,  # noqa: ANN001
    usuario_id: str,
    cuerpo: Modelo,
    hacer: Callable[[], Awaitable[RespuestaJson]],
) -> Response:
    clave = request.headers.get(ENCABEZADO)
    if clave is None:
        return await hacer()
    if not CLAVE_RE.match(clave):
        raise HttpError(400, "idempotencia_invalida", "Idempotency-Key debe tener de 16 a 64 letras, números, guiones o guiones bajos")

    ruta = request.url.path[:200]
    huella = _huella(ruta, cuerpo)

    # Una clave vencida se puede volver a usar
    await db.query(
        f"DELETE FROM idempotencia WHERE usuario_id = $1 AND clave = $2 AND creado_en <= now() - interval '{VIGENCIA}'",
        [usuario_id, clave],
    )
    reservada = await db.query(
        """INSERT INTO idempotencia (usuario_id, clave, ruta, huella) VALUES ($1, $2, $3, $4)
           ON CONFLICT (usuario_id, clave) DO NOTHING RETURNING clave""",
        [usuario_id, clave, ruta, huella],
    )
    if not reservada.rows:
        previa = await db.query(
            "SELECT ruta, huella, status, respuesta FROM idempotencia WHERE usuario_id = $1 AND clave = $2",
            [usuario_id, clave],
        )
        if not previa.rows:
            # Se liberó justo ahora porque la primera petición falló, se puede reintentar
            raise HttpError(409, "idempotencia_en_proceso", "La misma solicitud se está procesando, intenta en unos segundos")
        p = previa.rows[0]
        if p["ruta"] != ruta or p["huella"] != huella:
            raise HttpError(422, "idempotencia_conflicto", "Esa clave ya se usó con otra solicitud")
        if p["status"] is None:
            raise HttpError(409, "idempotencia_en_proceso", "La misma solicitud se está procesando, intenta en unos segundos")
        r = RespuestaJson(p["respuesta"], status_code=p["status"])
        r.headers["Idempotent-Replayed"] = "true"
        return r

    try:
        respuesta = await hacer()
    except BaseException:
        await db.query("DELETE FROM idempotencia WHERE usuario_id = $1 AND clave = $2", [usuario_id, clave])
        raise
    if 200 <= respuesta.status_code < 300:
        await db.query(
            "UPDATE idempotencia SET status = $3, respuesta = $4::jsonb WHERE usuario_id = $1 AND clave = $2",
            [usuario_id, clave, respuesta.status_code, bytes(respuesta.body).decode("utf-8")],
        )
    else:
        await db.query("DELETE FROM idempotencia WHERE usuario_id = $1 AND clave = $2", [usuario_id, clave])
    return respuesta


async def purgar(db) -> None:  # noqa: ANN001
    await db.query(f"DELETE FROM idempotencia WHERE creado_en <= now() - interval '{VIGENCIA}'")
