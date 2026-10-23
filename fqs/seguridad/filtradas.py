"""
Revisa si una contraseña aparece en filtraciones conocidas con Pwned Passwords de Have I Been
Pwned, como pide NIST SP 800-63B (comparar contra listas de contraseñas comprometidas).

Usa el modelo de k-anonimato. Solo viajan los primeros 5 caracteres del SHA-1 de la
contraseña, el servicio responde todos los sufijos que empiezan así con su conteo y la
comparación se hace aquí. Con Add-Padding la respuesta trae además filas de relleno con
conteo 0, así ni el tamaño de la respuesta revela algo.

Si el servicio no responde en 3 segundos se deja pasar la contraseña (las demás reglas ya se
aplicaron) y queda un aviso en el log. Una caída de un tercero no debe impedir que alguien
se registre.
"""

import hashlib
import unicodedata

from ..errores import HttpError
from ..http_cliente import Http, http_real
from ..log import log

URL = "https://api.pwnedpasswords.com/range/"


class RevisorFiltradas:
    def __init__(self, activo: bool, http: Http = http_real) -> None:
        self.activo = activo
        self.http = http

    async def veces(self, clave: str) -> int | None:
        """Veces que aparece, 0 si no aparece, None si no se pudo consultar."""
        if not self.activo:
            return 0
        sha1 = hashlib.sha1(unicodedata.normalize("NFKC", clave).encode("utf-8")).hexdigest().upper()
        prefijo, sufijo = sha1[:5], sha1[5:]
        try:
            r = await self.http("GET", URL + prefijo, {"Add-Padding": "true", "User-Agent": "FamiliasQueSuman-API"}, None, 3.0)
            if not 200 <= r.status < 300:
                raise RuntimeError(f"respondió {r.status}")
            for linea in r.texto.split("\n"):
                s, _, n = linea.strip().partition(":")
                if s == sufijo:
                    try:
                        return int(n)
                    except ValueError:
                        return 0
            return 0
        except Exception as e:  # noqa: BLE001
            log.warn("No se pudo consultar Pwned Passwords, la contraseña se aceptó sin esa revisión", {"error": str(e)})
            return None

    async def exigir_no_filtrada(self, clave: str) -> None:
        """Lanza 422 si la contraseña aparece en alguna filtración."""
        n = await self.veces(clave)
        if n is not None and n > 0:
            raise HttpError(
                422,
                "contrasena_filtrada",
                "Esa contraseña aparece en filtraciones de datos de otros sitios, así que es fácil de adivinar. Elige otra.",
            )
