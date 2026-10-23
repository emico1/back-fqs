"""Segundo factor de administración, bitácora encadenada, correo y configuración."""

import json

import psycopg
import pytest

from fqs.config import ErrorConfig, cargar_config
from fqs.correo import CorreoBrevo
from fqs.http_cliente import RespuestaHttp
from fqs.limites import limiter
from fqs.seguridad.contrasenas import hash_contrasena
from fqs.seguridad.totp import desde_base32, hash_codigo_respaldo, hotp, paso_actual, totp

from conftest import ADMIN_PASSWORD

ADMIN2_PASSWORD = "Otro-Admin-Seguro-2026"


@pytest.fixture(autouse=True)
def limpiar(e):
    # Todas las pruebas salen de 127.0.0.1 y aquí hay muchos inicios de sesión seguidos
    limiter.reset()


def siguiente_codigo(e, secreto: bytes, usuario_id: str) -> str:
    """Código de la app para el siguiente paso todavía no usado, así no se repite un código."""
    r = e.sql("SELECT ultimo_paso FROM fqs.usuarios_2fa WHERE usuario_id = %s", [usuario_id])
    actual = paso_actual()
    ultimo = int(r[0]["ultimo_paso"] or 0)
    # Si el siguiente paso libre ya cae fuera de la ventana, se simula que pasaron 30 segundos
    # moviendo hacia atrás el último paso usado. Así la prueba no depende del reloj
    if ultimo + 1 > actual + 1:
        e.sql("UPDATE fqs.usuarios_2fa SET ultimo_paso = %s WHERE usuario_id = %s", [actual - 1, usuario_id])
        return hotp(secreto, actual)
    return hotp(secreto, max(ultimo + 1, actual))


def eventos(e, accion: str) -> list[dict]:
    return e.sql("SELECT * FROM fqs.bitacora_seguridad WHERE accion = %s ORDER BY id", [accion])


def test_totp_coincide_con_los_vectores_de_los_rfc():
    s = b"12345678901234567890"
    # Apéndice B del RFC 6238 (SHA1), los 6 dígitos finales de cada valor de 8
    assert totp(s, 59_000) == "287082"
    assert totp(s, 1_111_111_109_000) == "081804"
    assert totp(s, 1_234_567_890_000) == "005924"
    assert totp(s, 20_000_000_000_000) == "353130"
    # Apéndice D del RFC 4226
    assert [hotp(s, i) for i in range(4)] == ["755224", "287082", "359152", "969429"]


def test_un_admin_sin_segundo_factor_solo_puede_activarlo(e):
    h = e.correr(hash_contrasena(ADMIN2_PASSWORD))
    e.sql(
        """INSERT INTO fqs.usuarios (nombre, username, correo, password_hash, rol, tipo_cuenta)
           VALUES ('Admin Dos', 'admin2', 'admin2@fqs.mx', %s, 'admin', 'individual')""",
        [h],
    )
    lo = e.login("admin2@fqs.mx", ADMIN2_PASSWORD)
    assert lo.status == 200
    assert lo.body["configurar2fa"] is True
    t = lo.body["tokens"]["accessToken"]
    bloqueada = e.api("GET", "/v1/admin/calidad", token=t)
    assert bloqueada.status == 403
    assert bloqueada.body["error"]["codigo"] == "requiere_2fa"
    assert e.api("POST", "/v1/admin/ciudades", token=t, json_={"nombre": "Saltillo", "estado": "Coahuila", "zonaHoraria": "America/Monterrey"}).status == 403
    estado = e.api("GET", "/v1/admin/2fa", token=t)
    assert estado.status == 200
    assert estado.body["activo"] is False
    assert estado.body["obligatorio"] is True
    assert len(eventos(e, "requiere_2fa")) >= 2

    # Activar pide la contraseña otra vez
    assert e.api("POST", "/v1/admin/2fa/iniciar", token=t, json_={"password": "equivocada-123"}).status == 400
    ini = e.api("POST", "/v1/admin/2fa/iniciar", token=t, json_={"password": ADMIN2_PASSWORD})
    assert ini.status == 200
    assert ini.body["uri"].startswith("otpauth://totp/Familias%20que%20Suman%3Aadmin2%40fqs.mx?secret=")
    assert ini.body["qrSvg"].startswith("<svg")
    secreto = desde_base32(ini.body["secreto"])
    assert len(secreto) == 20

    # En la base el secreto está cifrado, no aparece en claro
    guardado = e.sql(
        "SELECT f.secreto_cifrado FROM fqs.usuarios_2fa f JOIN fqs.usuarios u ON u.id = f.usuario_id WHERE u.username = 'admin2'"
    )
    assert secreto not in bytes(guardado[0]["secreto_cifrado"])

    assert e.api("POST", "/v1/admin/2fa/confirmar", token=t, json_={"codigo": "000000"}).status == 400
    conf = e.api("POST", "/v1/admin/2fa/confirmar", token=t, json_={"codigo": totp(secreto)})
    assert conf.status == 200
    assert len(conf.body["codigosRespaldo"]) == 10
    import re

    assert re.match(r"^[a-z2-9]{4}-[a-z2-9]{4}$", conf.body["codigosRespaldo"][0])
    # La misma sesión ya quedó verificada
    assert e.api("GET", "/v1/admin/calidad", token=t).status == 200
    # No se puede volver a iniciar para cambiar el secreto
    assert e.api("POST", "/v1/admin/2fa/iniciar", token=t, json_={"password": ADMIN2_PASSWORD}).status == 409
    # Los códigos de respaldo se guardan como hash
    codigos = e.sql("SELECT codigo_hash FROM fqs.codigos_respaldo_2fa")
    assert all(re.match(r"^[0-9a-f]{64}$", f["codigo_hash"]) for f in codigos)
    assert conf.body["codigosRespaldo"][0] not in json.dumps(codigos)


