"""Seguridad HTTP general, registro, inicio de sesión y sesiones con refresh rotativo."""

import re

from fqs.limites import limiter

from conftest import ADMIN_PASSWORD, PASSWORD

# ---------------- Seguridad HTTP general ----------------


def test_encabezados_de_seguridad(e):
    r = e.api("GET", "/v1/salud")
    assert r.status == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("cache-control") == "no-store"
    assert "default-src 'none'" in r.headers.get("content-security-policy", "")
    assert r.headers.get("x-powered-by") is None
    assert r.headers.get("server") is None


def test_rutas_protegidas_exigen_sesion(e):
    assert e.api("GET", "/v1/yo").status == 401
    assert e.api("GET", "/v1/yo", token="fqs_at_falso").status == 401
    assert e.api("GET", "/v1/yo", token=e.admin).status == 200


def test_parametro_que_no_es_uuid_responde_404(e):
    r = e.api("GET", "/v1/actividades/1%27%20OR%201=1", token=e.admin)
    assert r.status == 404


def test_cuerpo_que_no_es_json_o_demasiado_grande(e):
    r1 = e.api("POST", "/v1/auth/login", crudo=b"identificador=x", tipo="application/x-www-form-urlencoded")
    assert r1.status == 415
    r2 = e.api("POST", "/v1/auth/login", json_={"identificador": "x" * 70_000, "password": "x"})
    assert r2.status == 413
    r3 = e.api("POST", "/v1/auth/login", crudo=b"{malo", tipo="application/json")
    assert r3.status == 400
    assert r3.body["error"]["codigo"] == "json_invalido"


def test_metodo_no_permitido(e):
    assert e.api("DELETE", "/v1/catalogos").status == 405


def test_ruta_inexistente(e):
    r = e.api("GET", "/v1/no-existe")
    assert r.status == 404
    assert r.body["error"]["mensaje"] == "Ruta no encontrada"
    assert r.body["requestId"]


# ---------------- Registro e inicio de sesión ----------------


def test_sin_aviso_publicado_el_registro_no_esta_disponible(e):
    cat = e.api("GET", "/v1/catalogos")
    assert cat.body["avisoPrivacidad"] is None
    r = e.api(
        "POST",
        "/v1/auth/registro",
        json_={
            "nombre": "X",
            "username": "x_x",
            "correo": "x@x.mx",
            "password": PASSWORD,
            "fechaNacimiento": "1990-01-01",
            "ciudadId": e.ciudad_id,
            "avisoPrivacidadId": e.ciudad_id,
        },
    )
    assert r.status in (400, 503)


def test_admin_publica_el_aviso_de_privacidad(e):
    r = e.api(
        "POST", "/v1/admin/avisos-privacidad", token=e.admin, json_={"version": "2026.1", "contenido": "Aviso de privacidad de prueba. " * 5}
    )
    assert r.status == 201, r.body
    e.aviso_id = r.body["id"]
    cat = e.api("GET", "/v1/catalogos")
    assert cat.body["avisoPrivacidad"]["id"] == e.aviso_id
    assert any(c["clave"] == "NINOS" for c in cat.body["categorias"])


def test_rechaza_campos_no_declarados(e):
    r = e.api(
        "POST",
        "/v1/auth/registro",
        json_={
            "nombre": "Malo",
            "username": "malo",
            "correo": "malo@x.mx",
            "password": PASSWORD,
            "fechaNacimiento": "1990-01-01",
            "ciudadId": e.ciudad_id,
            "avisoPrivacidadId": e.aviso_id,
            "rol": "admin",
        },
    )
    assert r.status == 400
    assert r.body["error"]["codigo"] == "validacion"
    assert any(d["campo"] == "rol" for d in r.body["error"]["detalles"])


