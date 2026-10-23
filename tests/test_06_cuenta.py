"""Verificación de correo, contraseñas filtradas, sesiones, alertas, retención e imágenes."""

import base64
import hashlib
import re
import secrets
import struct
import zlib

import psycopg
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from fqs.errores import HttpError
from fqs.limites import limiter
from fqs.seguridad.filtradas import RevisorFiltradas
from fqs.seguridad.imagenes import validar_y_limpiar
from fqs.seguridad.totp import CifradoSecretos

from conftest import ADMIN_PASSWORD, PASSWORD


@pytest.fixture(autouse=True)
def limpiar(e):
    limiter.reset()


def datos_registro(e, sufijo: str, **extra) -> dict:
    return {
        "nombre": f"Familia {sufijo}",
        "username": f"fam_{sufijo}",
        "correo": f"{sufijo}@prueba.mx",
        "password": PASSWORD,
        "fechaNacimiento": "1988-04-12",
        "ciudadId": e.ciudad_id,
        "avisoPrivacidadId": e.aviso_id,
        **extra,
    }


def ultimo_codigo(e, destino: str) -> str:
    return [x for x in e.correo.enviados if x.tipo == "verificacion" and x.destino == destino][-1].token


def otro_codigo(c: str) -> str:
    return "11111111" if c == "00000000" else "00000000"


def test_con_correo_la_cuenta_no_existe_hasta_verificar(e):
    r = e.api("POST", "/v1/auth/registro", json_=datos_registro(e, "pendiente"))
    assert r.status == 202
    assert r.body["destino"] == "pe•••••••@prueba.mx"
    assert r.body["canal"] == "correo"
    assert "tokens" not in r.body
    antes = e.sql("SELECT count(*)::int AS n FROM fqs.usuarios WHERE username = 'fam_pendiente'")
    assert antes[0]["n"] == 0, "la cuenta todavía no existe"
    # En la base no queda la contraseña, solo su hash scrypt dentro de los datos pendientes
    pendiente = e.sql("SELECT datos::text AS d, codigo_hash FROM fqs.verificaciones_contacto WHERE id = %s", [r.body["registroId"]])
    assert "Arbol-Nogal" not in pendiente[0]["d"]
    assert "scrypt$" in pendiente[0]["d"]
    assert re.match(r"^[0-9a-f]{64}$", pendiente[0]["codigo_hash"])

    primero = ultimo_codigo(e, "pendiente@prueba.mx")
    assert e.api("POST", "/v1/auth/registro/reenviar", json_={"registroId": r.body["registroId"]}).status == 202
    segundo = ultimo_codigo(e, "pendiente@prueba.mx")
    if primero != segundo:
        assert e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r.body["registroId"], "codigo": primero}).status == 400
    v = e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r.body["registroId"], "codigo": segundo})
    assert v.status == 201
    assert v.body["tokens"]["accessToken"].startswith("fqs_at_")
    u = e.sql("SELECT correo_verificado_en FROM fqs.usuarios WHERE username = 'fam_pendiente'")
    assert u[0]["correo_verificado_en"]
    # El mismo código ya no sirve
    assert e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r.body["registroId"], "codigo": segundo}).status == 400

    # Cinco códigos equivocados agotan el registro aunque después llegue el correcto
    r2 = e.api("POST", "/v1/auth/registro", json_=datos_registro(e, "agotado"))
    bueno = ultimo_codigo(e, "agotado@prueba.mx")
    for _ in range(5):
        e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r2.body["registroId"], "codigo": otro_codigo(bueno)})
    assert e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r2.body["registroId"], "codigo": bueno}).status == 400
    # Un id inventado responde igual que uno real
    assert e.api("POST", "/v1/auth/registro/reenviar", json_={"registroId": e.ciudad_id}).status == 202


