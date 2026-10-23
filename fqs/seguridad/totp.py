"""
Códigos de un solo uso basados en tiempo (TOTP, RFC 6238) con los parámetros que entienden
todas las apps de autenticación (Google Authenticator, Microsoft Authenticator, Authy,
1Password) HMAC-SHA1, pasos de 30 segundos y 6 dígitos. Se acepta el paso anterior y el
siguiente para tolerar relojes un poco desfasados.
"""

import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PERIODO = 30
DIGITOS = 6
VENTANA = 1

_ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def base32(datos: bytes) -> str:
    bits = 0
    valor = 0
    salida = []
    for byte in datos:
        valor = ((valor << 8) | byte) & 0xFFFFFFFF
        bits += 8
        while bits >= 5:
            salida.append(_ALFABETO[(valor >> (bits - 5)) & 31])
            bits -= 5
    if bits > 0:
        salida.append(_ALFABETO[(valor << (5 - bits)) & 31])
    return "".join(salida)


def desde_base32(texto: str) -> bytes:
    limpio = texto.upper().replace(" ", "").replace("=", "").replace("-", "")
    bits = 0
    valor = 0
    salida = bytearray()
    for c in limpio:
        i = _ALFABETO.find(c)
        if i < 0:
            raise ValueError("Base32 inválido")
        valor = ((valor << 5) | i) & 0xFFFFFFFF
        bits += 5
        if bits >= 8:
            salida.append((valor >> (bits - 8)) & 255)
            bits -= 8
    return bytes(salida)


def nuevo_secreto() -> bytes:
    """160 bits, el tamaño que recomienda el RFC 4226 para HMAC-SHA1."""
    return secrets.token_bytes(20)


def hotp(secreto: bytes, contador: int) -> str:
    """HOTP del RFC 4226, con el truncado dinámico."""
    h = hmac.new(secreto, struct.pack(">Q", contador), hashlib.sha1).digest()
    d = h[-1] & 0x0F
    binario = ((h[d] & 0x7F) << 24) | (h[d + 1] << 16) | (h[d + 2] << 8) | h[d + 3]
    return str(binario % 10**DIGITOS).zfill(DIGITOS)


def paso_actual(ahora_ms: float | None = None) -> int:
    ms = time.time() * 1000 if ahora_ms is None else ahora_ms
    return int(ms // 1000 // PERIODO)


def totp(secreto: bytes, ahora_ms: float | None = None) -> str:
    return hotp(secreto, paso_actual(ahora_ms))


def verificar_totp(secreto: bytes, codigo: str, ahora_ms: float | None = None) -> int | None:
    """
    Devuelve el paso que coincidió o None. Quien llama debe rechazar un paso menor o igual
    al último aceptado, así un código que alguien vio por encima del hombro no sirve dos veces.
    """
    if not (len(codigo) == DIGITOS and codigo.isdigit()):
        return None
    actual = paso_actual(ahora_ms)
    hallado = None
    # Se revisan todos los pasos de la ventana sin salir antes, el tiempo no revela cuál coincidió
    for d in range(-VENTANA, VENTANA + 1):
        if hmac.compare_digest(hotp(secreto, actual + d), codigo) and hallado is None:
            hallado = actual + d
    return hallado


def uri_otpauth(secreto: bytes, cuenta: str, emisor: str = "Familias que Suman") -> str:
    """Enlace otpauth que se convierte en QR para la app de autenticación."""
    etiqueta = quote(f"{emisor}:{cuenta}", safe="")
    p = urlencode(
        {"secret": base32(secreto), "issuer": emisor, "algorithm": "SHA1", "digits": str(DIGITOS), "period": str(PERIODO)}
    )
    return f"otpauth://totp/{etiqueta}?{p}"


# Cifrado del secreto con AES-256-GCM. Se usa el id de la cuenta como dato asociado, así
# copiar el secreto cifrado de una cuenta a otra en la base no funciona.
#
# Formato  "F1" (2 bytes) + id de la clave (4 bytes) + iv (12) + etiqueta (16) + cifrado
# El id de la clave son los primeros 4 bytes de su SHA-256, así se sabe con cuál se cifró
# sin guardar la clave. También se lee el formato de la primera versión
# (iv + etiqueta + cifrado, sin cabecera).
_MAGIA = b"F1"


class _Clave:
    def __init__(self, base64_: str) -> None:
        import base64

        self.valor = base64.b64decode(base64_)
        if len(self.valor) != 32:
            raise ValueError("La clave de cifrado debe ser de 32 bytes en base64")
        self.id = hashlib.sha256(self.valor).digest()[:4]


class CifradoSecretos:
    def __init__(self, clave_base64: str, anteriores: list[str] | None = None) -> None:
        self.actual = _Clave(clave_base64)
        self.todas = [self.actual, *[_Clave(k) for k in anteriores or []]]

    def cifrar(self, datos: bytes, asociado: str) -> bytes:
        iv = os.urandom(12)
        # AESGCM devuelve cifrado + etiqueta, aquí se guarda etiqueta + cifrado como antes
        salida = AESGCM(self.actual.valor).encrypt(iv, datos, asociado.encode())
        cifrado, etiqueta = salida[:-16], salida[-16:]
        return _MAGIA + self.actual.id + iv + etiqueta + cifrado

    @staticmethod
    def _abrir(clave: bytes, cuerpo: bytes, asociado: str) -> bytes:
        iv, etiqueta, cifrado = cuerpo[:12], cuerpo[12:28], cuerpo[28:]
        return AESGCM(clave).decrypt(iv, cifrado + etiqueta, asociado.encode())

    def descifrar(self, blob: bytes, asociado: str) -> bytes:
        blob = bytes(blob)
        if blob[:2] == _MAGIA:
            ident = blob[2:6]
            for k in self.todas:
                if k.id == ident:
                    return self._abrir(k.valor, blob[6:], asociado)
        # Formato anterior sin cabecera, se prueba con cada clave conocida
        for k in self.todas:
            try:
                return self._abrir(k.valor, blob, asociado)
            except Exception:
                continue
        raise ValueError("No se pudo descifrar el secreto con ninguna de las claves configuradas")

    def necesita_recifrar(self, blob: bytes) -> bool:
        blob = bytes(blob)
        return not (blob[:2] == _MAGIA and blob[2:6] == self.actual.id)


# Diez códigos de respaldo del tipo k7m2-q9xa, sin letras que se confundan
_ALFABETO_RESPALDO = "abcdefghjkmnpqrstuvwxyz23456789"


def nuevos_codigos_respaldo(cantidad: int = 10) -> list[str]:
    codigos = []
    for _ in range(cantidad):
        s = "".join(_ALFABETO_RESPALDO[x % len(_ALFABETO_RESPALDO)] for x in secrets.token_bytes(8))
        codigos.append(f"{s[:4]}-{s[4:]}")
    return codigos


def normalizar_codigo_respaldo(c: str) -> str:
    return c.strip().lower().replace(" ", "").replace("-", "")


def hash_codigo_respaldo(usuario_id: str, codigo: str) -> str:
    return hashlib.sha256(f"{usuario_id}|respaldo|{normalizar_codigo_respaldo(codigo)}".encode()).hexdigest()