def test_contrasena_debil_menor_de_edad_y_aviso_desactualizado(e):
    limiter.reset()
    base = {
        "nombre": "Prueba",
        "username": "prueba1",
        "correo": "p1@x.mx",
        "fechaNacimiento": "1990-01-01",
        "ciudadId": e.ciudad_id,
        "avisoPrivacidadId": e.aviso_id,
    }
    assert e.api("POST", "/v1/auth/registro", json_={**base, "password": "corta"}).status == 422
    assert e.api("POST", "/v1/auth/registro", json_={**base, "password": "prueba1-Larga-99"}).status == 422
    assert e.api("POST", "/v1/auth/registro", json_={**base, "password": PASSWORD, "fechaNacimiento": "2012-01-01"}).status == 422
    assert e.api("POST", "/v1/auth/registro", json_={**base, "password": PASSWORD, "avisoPrivacidadId": e.ciudad_id}).status == 409


def test_correo_y_telefono_a_la_vez_o_ninguno(e):
    limiter.reset()
    base = {
        "nombre": "Prueba",
        "username": "prueba2",
        "password": PASSWORD,
        "fechaNacimiento": "1990-01-01",
        "ciudadId": e.ciudad_id,
        "avisoPrivacidadId": e.aviso_id,
    }
    ambos = e.api("POST", "/v1/auth/registro", json_={**base, "correo": "a@x.mx", "telefono": "8112345600"})
    assert ambos.status == 400
    assert ambos.body["error"]["detalles"][0]["campo"] == "correo"
    assert e.api("POST", "/v1/auth/registro", json_=base).status == 400


def test_registro_correcto_devuelve_tokens_y_perfil_sin_hash(e):
    r = e.registrar("lopez")
    assert r["tokens"]["accessToken"].startswith("fqs_at_")
    assert r["usuario"]["categorias"] == ["MEDIO_AMBIENTE"]
    assert r["usuario"]["preferencias"]["quiereParticipar"] is True
    assert "password_hash" not in r["usuario"]
    assert "scrypt$" not in str(r)
    limiter.reset()
    dup = e.api(
        "POST",
        "/v1/auth/registro",
        json_={
            "nombre": "Otra",
            "username": "otra",
            "correo": "LOPEZ@prueba.mx",
            "password": PASSWORD,
            "fechaNacimiento": "1990-01-01",
            "ciudadId": e.ciudad_id,
            "avisoPrivacidadId": e.aviso_id,
        },
    )
    # No revela que el correo existe, responde igual y al correo le llega un aviso
    assert dup.status == 202
    aviso = e.correo.enviados[-1]
    assert aviso.tipo == "ya_registrado"
    assert aviso.destino == "lopez@prueba.mx"


def test_registro_con_telefono_e_inicio_de_sesion_con_telefono(e):
    e.registrar("tel", correo=None, telefono="81 1234 5678")
    r = e.login("8112345678")
    assert r.status == 200


def test_la_contrasena_se_guarda_con_scrypt(e):
    r = e.sql("SELECT password_hash FROM fqs.usuarios WHERE username = 'fam_lopez'")
    assert re.match(r"^scrypt\$131072\$8\$1\$", r[0]["password_hash"])


def test_mismo_mensaje_y_bloqueo_tras_5_fallos(e):
    limiter.reset()
    a = e.api("POST", "/v1/auth/login", json_={"identificador": "nadie@x.mx", "password": "loquesea12345"})
    b = e.api("POST", "/v1/auth/login", json_={"identificador": "lopez@prueba.mx", "password": "incorrecta123"})
    assert a.status == 401
    assert b.status == 401
    assert a.body["error"]["mensaje"] == b.body["error"]["mensaje"]
    for _ in range(4):
        e.api("POST", "/v1/auth/login", json_={"identificador": "lopez@prueba.mx", "password": "incorrecta123"})
    bloqueada = e.api("POST", "/v1/auth/login", json_={"identificador": "lopez@prueba.mx", "password": PASSWORD})
    assert bloqueada.status == 429
    e.servicios.limites.login_cuenta.reiniciar("cuenta lopez@prueba.mx")