def test_nadie_puede_apartar_el_correo_de_otra_persona(e):
    # Alguien registra el correo de la víctima y nunca lo verifica
    atacante = e.api("POST", "/v1/auth/registro", json_=datos_registro(e, "impostor", correo="victima@prueba.mx"))
    assert atacante.status == 202
    # La dueña real se registra con su correo y lo verifica sin problema
    real = e.registrar("victima")
    assert real["usuario"]["correo"] == "victima@prueba.mx"
    # El registro pendiente del impostor quedó inservible
    codigo_impostor = [x for x in e.correo.enviados if x.tipo == "verificacion" and x.destino == "victima@prueba.mx"][0].token
    assert e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": atacante.body["registroId"], "codigo": codigo_impostor}).status == 400
    # Tampoco puede ponerlo en su propia cuenta, a la víctima solo le llega un aviso
    otro = e.registrar("impostor2")
    t = otro["tokens"]["accessToken"]
    cambio = e.api("PATCH", "/v1/yo", token=t, json_={"correo": "victima@prueba.mx", "passwordActual": PASSWORD})
    assert cambio.status == 200
    assert e.correo.enviados[-1].tipo == "ya_registrado"
    assert e.api("POST", "/v1/yo/correo/verificar", token=t, json_={"codigo": "12345678"}).status == 400


def test_el_codigo_de_recuperacion_solo_va_a_correos_verificados(e):
    fam = e.registrar("sinverificar")
    e.sql("UPDATE fqs.usuarios SET correo_verificado_en = NULL WHERE id = %s", [fam["usuario"]["id"]])
    antes = len(e.correo.enviados)
    limiter.reset()
    r = e.api("POST", "/v1/auth/recuperar", json_={"identificador": "sinverificar@prueba.mx"})
    assert r.status == 202
    assert len(e.correo.enviados) == antes, "no se mandó ningún código"


def test_limite_de_recuperacion_por_ip(e):
    """5 solicitudes de código por IP cada hora, la sexta se bloquea."""
    limiter.reset()
    e.servicios.limites.recuperacion_cuenta.limpiar()
    for i in range(5):
        assert e.api("POST", "/v1/auth/recuperar", json_={"identificador": f"nadie{i}@prueba.mx"}).status == 202
    assert e.api("POST", "/v1/auth/recuperar", json_={"identificador": "nadie9@prueba.mx"}).status == 429
    limiter.reset()


def test_contrasenas_filtradas_sin_mandar_la_contrasena_ni_el_hash_completo(e):
    e.consultas_filtradas.clear()
    r = e.api("POST", "/v1/auth/registro", json_=datos_registro(e, "filtrada", password="Laguna-Brava-Azul-77"))
    assert r.status == 422
    assert r.body["error"]["codigo"] == "contrasena_filtrada"
    url = e.consultas_filtradas[-1]
    assert re.match(r"^https://api\.pwnedpasswords\.com/range/[0-9A-F]{5}$", url)
    sha1 = hashlib.sha1(b"Laguna-Brava-Azul-77").hexdigest().upper()
    assert sha1[5:] not in url, "el sufijo nunca sale del servidor"

    fam = e.registrar("cambiapass")
    cambio = e.api("POST", "/v1/yo/contrasena", token=fam["tokens"]["accessToken"], json_={"actual": PASSWORD, "nueva": "Contrasena-Comun-123"})
    assert cambio.status == 422
    assert cambio.body["error"]["codigo"] == "contrasena_filtrada"

    # Si el servicio no responde, la contraseña se acepta (las demás reglas ya se aplicaron)
    async def sin_red(*_a):  # noqa: ANN002, ANN202
        raise OSError("sin red")

    caido = RevisorFiltradas(True, sin_red)
    assert e.correr(caido.veces("lo-que-sea-123")) is None
    e.correr(caido.exigir_no_filtrada("lo-que-sea-123"))


