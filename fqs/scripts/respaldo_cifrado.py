"""
Formato de los archivos de respaldo (.fqsr)
  FQSR1 y salto de línea (6 bytes) + iv (12 bytes) + datos cifrados + etiqueta GCM (16 bytes)
Cifrado AES-256-GCM. El tipo de contenido (db, archivos o bitacora) va como dato asociado, así
no se puede hacer pasar un respaldo de fotos por uno de base de datos.
"""

import base64
import binascii
import hashlib
import os
import secrets
from pathlib import Path
from typing import BinaryIO, Iterable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIA = b"FQSR1\n"
IV = 12
ETIQUETA = 16
TROZO = 1024 * 1024


def clave_respaldo(b64: str | None) -> bytes:
    if not b64:
        raise RuntimeError("Falta RESPALDO_CLAVE (32 bytes en base64). Genera una con  python -m fqs.scripts.generar_clave")
    try:
        k = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        k = b""
    if len(k) != 32:
        raise RuntimeError("RESPALDO_CLAVE debe ser de 32 bytes en base64")
    return k


def _abrir_exclusivo(ruta: Path) -> BinaryIO:
    """Crea el archivo con permisos 600 y falla si ya existe."""
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    return os.fdopen(fd, "wb")


def cifrar_flujo(origen: Iterable[bytes], destino: Path, clave: bytes, tipo: str) -> dict:
    """Cifra un flujo hacia un archivo. Devuelve el tamaño y el SHA-256 del archivo cifrado."""
    iv = secrets.token_bytes(IV)
    c = Cipher(algorithms.AES(clave), modes.GCM(iv)).encryptor()
    c.authenticate_additional_data(f"fqs-respaldo|{tipo}".encode())
    sha = hashlib.sha256()
    total = 0
    with _abrir_exclusivo(destino) as f:

        def escribir(b: bytes) -> None:
            nonlocal total
            if b:
                f.write(b)
                sha.update(b)
                total += len(b)

        escribir(MAGIA + iv)
        for trozo in origen:
            escribir(c.update(trozo))
        escribir(c.finalize())
        escribir(c.tag)
    return {"bytes": total, "sha256": sha.hexdigest()}


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while b := f.read(TROZO):
            h.update(b)
    return h.hexdigest()


def descifrar_archivo(origen: Path, destino: Path, clave: bytes, tipo: str) -> None:
    """
    Descifra un archivo hacia otro. Si la etiqueta no coincide (archivo alterado, clave
    equivocada o tipo cambiado) lanza un error y borra la salida.
    """
    tamano = origen.stat().st_size
    if tamano < len(MAGIA) + IV + ETIQUETA:
        raise RuntimeError("El archivo de respaldo está incompleto")
    with open(origen, "rb") as f:
        cabecera = f.read(len(MAGIA) + IV)
        if cabecera[: len(MAGIA)] != MAGIA:
            raise RuntimeError("No es un respaldo de Familias que Suman")
        f.seek(tamano - ETIQUETA)
        etiqueta = f.read(ETIQUETA)
        d = Cipher(algorithms.AES(clave), modes.GCM(cabecera[len(MAGIA) :], etiqueta)).decryptor()
        d.authenticate_additional_data(f"fqs-respaldo|{tipo}".encode())
        f.seek(len(MAGIA) + IV)
        restante = tamano - len(MAGIA) - IV - ETIQUETA
        try:
            with open(destino, "wb") as salida:
                os.chmod(destino, 0o600)
                while restante > 0:
                    b = f.read(min(TROZO, restante))
                    restante -= len(b)
                    salida.write(d.update(b))
                salida.write(d.finalize())
        except InvalidTag:
            destino.unlink(missing_ok=True)
            raise RuntimeError(f"No se pudo descifrar {tipo}. La clave es otra o el archivo fue modificado") from None
