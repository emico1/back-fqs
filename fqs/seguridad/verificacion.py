"""
Códigos para confirmar que un correo o un teléfono pertenece a quien se registra o lo cambia.
Son de 8 dígitos, vencen en 30 minutos, se guardan como SHA-256 junto con el id de la
verificación y permiten 5 intentos en total aunque se reenvíen.
"""

import hashlib
import hmac
import secrets

VERIFICACION_MINUTOS = 30
VERIFICACION_INTENTOS = 5
VERIFICACION_REENVIOS = 3


def nuevo_codigo() -> str:
    return str(secrets.randbelow(100_000_000)).zfill(8)


def hash_verificacion(ident: str, codigo: str) -> str:
    return hashlib.sha256(f"{ident}|verificacion|{codigo}".encode()).hexdigest()


def codigo_coincide(ident: str, codigo: str, guardado: str) -> bool:
    return hmac.compare_digest(hash_verificacion(ident, codigo), guardado)


def enmascarar_telefono(t: str) -> str:
    """Muestra solo los últimos 4 dígitos del teléfono."""
    return f"•••• •• {t[-4:]}"


def enmascarar_correo(correo: str) -> str:
    """Muestra solo el inicio del correo, para confirmar en pantalla a dónde llegó el código."""
    usuario, _, dominio = correo.partition("@")
    visible = usuario[: min(2, len(usuario))]
    return f"{visible}{'•' * max(1, len(usuario) - len(visible))}@{dominio}"