def test_cada_quien_ve_y_cierra_sus_sesiones(e):
    fam = e.registrar("dispositivos")
    otro = e.login("dispositivos@prueba.mx")
    t1 = fam["tokens"]["accessToken"]
    t2 = otro.body["tokens"]["accessToken"]
    lista = e.api("GET", "/v1/yo/sesiones", token=t1)
    assert lista.status == 200
    assert len(lista.body) == 2
    assert lista.body[0]["actual"] is True
    ajena = next(x for x in lista.body if not x["actual"])
    # Otra persona no puede cerrar mis sesiones
    extrana = e.registrar("extrana")
    assert e.api("DELETE", f"/v1/yo/sesiones/{ajena['id']}", token=extrana["tokens"]["accessToken"]).status == 404
    assert e.api("DELETE", f"/v1/yo/sesiones/{ajena['id']}", token=t1).status == 204
    assert e.api("GET", "/v1/yo", token=t2).status == 401
    assert e.api("GET", "/v1/yo", token=t1).status == 200

    tercera = e.login("dispositivos@prueba.mx")
    assert e.api("POST", "/v1/yo/sesiones/cerrar-otras", token=t1).status == 204
    assert e.api("GET", "/v1/yo", token=tercera.body["tokens"]["accessToken"]).status == 401
    assert len(e.api("GET", "/v1/yo/sesiones", token=t1).body) == 1


def test_la_sesion_de_administracion_es_corta_y_tiene_un_tope(e):
    r = e.sql(
        """SELECT extract(epoch FROM refresh_expira_en - creado_en) AS segundos FROM fqs.sesiones
           WHERE usuario_id = %s AND revocada_en IS NULL AND rotada_en IS NULL ORDER BY creado_en DESC LIMIT 1""",
        [e.admin_id],
    )
    assert float(r[0]["segundos"]) <= 30 * 60 + 5, "el refresh de admin dura 30 minutos sin uso"
    # Una familia conserva sus 30 días
    f = e.sql(
        """SELECT extract(epoch FROM s.refresh_expira_en - s.creado_en) AS segundos FROM fqs.sesiones s
           JOIN fqs.usuarios u ON u.id = s.usuario_id WHERE u.rol = 'familia' ORDER BY s.creado_en DESC LIMIT 1"""
    )
    assert float(f[0]["segundos"]) > 29 * 86400
    # Pasado el tope de 12 horas desde el inicio ya no se renueva aunque se haya usado
    e.sql("UPDATE fqs.sesiones SET familia_inicio = now() - interval '13 hours' WHERE usuario_id = %s", [e.admin_id])
    assert e.api("POST", "/v1/auth/refresh", json_={"refreshToken": e.admin_refresh}).status == 401
    e.sql("UPDATE fqs.sesiones SET familia_inicio = now() WHERE usuario_id = %s", [e.admin_id])


def test_rotacion_de_la_clave_del_segundo_factor():
    vieja = base64.b64encode(secrets.token_bytes(32)).decode()
    nueva = base64.b64encode(secrets.token_bytes(32)).decode()
    secreto = secrets.token_bytes(20)
    ident = "6f0c2c1e-1111-4111-8111-111111111111"
    antes = CifradoSecretos(vieja).cifrar(secreto, ident)
    despues = CifradoSecretos(nueva, [vieja])
    assert despues.necesita_recifrar(antes) is True
    assert despues.descifrar(antes, ident) == secreto
    recifrado = despues.cifrar(secreto, ident)
    assert despues.necesita_recifrar(recifrado) is False
    # Ya sin la clave vieja sigue funcionando
    assert CifradoSecretos(nueva).descifrar(recifrado, ident) == secreto
    # Con otra cuenta como dato asociado no se abre
    with pytest.raises(Exception):  # noqa: B017
        despues.descifrar(recifrado, "6f0c2c1e-2222-4222-8222-222222222222")
    # Formato de la primera versión, sin cabecera (iv, etiqueta y cifrado)
    iv = secrets.token_bytes(12)
    sellado = AESGCM(base64.b64decode(vieja)).encrypt(iv, secreto, ident.encode())
    legado = iv + sellado[-16:] + sellado[:-16]
    assert despues.descifrar(legado, ident) == secreto
    assert despues.necesita_recifrar(legado) is True


