"""
Casos maliciosos o no permitidos que la API debe rechazar (rúbrica, parte 2.3).

Cada prueba documenta un tipo de ataque y la respuesta esperada. Varias ya aparecen dentro de
los flujos de las otras pruebas, aquí se juntan para que sirvan de evidencia directa.
"""

import pytest

from fqs.limites import limiter

from conftest import PASSWORD

F: dict = {}

INYECCIONES = ["' OR '1'='1", "admin@fqs.mx' --", "1; DROP TABLE fqs.usuarios; --", "' UNION SELECT password_hash FROM fqs.usuarios --"]


@pytest.fixture(scope="module", autouse=True)
def cuentas(e):
    e.reiniciar_limites()
    F["a"] = e.registrar("rechazoa")
    F["b"] = e.registrar("rechazob")


def _t(c: str) -> str:
    return F[c]["tokens"]["accessToken"]


# ---------------- Inyección SQL ----------------


@pytest.mark.parametrize("ataque", INYECCIONES)
def test_inyeccion_sql_en_el_inicio_de_sesion(e, ataque):
    limiter.reset()
    r = e.api("POST", "/v1/auth/login", json_={"identificador": ataque, "password": ataque})
    assert r.status in (400, 401)
    assert "tokens" not in (r.body if isinstance(r.body, dict) else {})


@pytest.mark.parametrize("ataque", INYECCIONES)
def test_inyeccion_sql_en_busquedas_y_filtros(e, ataque):
    from urllib.parse import quote

    r = e.api("GET", f"/v1/asociaciones?q={quote(ataque)}", token=_t("a"))
    assert r.status == 200
    assert r.body == []
    # En un filtro con valores fijos o un UUID, el valor ni siquiera llega a la base
    assert e.api("GET", f"/v1/actividades?tipo={quote(ataque)}", token=_t("a")).status == 400
    assert e.api("GET", f"/v1/actividades?ciudadId={quote(ataque)}", token=_t("a")).status == 400


def test_inyeccion_sql_en_la_ruta(e):
    for ruta in ["/v1/actividades/1%20OR%201=1", "/v1/propuestas/'%3B%20DROP%20TABLE%20fqs.propuestas%3B--"]:
        assert e.api("GET", ruta, token=_t("a")).status == 404


def test_la_base_sigue_intacta_despues_de_los_intentos(e):
    n = e.sql("SELECT count(*)::int AS n FROM fqs.usuarios")
    assert n[0]["n"] > 2


def test_tipos_equivocados_no_se_convierten(e):
    """Un número como texto o un texto como número se rechaza, no se intenta adivinar."""
    r = e.api(
        "POST",
        "/v1/yo/comunidad",
        token=_t("a"),
        json_={"nombre": "Ana", "relacion": "Hija", "fechaNacimiento": "2016-10-20", "esMenor": "1; DROP TABLE x"},
    )
    assert r.status == 400
    r2 = e.api("PUT", "/v1/yo/preferencias", token=_t("a"), json_={"quiereDonar": "true", "quiereParticipar": True, "quiereProponer": False, "recibirRecordatorios": True, "recibirSugerencias": True, "categorias": []})
    assert r2.status == 400


# ---------------- Tokens expirados, manipulados o inventados ----------------


def test_token_inventado_manipulado_o_con_inyeccion(e):
    t = _t("a")
    for falso in ["fqs_at_" + "A" * 43, t[:-2] + "zz", t + "x", "' OR 1=1 --", "Bearer", ""]:
        assert e.api("GET", "/v1/yo", token=falso or None).status == 401


def test_token_expirado(e):
    reg = e.registrar("rechazoexp")
    e.sql("UPDATE fqs.sesiones SET access_expira_en = now() - interval '1 second' WHERE usuario_id = %s", [reg["usuario"]["id"]])
    r = e.api("GET", "/v1/yo", token=reg["tokens"]["accessToken"])
    assert r.status == 401
    assert r.body["error"]["codigo"] == "no_autenticado"


def test_refresh_reutilizado_cierra_toda_la_sesion(e):
    reg = e.registrar("rechazorot")
    nuevo = e.api("POST", "/v1/auth/refresh", json_={"refreshToken": reg["tokens"]["refreshToken"]})
    assert nuevo.status == 200
    assert e.api("POST", "/v1/auth/refresh", json_={"refreshToken": reg["tokens"]["refreshToken"]}).status == 401
    assert e.api("GET", "/v1/yo", token=nuevo.body["tokens"]["accessToken"]).status == 401


# ---------------- Datos de otra persona (IDOR) ----------------


