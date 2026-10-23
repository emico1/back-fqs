"""
Generador de códigos QR (ISO/IEC 18004) en modo byte con corrección de errores M, sin
dependencias. Se usa para que el panel muestre la clave del segundo factor como QR y la app
de autenticación la lea con la cámara. La clave nunca sale a un servicio externo para
dibujar el QR.

Sigue el algoritmo de la referencia de Project Nayuki (tablas de bloques, Reed-Solomon sobre
GF(256) con polinomio 0x11D, colocación en zigzag y máscaras).
"""

# Corrección de errores M por versión (índice = versión, 1 a 40)
_ECC_POR_BLOQUE = [
    -1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28,
    28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
]
_NUM_BLOQUES = [
    -1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37,
    38, 40, 43, 45, 47, 49,
]
_BITS_FORMATO_M = 0


def _modulos_datos(ver: int) -> int:
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        r -= (25 * n - 10) * n - 55
        if ver >= 7:
            r -= 36
    return r


def _codewords_datos(ver: int) -> int:
    return _modulos_datos(ver) // 8 - _ECC_POR_BLOQUE[ver] * _NUM_BLOQUES[ver]


def _multiplicar(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = ((z << 1) ^ ((z >> 7) * 0x11D)) & 0xFFFF
        z ^= ((y >> i) & 1) * x
    return z


def _divisor_rs(grado: int) -> list[int]:
    r = [0] * grado
    r[grado - 1] = 1
    raiz = 1
    for _ in range(grado):
        for j in range(len(r)):
            r[j] = _multiplicar(r[j], raiz)
            if j + 1 < len(r):
                r[j] ^= r[j + 1]
        raiz = _multiplicar(raiz, 0x02)
    return r


def _residuo_rs(datos: list[int], divisor: list[int]) -> list[int]:
    r = [0] * len(divisor)
    for b in datos:
        factor = b ^ r.pop(0)
        r.append(0)
        for i, coef in enumerate(divisor):
            r[i] ^= _multiplicar(coef, factor)
    return r


def _posiciones_alineacion(ver: int, tam: int) -> list[int]:
    if ver == 1:
        return []
    n = ver // 7 + 2
    paso = 26 if ver == 32 else -(-(ver * 4 + 4) // (n * 2 - 2)) * 2
    r = [6]
    pos = tam - 7
    while len(r) < n:
        r.insert(1, pos)
        pos -= paso
    return r


def _bit(x: int, i: int) -> bool:
    return ((x >> i) & 1) != 0


def matriz_qr(texto: str) -> list[list[bool]]:
    """Matriz de módulos (True = oscuro) del texto en un QR de corrección M."""
    datos_bytes = list(texto.encode("utf-8"))
    ver = 1
    while ver <= 40:
        bits_conteo = 8 if ver <= 9 else 16
        if 4 + bits_conteo + len(datos_bytes) * 8 <= _codewords_datos(ver) * 8:
            break
        ver += 1
    if ver > 40:
        raise ValueError("Texto demasiado largo para un QR")
    tam = ver * 4 + 17

    # Flujo de bits
    bits: list[int] = []

    def agregar(valor: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            bits.append((valor >> i) & 1)

    agregar(0b0100, 4)
    agregar(len(datos_bytes), 8 if ver <= 9 else 16)
    for b in datos_bytes:
        agregar(b, 8)
    capacidad = _codewords_datos(ver) * 8
    agregar(0, min(4, capacidad - len(bits)))
    agregar(0, (8 - len(bits) % 8) % 8)
    relleno = 0xEC
    while len(bits) < capacidad:
        agregar(relleno, 8)
        relleno ^= 0xEC ^ 0x11
    datos = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]

    # Bloques con corrección de errores e intercalado
    num_bloques = _NUM_BLOQUES[ver]
    ecc_largo = _ECC_POR_BLOQUE[ver]
    total = _modulos_datos(ver) // 8
    cortos = num_bloques - total % num_bloques
    largo_corto = total // num_bloques
    divisor = _divisor_rs(ecc_largo)
    bloques: list[list[int]] = []
    k = 0
    for i in range(num_bloques):
        dat = datos[k : k + largo_corto - ecc_largo + (0 if i < cortos else 1)]
        k += len(dat)
        ecc = _residuo_rs(dat, divisor)
        if i < cortos:
            dat = dat + [0]
        bloques.append(dat + ecc)
    final: list[int] = []
    for i in range(len(bloques[0])):
        for j, b in enumerate(bloques):
            if i != largo_corto - ecc_largo or j >= cortos:
                final.append(b[i])

    # Patrones fijos
    m = [[False] * tam for _ in range(tam)]
    fijo = [[False] * tam for _ in range(tam)]

    def poner(x: int, y: int, oscuro: bool) -> None:
        m[y][x] = oscuro
        fijo[y][x] = True

    for i in range(tam):
        poner(6, i, i % 2 == 0)
        poner(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (tam - 4, 3), (3, tam - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                d = max(abs(dx), abs(dy))
                x, y = cx + dx, cy + dy
                if 0 <= x < tam and 0 <= y < tam:
                    poner(x, y, d not in (2, 4))
    alin = _posiciones_alineacion(ver, tam)
    for i in range(len(alin)):
        for j in range(len(alin)):
            if (i == 0 and j == 0) or (i == 0 and j == len(alin) - 1) or (i == len(alin) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    poner(alin[i] + dx, alin[j] + dy, max(abs(dx), abs(dy)) != 1)

    def dibujar_formato(mascara: int) -> None:
        datos_formato = (_BITS_FORMATO_M << 3) | mascara
        rem = datos_formato
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        b = ((datos_formato << 10) | rem) ^ 0x5412
        for i in range(6):
            poner(8, i, _bit(b, i))
        poner(8, 7, _bit(b, 6))
        poner(8, 8, _bit(b, 7))
        poner(7, 8, _bit(b, 8))
        for i in range(9, 15):
            poner(14 - i, 8, _bit(b, i))
        for i in range(8):
            poner(tam - 1 - i, 8, _bit(b, i))
        for i in range(8, 15):
            poner(8, tam - 15 + i, _bit(b, i))
        poner(8, tam - 8, True)

    dibujar_formato(0)
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        b = (ver << 12) | rem
        for i in range(18):
            a = tam - 11 + i % 3
            c = i // 3
            poner(a, c, _bit(b, i))
            poner(c, a, _bit(b, i))

    # Datos en zigzag
    i = 0
    derecha = tam - 1
    while derecha >= 1:
        if derecha == 6:
            derecha = 5
        for vert in range(tam):
            for j in range(2):
                x = derecha - j
                arriba = ((derecha + 1) & 2) == 0
                y = tam - 1 - vert if arriba else vert
                if not fijo[y][x] and i < len(final) * 8:
                    m[y][x] = _bit(final[i >> 3], 7 - (i & 7))
                    i += 1
        derecha -= 2

    # Máscara. Se prueban las 8 y se elige la de menor penalización simple (rachas y bloques)
    def condicion(k: int, x: int, y: int) -> bool:
        if k == 0:
            return (x + y) % 2 == 0
        if k == 1:
            return y % 2 == 0
        if k == 2:
            return x % 3 == 0
        if k == 3:
            return (x + y) % 3 == 0
        if k == 4:
            return (x // 3 + y // 2) % 2 == 0
        if k == 5:
            return (x * y) % 2 + (x * y) % 3 == 0
        if k == 6:
            return ((x * y) % 2 + (x * y) % 3) % 2 == 0
        return ((x + y) % 2 + (x * y) % 3) % 2 == 0

    def aplicar(k: int) -> None:
        for y in range(tam):
            for x in range(tam):
                if not fijo[y][x] and condicion(k, x, y):
                    m[y][x] = not m[y][x]

    def penalizacion() -> int:
        p = 0
        for linea in [m[y] for y in range(tam)] + [[m[y][x] for y in range(tam)] for x in range(tam)]:
            racha = 0
            color = None
            for v in linea:
                if v != color:
                    color = v
                    racha = 1
                else:
                    racha += 1
                    if racha == 5:
                        p += 3
                    elif racha > 5:
                        p += 1
        for y in range(tam - 1):
            for x in range(tam - 1):
                c = m[y][x]
                if c == m[y][x + 1] and c == m[y + 1][x] and c == m[y + 1][x + 1]:
                    p += 3
        return p

    mejor = 0
    menor = None
    for k in range(8):
        aplicar(k)
        dibujar_formato(k)
        p = penalizacion()
        if menor is None or p < menor:
            menor = p
            mejor = k
        aplicar(k)
    aplicar(mejor)
    dibujar_formato(mejor)
    return m


def svg_qr(texto: str) -> str:
    """SVG del QR con margen de 4 módulos, listo para usarse como imagen."""
    m = matriz_qr(texto)
    borde = 4
    tam = len(m) + borde * 2
    trazos = []
    for y, fila in enumerate(m):
        for x, oscuro in enumerate(fila):
            if oscuro:
                trazos.append(f"M{x + borde},{y + borde}h1v1h-1z")
    d = "".join(trazos)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {tam} {tam}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#fff"/><path d="{d}" fill="#000"/></svg>'
    )
