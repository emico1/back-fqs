"""
Hash de contraseñas con scrypt (incluido en la biblioteca estándar, sin dependencias nativas).

Parámetros mínimos recomendados por OWASP para scrypt, N=2^17, r=8, p=1. El formato guarda
los parámetros para poder subirlos en el futuro sin romper contraseñas existentes (se
re-hashean al iniciar sesión).

    scrypt$N$r$p$sal_base64$hash_base64
"""

import asyncio
import base64
import hashlib
import hmac
import secrets
import unicodedata

N = 2**17
R = 8
P = 1
LONGITUD = 64
MAXMEM = 256 * 1024 * 1024


def _scrypt(clave: str, sal: bytes, n: int, r: int, p: int, largo: int) -> bytes:
    normalizada = unicodedata.normalize("NFKC", clave).encode("utf-8")
    return hashlib.scrypt(normalizada, salt=sal, n=n, r=r, p=p, maxmem=MAXMEM, dklen=largo)


def _hash_sync(clave: str) -> str:
    sal = secrets.token_bytes(16)
    k = _scrypt(clave, sal, N, R, P, LONGITUD)
    return "$".join(["scrypt", str(N), str(R), str(P), base64.b64encode(sal).decode(), base64.b64encode(k).decode()])


def _verificar_sync(clave: str, guardado: str) -> bool:
    partes = guardado.split("$")
    if len(partes) != 6 or partes[0] != "scrypt":
        return False
    try:
        n, r, p = int(partes[1]), int(partes[2]), int(partes[3])
        sal = base64.b64decode(partes[4])
        esperado = base64.b64decode(partes[5])
    except ValueError:
        return False
    k = _scrypt(clave, sal, n, r, p, len(esperado))
    return hmac.compare_digest(k, esperado)


async def hash_contrasena(clave: str) -> str:
    # scrypt tarda a propósito, se corre fuera del ciclo de eventos para no detener las demás peticiones
    return await asyncio.to_thread(_hash_sync, clave)


async def verificar_contrasena(clave: str, guardado: str) -> bool:
    return await asyncio.to_thread(_verificar_sync, clave, guardado)


def necesita_rehash(guardado: str) -> bool:
    partes = guardado.split("$")
    if len(partes) < 4 or partes[0] != "scrypt":
        return True
    try:
        return int(partes[1]) < N or int(partes[2]) < R or int(partes[3]) < P
    except ValueError:
        return True


# Hash válido de una contraseña aleatoria. Se usa cuando la cuenta no existe para que la
# respuesta tarde lo mismo y no revele qué cuentas existen.
_senuelo: str | None = None
_candado = asyncio.Lock()


async def senuelo() -> str:
    global _senuelo
    if _senuelo is None:
        async with _candado:
            if _senuelo is None:
                _senuelo = await hash_contrasena(secrets.token_hex(32))
    return _senuelo


_COMUNES = {
    "1234567890", "12345678910", "qwertyuiop", "contrasena", "contraseña", "password123",
    "password1234", "familiasquesuman", "monterrey123", "0987654321", "iloveyou12", "abcdefghij",
}


def problema_contrasena(clave: str, datos_personales: list[str] | None = None) -> str | None:
    """Devuelve un mensaje si la contraseña no es aceptable, o None si está bien."""
    if len(clave) < 10:
        return "La contraseña debe tener al menos 10 caracteres"
    if len(clave) > 128:
        return "La contraseña es demasiado larga"
    if len(set(clave)) < 4:
        return "La contraseña es demasiado repetitiva"
    minus = clave.lower()
    if minus in _COMUNES:
        return "Esa contraseña es demasiado común"
    for d in datos_personales or []:
        limpio = d.lower().split("@")[0]
        if len(limpio) >= 4 and limpio in minus:
            return "La contraseña no debe contener tu nombre, usuario o correo"
    return None