def test_no_se_puede_ver_ni_cambiar_datos_de_otra_familia(e):
    a, b = _t("a"), _t("b")
    m = e.api("POST", "/v1/yo/comunidad", token=a, json_={"nombre": "Sofía", "relacion": "Hija", "fechaNacimiento": "2014-02-02"})
    assert m.status == 201
    p = e.api("POST", "/v1/propuestas", token=a, json_={"tipo": "iniciativa_vecinal", "titulo": "Banca nueva", "descripcion": "Una banca para el parque de la colonia"})
    assert p.status == 201
    sesiones = e.api("GET", "/v1/yo/sesiones", token=a).body
    # La otra familia recibe 404, igual que si no existiera
    assert e.api("PUT", f"/v1/yo/comunidad/{m.body['id']}", token=b, json_={"nombre": "Robada", "relacion": "Hija", "fechaNacimiento": "2014-02-02"}).status == 404
    assert e.api("GET", f"/v1/propuestas/{p.body['id']}", token=b).status == 404
    # Editar la propuesta ajena responde lo mismo que una propuesta que no existe
    ajena = e.api("PUT", f"/v1/propuestas/{p.body['id']}", token=b, json_={"tipo": "iniciativa_vecinal", "titulo": "Otra", "descripcion": "Cambio de otra persona"})
    assert ajena.status == 409
    assert ajena.body["error"]["mensaje"].startswith("La propuesta no existe")
    assert e.api("GET", f"/v1/propuestas/{p.body['id']}", token=a).body["titulo"] == "Banca nueva"
    assert e.api("DELETE", f"/v1/yo/sesiones/{sesiones[0]['id']}", token=b).status == 404
    # Y lo de la dueña sigue igual
    assert e.api("GET", "/v1/yo/comunidad", token=a).body[0]["nombre"] == "Sofía"
    assert e.api("GET", "/v1/yo", token=a).status == 200


def test_campos_privilegiados_no_se_pueden_mandar(e):
    """Asignación masiva, el rol o el estado no se cambian aunque vengan en el cuerpo."""
    for extra in ({"rol": "admin"}, {"estado": "activo"}, {"id": F["b"]["usuario"]["id"]}):
        r = e.api("PATCH", "/v1/yo", token=_t("a"), json_={"nombre": "Familia rechazoa", **extra})
        assert r.status == 400
    assert e.api("GET", "/v1/yo", token=_t("a")).body["rol"] == "familia"


def test_una_familia_no_usa_la_administracion(e):
    for metodo, ruta in [("GET", "/v1/admin/usuarios"), ("GET", "/v1/admin/bitacora"), ("PUT", f"/v1/admin/usuarios/{F['b']['usuario']['id']}/estado")]:
        r = e.api(metodo, ruta, token=_t("a"), json_={"estado": "suspendido"} if metodo == "PUT" else None)
        assert r.status == 403
    assert e.api("GET", "/v1/yo", token=_t("b")).status == 200


# ---------------- Bloqueo por exceso de peticiones ----------------


def test_bloqueo_por_exceso_en_el_inicio_de_sesion(e):
    limiter.reset()
    estados = [e.api("POST", "/v1/auth/login", json_={"identificador": f"x{i}@x.mx", "password": "nada-123456"}).status for i in range(21)]
    assert estados[:20] == [401] * 20
    assert estados[20] == 429
    limiter.reset()


def test_bloqueo_de_la_cuenta_aunque_cambie_la_ip(e):
    """5 contraseñas equivocadas bloquean la cuenta 15 minutos, sin importar de dónde vengan."""
    limiter.reset()
    for _ in range(5):
        assert e.api("POST", "/v1/auth/login", json_={"identificador": "rechazob@prueba.mx", "password": "equivocada-1"}).status == 401
        limiter.reset()  # como si cada intento llegara de otra IP
    r = e.api("POST", "/v1/auth/login", json_={"identificador": "rechazob@prueba.mx", "password": PASSWORD})
    assert r.status == 429
    assert r.body["error"]["codigo"] == "cuenta_bloqueada"
    e.servicios.limites.login_cuenta.reiniciar("cuenta rechazob@prueba.mx")


def test_bloqueo_por_exceso_en_el_registro(e):
    limiter.reset()
    datos = {"nombre": "Equis", "username": "equis", "correo": "e@x.mx", "password": "corta", "fechaNacimiento": "1990-01-01"}
    datos |= {"ciudadId": e.ciudad_id, "avisoPrivacidadId": e.aviso_id}
    estados = [e.api("POST", "/v1/auth/registro", json_=datos).status for _ in range(11)]
    assert estados[:10] == [422] * 10
    assert estados[10] == 429
    limiter.reset()


def test_no_hay_limite_global(e):
    """Muchas lecturas seguidas no se bloquean, los límites solo están en las rutas sensibles."""
    limiter.reset()
    for _ in range(120):
        assert e.api("GET", "/v1/catalogos").status == 200


def test_caracter_nulo_en_cuerpo_y_consulta(e):
    """Hallazgo del escaneo con ZAP, un texto con el carácter nulo provocaba un 500."""
    r = e.api("POST", "/v1/admin/ciudades", token=e.admin, json_={"nombre": "Ciudad\u0000", "estado": "Estado", "zonaHoraria": "America/Monterrey"})
    assert r.status == 400
    assert r.body["error"]["detalles"][0]["campo"] == "nombre"
    r2 = e.api("DELETE", "/v1/yo/dispositivos", token=_t("a"), json_={"tokenFcm": "token-" + "\u0000" * 30})
    assert r2.status == 400
    assert e.api("GET", "/v1/asociaciones?q=raices%00", token=_t("a")).status == 400


def test_diagonal_final_no_redirige(e):
    r = e.api("GET", "/v1/catalogos/")
    assert r.status == 404
    assert "location" not in r.headers
