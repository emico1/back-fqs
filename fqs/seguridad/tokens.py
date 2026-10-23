"""
Tokens opacos de 256 bits. En la base solo se guarda su SHA-256, así que una copia filtrada
de la base no permite suplantar a nadie. Al ser opacos y consultarse en cada petición,
cerrar sesión o suspender una cuenta tiene efecto inmediato (a diferencia de un JWT, que
sigue valiendo hasta que expira).

Prefijos, at acceso, rt renovación, 2f desafío de segundo factor.
"""

import base64
import hashlib
import re
import secrets

_FORMATO = re.compile(r"^fqs_(at|rt|rc|2f)_[A-Za-z0-9_-]{43}$")


def nuevo_token(prefijo: str) -> str:
    cuerpo = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    return f"fqs_{prefijo}_{cuerpo}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def formato_valido(token: str, prefijo: str) -> bool:
    return bool(_FORMATO.match(token)) and token.startswith(f"fqs_{prefijo}_")
