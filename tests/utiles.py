"""Utilidades compartidas por las pruebas."""

import struct
from datetime import datetime, timedelta, timezone

from fqs.jsonfmt import iso


def en(**delta: float) -> str:
    """Instante ISO relativo a ahora, por ejemplo en(days=3) o en(hours=-1)."""
    return iso(datetime.now(timezone.utc) + timedelta(**delta)) or ""


def mas(instante: str, **delta: float) -> str:
    d = datetime.fromisoformat(instante.replace("Z", "+00:00"))
    return iso(d + timedelta(**delta)) or ""


def png_con_texto() -> bytes:
    """PNG mínimo válido de 1x1 con un fragmento tEXt que debe eliminarse."""
    firma = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])

    def trozo(tipo: str, datos: bytes) -> bytes:
        return struct.pack(">I", len(datos)) + tipo.encode("latin1") + datos + bytes(4)

    ihdr = bytes([0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0])
    return (
        firma
        + trozo("IHDR", ihdr)
        + trozo("tEXt", "GPS\0Monterrey 25.68,-100.31".encode("latin1"))
        + trozo("IDAT", bytes([0x78, 0x9C, 0x63, 0x60, 0, 0, 0, 2, 0, 1]))
        + trozo("IEND", b"")
    )


def jpeg_con_exif() -> bytes:
    """JPEG mínimo con un segmento EXIF (APP1) que debe eliminarse."""
    app1_datos = "Exif\0\0GPSLatitude=25.68".encode("latin1")
    app1 = bytes([0xFF, 0xE1]) + bytes([0, len(app1_datos) + 2]) + app1_datos
    app0_datos = "JFIF\0\x01\x01\0\0\x01\0\x01\0\0".encode("latin1")
    app0 = bytes([0xFF, 0xE0]) + bytes([0, len(app0_datos) + 2]) + app0_datos
    sos = bytes([0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0x12, 0x34, 0xFF, 0xD9])
    return bytes([0xFF, 0xD8]) + app0 + app1 + sos