def test_con_segundo_factor_la_contrasena_sola_no_da_sesion(e):
    lo = e.login("admin@fqs.mx", ADMIN_PASSWORD)
    assert lo.status == 200
    assert lo.body["requiere2fa"] is True
    assert "tokens" not in lo.body
    assert lo.body["desafio"].startswith("fqs_2f_")
    desafio = lo.body["desafio"]

    mal = e.api("POST", "/v1/auth/2fa", json_={"desafio": desafio, "codigo": "123456"})
    assert mal.status == 401
    assert mal.body["error"]["codigo"] == "codigo_2fa"
    assert mal.body["error"]["detalles"]["intentosRestantes"] == 4

    # El código del paso que ya se usó al activar no sirve otra vez
    usado = e.sql("SELECT ultimo_paso FROM fqs.usuarios_2fa WHERE usuario_id = %s", [e.admin_id])
    repetido = e.api("POST", "/v1/auth/2fa", json_={"desafio": desafio, "codigo": hotp(e.admin_secreto, int(usado[0]["ultimo_paso"]))})
    assert repetido.status == 401

    codigo = siguiente_codigo(e, e.admin_secreto, e.admin_id)
    bien = e.api("POST", "/v1/auth/2fa", json_={"desafio": desafio, "codigo": codigo})
    assert bien.status == 200, bien.body
    assert bien.body["tokens"]["accessToken"].startswith("fqs_at_")
    assert bien.body["usuario"]["rol"] == "admin"
    assert e.api("GET", "/v1/admin/calidad", token=bien.body["tokens"]["accessToken"]).status == 200

    # El desafío ya se canjeó
    otra_vez = e.api("POST", "/v1/auth/2fa", json_={"desafio": desafio, "codigo": codigo})
    assert otra_vez.status == 401
    assert otra_vez.body["error"]["codigo"] == "desafio_invalido"

    # Al renovar, la sesión sigue marcada con segundo factor
    ren = e.api("POST", "/v1/auth/refresh", json_={"refreshToken": bien.body["tokens"]["refreshToken"]})
    assert ren.status == 200
    assert e.api("GET", "/v1/admin/calidad", token=ren.body["tokens"]["accessToken"]).status == 200
    f = e.sql("SELECT bool_and(segundo_factor) AS todas FROM fqs.sesiones WHERE usuario_id = %s AND revocada_en IS NULL", [e.admin_id])
    assert f[0]["todas"] is True
    assert len(eventos(e, "2fa_correcto")) >= 1
    assert len(eventos(e, "2fa_fallido")) >= 2