def test_limite_por_ip_del_inicio_de_sesion(e):
    """20 intentos por IP cada 15 minutos. El 21 se bloquea con 429 y Retry-After."""
    limiter.reset()
    for i in range(20):
        r = e.api("POST", "/v1/auth/login", json_={"identificador": f"nadie{i}@x.mx", "password": "loquesea12345"})
        assert r.status == 401
    r = e.api("POST", "/v1/auth/login", json_={"identificador": "nadie@x.mx", "password": "loquesea12345"})
    assert r.status == 429
    assert r.body["error"]["codigo"] == "demasiadas_solicitudes"
    assert int(r.headers["retry-after"]) > 0
    # El límite es solo de esta ruta, las demás siguen respondiendo
    assert e.api("GET", "/v1/catalogos").status == 200
    limiter.reset()


def test_limite_por_ip_del_registro(e):
    """10 registros por IP cada hora."""
    limiter.reset()
    datos = {"nombre": "Equis", "username": "x_x", "correo": "x@x.mx", "password": "corta", "fechaNacimiento": "1990-01-01"}
    datos |= {"ciudadId": e.ciudad_id, "avisoPrivacidadId": e.aviso_id}
    for _ in range(10):
        assert e.api("POST", "/v1/auth/registro", json_=datos).status == 422
    assert e.api("POST", "/v1/auth/registro", json_=datos).status == 429
    limiter.reset()


# ---------------- Sesiones con refresh rotativo ----------------


def test_rotacion_invalida_el_access_anterior_y_el_reuso_revoca_la_familia(e):
    reg = e.registrar("rota")
    r1 = e.api("POST", "/v1/auth/refresh", json_={"refreshToken": reg["tokens"]["refreshToken"]})
    assert r1.status == 200
    assert e.api("GET", "/v1/yo", token=reg["tokens"]["accessToken"]).status == 401
    assert e.api("GET", "/v1/yo", token=r1.body["tokens"]["accessToken"]).status == 200
    # Un atacante reutiliza el refresh viejo
    robo = e.api("POST", "/v1/auth/refresh", json_={"refreshToken": reg["tokens"]["refreshToken"]})
    assert robo.status == 401
    # La sesión legítima también se cae, hay que volver a iniciar sesión
    assert e.api("GET", "/v1/yo", token=r1.body["tokens"]["accessToken"]).status == 401
    assert e.api("POST", "/v1/auth/refresh", json_={"refreshToken": r1.body["tokens"]["refreshToken"]}).status == 401


def test_token_manipulado_o_expirado(e):
    reg = e.registrar("manipula")
    t = reg["tokens"]["accessToken"]
    # Un carácter cambiado ya no corresponde a ningún hash guardado
    otro = t[:-1] + ("A" if t[-1] != "A" else "B")
    assert e.api("GET", "/v1/yo", token=otro).status == 401
    # Se simula que el token ya venció
    e.sql("UPDATE fqs.sesiones SET access_expira_en = now() - interval '1 second' WHERE usuario_id = %s", [reg["usuario"]["id"]])
    r = e.api("GET", "/v1/yo", token=t)
    assert r.status == 401
    assert r.body["error"]["codigo"] == "no_autenticado"


def test_logout_revoca_la_sesion(e):
    reg = e.registrar("salir")
    assert e.api("POST", "/v1/auth/logout", json_={"refreshToken": reg["tokens"]["refreshToken"]}).status == 204
    assert e.api("GET", "/v1/yo", token=reg["tokens"]["accessToken"]).status == 401


def test_en_la_base_solo_hay_hashes_de_tokens(e):
    reg = e.registrar("hash")
    r = e.sql(
        "SELECT count(*)::int AS n FROM fqs.sesiones WHERE access_hash = %s OR refresh_hash = %s",
        [reg["tokens"]["accessToken"], reg["tokens"]["accessToken"]],
    )
    assert r[0]["n"] == 0


def test_admin_sigue_con_su_contrasena(e):
    assert e.login("admin@fqs.mx", ADMIN_PASSWORD).status == 200