def test_alertas_por_correo_de_la_bitacora_sin_repetirse(e):
    e.sql("UPDATE fqs.usuarios SET correo_verificado_en = now() WHERE id = %s", [e.admin_id])
    antes = len(e.correo.enviados)
    avisos = e.correr(e.servicios.vigilancia.revisar_bitacora())
    e.pendientes()
    assert avisos > 0
    nuevos = e.correo.enviados[antes:]
    asuntos = {x.asunto for x in nuevos}
    assert any(x.asunto == "Nuevo inicio de sesión en tu cuenta de administración" and x.destino == "admin@fqs.mx" for x in nuevos)
    assert "Varios códigos de verificación equivocados" in asuntos
    assert "Se usó un código de respaldo" in asuntos
    assert "Cerramos tus sesiones por seguridad" in asuntos
    # Volver a revisar no manda nada, la bitácora ya se leyó
    despues = len(e.correo.enviados)
    assert e.correr(e.servicios.vigilancia.revisar_bitacora()) == 0
    e.pendientes()
    assert len(e.correo.enviados) == despues
    lista = e.api("GET", "/v1/admin/alertas", token=e.admin)
    assert lista.status == 200
    assert len(lista.body) >= 4


def test_ancla_externa_de_la_bitacora(e):
    r = e.correr(e.servicios.vigilancia.anclar(True))
    e.pendientes()
    assert r and r["valida"] and r["hash"] and r["hastaId"]
    correo_ancla = e.correo.enviados[-1]
    assert correo_ancla.asunto == "Ancla semanal de la bitácora de seguridad"
    assert r["hash"] in (correo_ancla.texto or "")
    ok = e.api("GET", f"/v1/admin/bitacora/verificar?hastaId={r['hastaId']}&hash={r['hash']}", token=e.admin)
    assert ok.body["coincideAncla"] is True
    assert ok.body["valida"] is True
    mal = e.api("GET", f"/v1/admin/bitacora/verificar?hastaId={r['hastaId']}&hash={'a' * 64}", token=e.admin)
    assert mal.body["coincideAncla"] is False
    assert mal.body["valida"] is False
    # hastaId sin hash no se acepta
    assert e.api("GET", f"/v1/admin/bitacora/verificar?hastaId={r['hastaId']}", token=e.admin).status == 400
    # No se vuelve a mandar antes de 7 días
    assert e.correr(e.servicios.vigilancia.anclar()) is None


def test_poda_de_la_bitacora_con_corte(e):
    ancla = e.sql("SELECT hasta_id::text AS id, hash FROM fqs.anclas_bitacora ORDER BY id DESC LIMIT 1")[0]
    hasta = e.sql("SELECT b.id::text AS id FROM fqs.bitacora_seguridad b ORDER BY b.id OFFSET 5 LIMIT 1")[0]["id"]
    # El backend no puede podar
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        e.correr(e.servicios.db.query("SELECT podar_bitacora($1, 'x')", [hasta]))
    n = e.sql("SELECT fqs.podar_bitacora(%s, 'bitacora-prueba.fqsr') AS n", [hasta])
    assert int(n[0]["n"]) == 6
    v = e.api("GET", f"/v1/admin/bitacora/verificar?hastaId={ancla['id']}&hash={ancla['hash']}", token=e.admin)
    assert v.body["cadenaValida"] is True
    assert v.body["coincideAncla"] is True
    assert len(v.body["cortes"]) == 1
    # Fuera de la poda sigue sin poder borrarse nada, ni los cortes
    with pytest.raises(psycopg.Error, match="solo agregar"):
        e.sql("DELETE FROM fqs.bitacora_seguridad WHERE id = (SELECT max(id) FROM fqs.bitacora_seguridad)")
    with pytest.raises(psycopg.Error, match="solo agregar"):
        e.sql("DELETE FROM fqs.bitacora_cortes")