def test_codigo_de_respaldo_de_un_solo_uso_y_desafio_que_se_agota(e):
    lc = e.servicios.limites.login_cuenta
    lc.reiniciar(f"2fa {e.admin_id}")
    l0 = e.login("admin@fqs.mx", ADMIN_PASSWORD)
    s0 = e.api("POST", "/v1/auth/2fa", json_={"desafio": l0.body["desafio"], "codigo": siguiente_codigo(e, e.admin_secreto, e.admin_id)})
    assert s0.status == 200
    regen = e.api("POST", "/v1/admin/2fa/codigos-respaldo", token=s0.body["tokens"]["accessToken"], json_={"codigo": "111111"})
    assert regen.status == 400
    iniciales = e.sql("SELECT count(*)::int AS n FROM fqs.codigos_respaldo_2fa WHERE usuario_id = %s", [e.admin_id])
    assert iniciales[0]["n"] == 10

    # Se fija un código de respaldo conocido directamente en la base para probar el canje
    e.sql("INSERT INTO fqs.codigos_respaldo_2fa (usuario_id, codigo_hash) VALUES (%s, %s)", [e.admin_id, hash_codigo_respaldo(e.admin_id, "k7m2-q9xa")])
    l1 = e.login("admin@fqs.mx", ADMIN_PASSWORD)
    assert e.api("POST", "/v1/auth/2fa", json_={"desafio": l1.body["desafio"], "codigo": "K7M2 Q9XA"}).status == 200
    l2 = e.login("admin@fqs.mx", ADMIN_PASSWORD)
    assert e.api("POST", "/v1/auth/2fa", json_={"desafio": l2.body["desafio"], "codigo": "k7m2-q9xa"}).status == 401, "ya se usó"
    assert len(eventos(e, "2fa_codigo_respaldo_usado")) == 1

    # Cinco códigos equivocados agotan el desafío
    lc.reiniciar(f"2fa {e.admin_id}")
    l3 = e.login("admin@fqs.mx", ADMIN_PASSWORD)
    for _ in range(4):
        assert e.api("POST", "/v1/auth/2fa", json_={"desafio": l3.body["desafio"], "codigo": "000000"}).status == 401
    lc.reiniciar(f"2fa {e.admin_id}")
    assert e.api("POST", "/v1/auth/2fa", json_={"desafio": l3.body["desafio"], "codigo": "000000"}).status == 401
    agotado = e.api("POST", "/v1/auth/2fa", json_={"desafio": l3.body["desafio"], "codigo": siguiente_codigo(e, e.admin_secreto, e.admin_id)})
    assert agotado.body["error"]["codigo"] == "desafio_invalido"
    # Un desafío inventado
    assert e.api("POST", "/v1/auth/2fa", json_={"desafio": "fqs_2f_" + "a" * 43, "codigo": "123456"}).status == 401
    lc.reiniciar(f"2fa {e.admin_id}")


def test_cada_accion_de_administracion_queda_en_la_bitacora_sin_el_cuerpo(e):
    fam = e.registrar("bitacora")
    assert e.api("GET", "/v1/admin/calidad", token=fam["tokens"]["accessToken"]).status == 403
    denegado = eventos(e, "acceso_denegado")[-1]
    assert str(denegado["actor_id"]) == fam["usuario"]["id"]
    assert denegado["ruta"] == "GET /v1/admin/calidad"

    cat = e.api(
        "POST",
        "/v1/admin/categorias",
        token=e.admin,
        json_={"clave": "BITACORA_PRUEBA", "nombre": "Categoría secreta de bitácora", "descripcion": "Texto privado que no debe guardarse"},
    )
    assert cat.status in (200, 201), cat.body
    accion = eventos(e, "admin_accion")[-1]
    assert accion["ruta"] == "POST /v1/admin/categorias"
    assert str(accion["actor_id"]) == e.admin_id
    assert "Texto privado" not in json.dumps(accion, default=str)
    assert len(accion["hash"]) == 64

    lista = e.api("GET", "/v1/admin/bitacora?accion=admin_accion&limite=5", token=e.admin)
    assert lista.status == 200
    assert len(lista.body["eventos"]) >= 1
    assert lista.body["eventos"][0]["actorUsername"] == "admin"
    assert e.api("GET", "/v1/admin/bitacora?accion=DROP%20TABLE", token=e.admin).status == 400
    assert e.api("GET", "/v1/admin/bitacora?otro=1", token=e.admin).status == 400

    ver = e.api("GET", "/v1/admin/bitacora/verificar", token=e.admin)
    assert ver.status == 200
    assert ver.body["valida"] is True
    assert ver.body["revisadas"] >= 10


