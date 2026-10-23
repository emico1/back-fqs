"""
Validación y reconstrucción de imágenes subidas.

El tipo se decide por los bytes del archivo (firma mágica) y no por lo que diga el cliente.
Después la imagen se reconstruye conservando solo lo necesario para mostrarla.
  Se eliminan los metadatos que pueden exponer datos personales (EXIF con ubicación GPS,
  XMP, IPTC, comentarios, textos de PNG).
  Se eliminan segmentos desconocidos y cualquier dato pegado después del final de la imagen,
  que es donde se esconden los archivos políglota (una imagen que también es un ZIP, un HTML
  o un script).
  En PNG los datos de la imagen se descomprimen y se vuelven a comprimir en un solo bloque
  nuevo, con un tope de tamaño que detiene las bombas de descompresión.
Las imágenes no se re-codifican píxel por píxel, eso requeriría una dependencia nativa.
"""

import re
import struct
import zlib

from ..errores import HttpError

# Tope de píxeles y de bytes descomprimidos, una foto de 50 megapíxeles RGBA cabe holgada
MAX_PIXELES = 50_000_000
MAX_DESCOMPRIMIDO = MAX_PIXELES * 4 + 50_000

_FIRMA_PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def detectar_tipo(b: bytes) -> str | None:
    if len(b) >= 3 and b[0] == 0xFF and b[1] == 0xD8 and b[2] == 0xFF:
        return "image/jpeg"
    if len(b) >= 8 and b[:8] == _FIRMA_PNG:
        return "image/png"
    return None


def _invalida() -> HttpError:
    return HttpError(422, "imagen_invalida", "La imagen está dañada o no es un JPEG o PNG válido")


def _conservar_jpeg(marcador: int, datos: bytes) -> bool:
    """
    Marcadores JPEG que se conservan. Los SOF (C0 a CF salvo C8), las tablas de Huffman (C4),
    de cuantización (DB), aritméticas (CC), el intervalo de reinicio (DD), el número de líneas
    (DC), APP0 JFIF y APP14 Adobe (necesario para CMYK) y APP2 solo si es un perfil ICC.
    """
    if 0xC0 <= marcador <= 0xCF and marcador != 0xC8:
        return True
    if marcador in (0xDB, 0xDD, 0xDC):
        return True
    if marcador == 0xE0:
        return datos[:5] == b"JFIF\x00"
    if marcador == 0xEE:
        return datos[:5] == b"Adobe"
    if marcador == 0xE2:
        return datos[:12] == b"ICC_PROFILE\x00"
    return False


def _reconstruir_jpeg(b: bytes) -> bytes:
    """Recorre el JPEG y lo vuelve a armar con los segmentos permitidos, hasta EOI."""
    partes = [b"\xff\xd8"]
    i = 2
    vio_imagen = False
    n = len(b)
    while i < n:
        if b[i] != 0xFF:
            raise _invalida()
        if i + 1 >= n:
            raise _invalida()
        marcador = b[i + 1]
        # Bytes de relleno 0xFF permitidos por la norma
        while marcador == 0xFF:
            i += 1
            if i + 1 >= n:
                raise _invalida()
            marcador = b[i + 1]
        if marcador == 0xD9:
            if not vio_imagen:
                raise _invalida()
            partes.append(b"\xff\xd9")
            # Todo lo que venga después de EOI se descarta
            return b"".join(partes)
        if marcador == 0x01 or 0xD0 <= marcador <= 0xD7:
            partes.append(bytes([0xFF, marcador]))
            i += 2
            continue
        if i + 4 > n:
            raise _invalida()
        largo = struct.unpack(">H", b[i + 2 : i + 4])[0]
        if largo < 2 or i + 2 + largo > n:
            raise _invalida()
        fin = i + 2 + largo
        if marcador == 0xDA:
            # Inicio de un barrido. Los datos comprimidos siguen hasta el siguiente marcador real
            # (0xFF seguido de algo distinto de 0x00 y de los marcadores de reinicio)
            j = fin
            while j < n - 1:
                if b[j] == 0xFF:
                    sig = b[j + 1]
                    if sig != 0x00 and not (0xD0 <= sig <= 0xD7) and sig != 0xFF:
                        break
                j += 1
            if j >= n - 1:
                raise _invalida()
            partes.append(b[i:j])
            vio_imagen = True
            i = j
            continue
        if _conservar_jpeg(marcador, b[i + 4 : fin]):
            partes.append(b[i:fin])
        i = fin
    raise _invalida()


# Fragmentos PNG que se conservan, los necesarios y los que afectan cómo se ve
_PNG_CONSERVAR = {"IHDR", "PLTE", "tRNS", "gAMA", "cHRM", "sRGB", "iCCP", "sBIT", "bKGD", "pHYs"}


def _fragmento(tipo: str, datos: bytes) -> bytes:
    cuerpo = tipo.encode("latin1") + datos
    return struct.pack(">I", len(datos)) + cuerpo + struct.pack(">I", zlib.crc32(cuerpo) & 0xFFFFFFFF)


def _reconstruir_png(b: bytes) -> bytes:
    """Reconstruye el PNG con los fragmentos permitidos y un IDAT nuevo."""
    conservados: list[bytes] = []
    idat: list[bytes] = []
    ihdr: bytes | None = None
    i = 8
    vio_fin = False
    while i < len(b):
        if i + 12 > len(b):
            raise _invalida()
        largo = struct.unpack(">I", b[i : i + 4])[0]
        tipo = b[i + 4 : i + 8].decode("latin1")
        fin = i + 12 + largo
        if largo > 0x7FFFFFFF or fin > len(b) or not re.fullmatch(r"[A-Za-z]{4}", tipo):
            raise _invalida()
        datos = b[i + 8 : i + 8 + largo]
        # La norma exige IHDR como primer fragmento y una sola vez
        if (i == 8) != (tipo == "IHDR"):
            raise _invalida()
        if tipo == "IHDR":
            ihdr = datos
        if tipo == "IDAT":
            idat.append(datos)
        elif tipo in _PNG_CONSERVAR:
            conservados.append(_fragmento(tipo, datos))
        i = fin
        if tipo == "IEND":
            vio_fin = True
            break
    # Lo que venga después de IEND se descarta
    if not vio_fin or ihdr is None or len(ihdr) != 13 or not idat:
        raise _invalida()
    ancho, alto = struct.unpack(">II", ihdr[:8])
    if ancho == 0 or alto == 0 or ancho * alto > MAX_PIXELES:
        raise _invalida()
    try:
        d = zlib.decompressobj()
        crudo = d.decompress(b"".join(idat), MAX_DESCOMPRIMIDO)
        if d.unconsumed_tail:
            raise _invalida()
    except zlib.error:
        raise _invalida() from None
    # IHDR primero, como exige la norma, después el resto en su orden original
    ihdr_fragmento = conservados.pop(0)
    return b"".join([b[:8], ihdr_fragmento, *conservados, _fragmento("IDAT", zlib.compress(crudo, 9)), _fragmento("IEND", b"")])


def validar_y_limpiar(datos: bytes, tipo_declarado: str | None) -> tuple[str, bytes]:
    tipo = detectar_tipo(datos)
    if not tipo:
        raise HttpError(415, "tipo_no_soportado", "Solo se aceptan imágenes JPEG o PNG")
    if tipo_declarado and tipo_declarado != tipo:
        raise HttpError(415, "tipo_no_coincide", "El tipo declarado no coincide con el contenido del archivo")
    limpio = _reconstruir_jpeg(datos) if tipo == "image/jpeg" else _reconstruir_png(datos)
    return tipo, limpio