def test_cuentas_inactivas_aviso_solicitud_y_entrar_lo_cancela(e):
    fam = e.registrar("inactiva")
    uid = fam["usuario"]["id"]
    e.sql("UPDATE fqs.usuarios SET ultimo_acceso_en = now() - interval '25 months' WHERE id = %s", [uid])
    r1 = e.correr(e.servicios.vigilancia.revisar_inactivas())
    e.pendientes()
    assert r1["avisadas"] >= 1
    assert any(x.destino == "inactiva@prueba.mx" and x.asunto == "Tu cuenta se eliminará por falta de uso" for x in e.correo.enviados)
    e.sql("UPDATE fqs.avisos_inactividad SET enviado_en = now() - interval '31 days' WHERE usuario_id = %s", [uid])
    e.sql("UPDATE fqs.usuarios SET ultimo_acceso_en = now() - interval '26 months' WHERE id = %s", [uid])
    e.correr(e.servicios.vigilancia.revisar_inactivas())
    s = e.sql("SELECT origen, estado FROM fqs.solicitudes_eliminacion WHERE usuario_id = %s", [uid])
    assert s[0] == {"origen": "inactividad", "estado": "pendiente"}
    # Vuelve a entrar y todo se cancela
    assert e.login("inactiva@prueba.mx").status == 200
    s2 = e.sql("SELECT count(*)::int AS n FROM fqs.solicitudes_eliminacion WHERE usuario_id = %s", [uid])
    assert s2[0]["n"] == 0


def test_imagenes_sin_datos_escondidos_ni_bombas():
    def trozo(tipo: str, datos: bytes) -> bytes:
        return struct.pack(">I", len(datos)) + tipo.encode("latin1") + datos + bytes(4)

    firma = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])

    def ihdr(w: int, h: int) -> bytes:
        return struct.pack(">II", w, h) + bytes([8, 6, 0, 0, 0])

    zip_pegado = "PK\x03\x04<script>alert(1)</script>".encode("latin1")
    png = (
        firma
        + trozo("IHDR", ihdr(1, 1))
        + trozo("prVt", b"carga privada")
        + trozo("IDAT", zlib.compress(bytes([0, 1, 2, 3, 4])))
        + trozo("IEND", b"")
        + zip_pegado
    )
    _, limpio = validar_y_limpiar(png, "image/png")
    assert b"PK" not in limpio, "el ZIP pegado al final se quitó"
    assert b"prVt" not in limpio, "el fragmento desconocido se quitó"
    assert limpio[-8:-4] == b"IEND"

    # Bomba, un IHDR enorme o datos que descomprimen de más
    bomba = firma + trozo("IHDR", ihdr(100000, 100000)) + trozo("IDAT", zlib.compress(bytes(10))) + trozo("IEND", b"")
    with pytest.raises(HttpError, match="dañada"):
        validar_y_limpiar(bomba, "image/png")
    bomba2 = firma + trozo("IHDR", ihdr(10, 10)) + trozo("IDAT", zlib.compress(bytes(300_000_000))) + trozo("IEND", b"")
    with pytest.raises(HttpError, match="dañada"):
        validar_y_limpiar(bomba2, "image/png")

    # JPEG con comentario y datos después del final
    app0 = bytes([0xFF, 0xE0, 0, 16]) + "JFIF\0\x01\x01\0\0\x01\0\x01\0\0".encode("latin1")
    com = bytes([0xFF, 0xFE, 0, 18]) + "<?php system(1);".encode("latin1")
    sos = bytes([0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0x12, 0xFF, 0x00, 0x34, 0xFF, 0xD9])
    jpeg = bytes([0xFF, 0xD8]) + app0 + com + sos + zip_pegado
    _, j = validar_y_limpiar(jpeg, "image/jpeg")
    assert b"php" not in j
    assert b"PK" not in j
    assert j[-2:] == bytes([0xFF, 0xD9])
    assert bytes([0x12, 0xFF, 0x00, 0x34]) in j, "los datos de la imagen se conservan"


def test_admin_conserva_su_contrasena(e):
    assert e.login("admin@fqs.mx", ADMIN_PASSWORD).status == 200