def test_la_bitacora_no_se_puede_editar_ni_borrar_y_una_alteracion_se_detecta(e):
    # El rol del backend no tiene permiso
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        e.correr(e.servicios.db.query("UPDATE bitacora_seguridad SET accion = 'nada'"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        e.correr(e.servicios.db.query("DELETE FROM bitacora_seguridad"))
    # Ni el dueño de la base, el trigger lo impide
    with pytest.raises(psycopg.Error, match="solo agregar"):
        e.sql("DELETE FROM fqs.bitacora_seguridad WHERE id = 1")
    with pytest.raises(psycopg.Error, match="solo agregar"):
        e.sql("TRUNCATE fqs.bitacora_seguridad")

    # Alguien con acceso total desactiva el trigger y cambia una fila, la cadena lo delata
    fila = e.sql("SELECT id, accion FROM fqs.bitacora_seguridad ORDER BY id LIMIT 1 OFFSET 2")[0]
    e.sql("ALTER TABLE fqs.bitacora_seguridad DISABLE TRIGGER inmutable")
    try:
        e.sql("UPDATE fqs.bitacora_seguridad SET accion = 'login_admin' WHERE id = %s", [fila["id"]])
        ver = e.api("GET", "/v1/admin/bitacora/verificar", token=e.admin)
        assert ver.body["valida"] is False
        assert ver.body["primerError"] == str(fila["id"])
        # Se deja como estaba para no afectar otras pruebas
        e.sql("UPDATE fqs.bitacora_seguridad SET accion = %s WHERE id = %s", [fila["accion"], fila["id"]])
    finally:
        e.sql("ALTER TABLE fqs.bitacora_seguridad ENABLE TRIGGER inmutable")
    assert e.api("GET", "/v1/admin/bitacora/verificar", token=e.admin).body["valida"] is True


def test_reusar_un_refresh_token_queda_en_la_bitacora(e):
    fam = e.registrar("reuso2")
    assert e.api("POST", "/v1/auth/refresh", json_={"refreshToken": fam["tokens"]["refreshToken"]}).status == 200
    assert e.api("POST", "/v1/auth/refresh", json_={"refreshToken": fam["tokens"]["refreshToken"]}).status == 401
    assert str(eventos(e, "refresh_reutilizado")[-1]["actor_id"]) == fam["usuario"]["id"]


def test_correo_de_recuperacion_por_brevo(e):
    llamadas: list[dict] = []
    respuesta = {"status": 201, "texto": '{"messageId":"<1@relay>"}'}

    async def http(metodo, url, encabezados, cuerpo, tiempo):  # noqa: ANN001, ANN202
        llamadas.append({"url": url, "headers": encabezados, "cuerpo": cuerpo})
        return RespuestaHttp(respuesta["status"], respuesta["texto"])

    brevo = CorreoBrevo("xkeysib-prueba", "no-responder@fqs.mx", "FqS", http)
    e.correr(brevo.enviar_recuperacion("familia@correo.mx", "12345678"))
    assert llamadas[0]["url"] == "https://api.brevo.com/v3/smtp/email"
    assert llamadas[0]["headers"]["api-key"] == "xkeysib-prueba"
    cuerpo = json.loads(llamadas[0]["cuerpo"])
    assert cuerpo["sender"] == {"name": "FqS", "email": "no-responder@fqs.mx"}
    assert cuerpo["to"] == [{"email": "familia@correo.mx"}]
    assert "1234 5678" in cuerpo["htmlContent"]

    respuesta.update(status=401, texto='{"code":"unauthorized","message":"Key not found"}')
    with pytest.raises(RuntimeError, match="Brevo respondió 401"):
        e.correr(brevo.enviar_recuperacion("familia@correo.mx", "12345678"))


def test_la_configuracion_exige_la_clave_y_no_acepta_2fa_opcional_en_produccion():
    with pytest.raises(ErrorConfig, match="CLAVE_CIFRADO_2FA"):
        cargar_config({"DATABASE_URL": "postgres://x@localhost/x"})
    with pytest.raises(ErrorConfig, match="32 bytes"):
        cargar_config({"DATABASE_URL": "postgres://x@localhost/x", "CLAVE_CIFRADO_2FA": "corta"})
    with pytest.raises(ErrorConfig, match="obligatorio"):
        cargar_config({"DATABASE_URL": "postgres://x@localhost/x", "ENTORNO": "production", "ADMIN_2FA": "opcional"})
    with pytest.raises(ErrorConfig, match="CORREO_REMITENTE"):
        cargar_config({"DATABASE_URL": "postgres://x@localhost/x", "ADMIN_2FA": "opcional", "BREVO_API_KEY": "x"})
