"""Verificación de teléfono por SMS, panel web de administración y correo a acompañantes."""

import dataclasses
import http.client
import json
import re
import time
from urllib.parse import urlsplit

import httpx
import pytest

from fqs.http.cookies import cookies_sesion, nombres_cookies
from fqs.http_cliente import RespuestaHttp
from fqs.limites import limiter
from fqs.seguridad.contrasenas import hash_contrasena
from fqs.seguridad.qr import matriz_qr, svg_qr
from fqs.seguridad.totp import hotp, paso_actual
from fqs.sms import ControlSms, SmsBrevo
from utiles import en, mas, png_con_texto

from conftest import ADMIN_PASSWORD, PASSWORD, RAIZ


@pytest.fixture(autouse=True)
def limpiar(e):
    limiter.reset()
    e.servicios.limites.login_cuenta.reiniciar("cuenta admin@fqs.mx")


def base(e, sufijo: str, **extra) -> dict:
    return {
        "nombre": f"Familia {sufijo}",
        "username": f"fam_{sufijo}",
        "password": PASSWORD,
        "fechaNacimiento": "1988-04-12",
        "ciudadId": e.ciudad_id,
        "avisoPrivacidadId": e.aviso_id,
        **extra,
    }


# ---------------- Verificación de teléfono por SMS ----------------


def test_registro_solo_con_telefono_por_sms(e):
    r = e.api("POST", "/v1/auth/registro", json_=base(e, "sms1", telefono="81 5555 0101"))
    assert r.status == 202
    assert r.body["canal"] == "sms"
    assert r.body["destino"] == "•••• •• 0101"
    sms = e.sms.enviados[-1]
    assert sms.destino == "+528155550101"
    assert re.search(r"código de verificación es \d{8}", sms.texto)
    v = e.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r.body["registroId"], "codigo": e.ultimo_sms("+528155550101")})
    assert v.status == 201
    assert v.body["usuario"]["telefono"] == "+528155550101"
    u = e.sql("SELECT telefono_verificado_en FROM fqs.usuarios WHERE username = 'fam_sms1'")
    assert u[0]["telefono_verificado_en"]
    # Entra con cualquier forma de escribir el mismo número
    for ident in ["8155550101", "+52 81 5555 0101", "528155550101"]:
        assert e.login(ident).status == 200, ident
    # El mismo número escrito distinto ya cuenta como existente, no se manda otro SMS
    antes = len(e.sms.enviados)
    dup = e.api("POST", "/v1/auth/registro", json_=base(e, "sms1b", telefono="+528155550101"))
    assert dup.status == 202
    assert len(e.sms.enviados) == antes


def test_solo_numeros_de_mexico_y_sin_proveedor_no_hay_registro_por_telefono(e):
    extranjero = e.api("POST", "/v1/auth/registro", json_=base(e, "sms2", telefono="+12025550123"))
    assert extranjero.status == 422
    assert extranjero.body["error"]["codigo"] == "telefono_no_soportado"
    ambos = e.api("POST", "/v1/auth/registro", json_=base(e, "sms3", telefono="8155550102", correo="ambos@prueba.mx"))
    assert ambos.status == 400
    sin_proveedor = ControlSms(e.servicios.db, e.sms, e.servicios.config, False)
    with pytest.raises(Exception, match="Regístrate con un correo"):
        sin_proveedor.exigir_disponible("+528155550102")


def test_topes_de_sms_por_numero_y_por_dia(e):
    control = ControlSms(e.servicios.db, e.sms, e.servicios.config, True)
    numero = "+528155550199"
    for _ in range(5):
        assert e.correr(control.enviar_codigo(numero, "12345678", "verificacion")) is True
    assert e.correr(control.enviar_codigo(numero, "12345678", "verificacion")) is False, "el sexto del día no sale"
    e.pendientes()
    # Del número solo queda el hash
    filas = e.sql("SELECT destino_hash FROM fqs.sms_enviados")
    assert "8155550199" not in json.dumps(filas)
    # Tope global
    total = e.sql("SELECT count(*)::int AS n FROM fqs.sms_enviados WHERE creado_en > now() - interval '1 day'")[0]["n"]
    topeado = ControlSms(e.servicios.db, e.sms, dataclasses.replace(e.servicios.config, SMS_MAX_DIA=total), True)
    assert e.correr(topeado.enviar_codigo("+528155550198", "12345678", "verificacion")) is False
    # Un número de otro país nunca recibe nada
    assert e.correr(control.enviar_codigo("+12025550123", "12345678", "verificacion")) is False


def test_recuperacion_de_contrasena_por_sms(e):
    e.registrar("sms4", correo=None, telefono="8155550104")
    limiter.reset()
    r = e.api("POST", "/v1/auth/recuperar", json_={"identificador": "81 5555 0104"})
    assert r.status == 202
    sms = e.sms.enviados[-1]
    assert sms.destino == "+528155550104"
    assert re.search(r"cambiar la contraseña es \d{8}", sms.texto)
    codigo = re.search(r"\d{8}", sms.texto).group(0)  # type: ignore[union-attr]
    ok = e.api("POST", "/v1/auth/restablecer", json_={"identificador": "8155550104", "codigo": codigo, "password": "Nueva-Clave-Segura-1"})
    assert ok.status == 204
    assert e.login("8155550104", "Nueva-Clave-Segura-1").status == 200


def test_agregar_un_telefono_al_perfil_exige_verificarlo(e):
    fam = e.registrar("sms5")
    t = fam["tokens"]["accessToken"]
    p = e.api("PATCH", "/v1/yo", token=t, json_={"telefono": "8155550105", "passwordActual": PASSWORD})
    assert p.status == 200
    assert p.body["telefono"] is None, "no se aplica sin verificar"
    assert p.body["telefonoPendiente"] == "•••• •• 0105"
    assert e.api("POST", "/v1/yo/telefono/verificar", token=t, json_={"codigo": "00000000"}).status == 400
    v = e.api("POST", "/v1/yo/telefono/verificar", token=t, json_={"codigo": e.ultimo_sms("+528155550105")})
    assert v.status == 200
    assert v.body["telefono"] == "+528155550105"
    # Al correo verificado le llega el aviso del cambio
    assert any(x.tipo == "aviso" and x.destino == "sms5@prueba.mx" and x.asunto == "Cambiaste el teléfono de tu cuenta" for x in e.correo.enviados)
    # Otra cuenta no puede apartar ese número
    otra = e.registrar("sms6")
    antes = len(e.sms.enviados)
    e.api("PATCH", "/v1/yo", token=otra["tokens"]["accessToken"], json_={"telefono": "8155550105", "passwordActual": PASSWORD})
    assert len(e.sms.enviados) == antes, "a un número ocupado no se le manda SMS"


def test_sms_por_brevo(e):
    llamadas: list[dict] = []

    async def http(metodo, url, encabezados, cuerpo, tiempo):  # noqa: ANN001, ANN202
        llamadas.append({"url": url, "headers": encabezados, "cuerpo": cuerpo})
        return RespuestaHttp(201, '{"messageId":1511882900100020}')

    brevo = SmsBrevo("xkeysib-prueba", "FamSuman", http)
    e.correr(brevo.enviar("+528155550106", "Tu código es 12345678"))
    assert llamadas[0]["url"] == "https://api.brevo.com/v3/transactionalSMS/send"
    assert llamadas[0]["headers"]["api-key"] == "xkeysib-prueba"
    cuerpo = json.loads(llamadas[0]["cuerpo"])
    assert {k: cuerpo[k] for k in ("sender", "recipient", "type")} == {"sender": "FamSuman", "recipient": "528155550106", "type": "transactional"}


# ---------------- Panel web de administración ----------------


def siguiente_codigo(e) -> str:
    r = e.sql("SELECT ultimo_paso FROM fqs.usuarios_2fa WHERE usuario_id = %s", [e.admin_id])
    actual = paso_actual()
    ultimo = int(r[0]["ultimo_paso"] or 0)
    if ultimo + 1 > actual + 1:
        e.sql("UPDATE fqs.usuarios_2fa SET ultimo_paso = %s WHERE usuario_id = %s", [actual - 1, e.admin_id])
        return hotp(e.admin_secreto, actual)
    return hotp(e.admin_secreto, max(ultimo + 1, actual))


class RespPanel:
    def __init__(self, r: httpx.Response) -> None:
        self.status = r.status_code
        self.headers = r.headers
        self.set_cookie = r.headers.get_list("set-cookie")
        self.cookies: dict[str, str] = {}
        for c in self.set_cookie:
            par = c.split(";")[0]
            k, _, v = par.partition("=")
            self.cookies[k] = v
        self.body = r.json() if r.content and "json" in r.headers.get("content-type", "") else r.text


def panel(e, metodo: str, ruta: str, cookies: dict | None = None, json_=None, encabezado: bool = True, origen: str | None = None) -> RespPanel:
    """Petición como la haría el navegador del panel, con cookies y sin Bearer."""
    h: dict[str, str] = {}
    if encabezado:
        h["x-fqs-panel"] = "1"
    if origen:
        h["origin"] = origen
    if cookies:
        h["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    contenido = None
    if json_ is not None:
        h["content-type"] = "application/json"
        contenido = json.dumps(json_).encode()
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        r = c.request(metodo, e.base + ruta, headers=h, content=contenido)
    e.pendientes()
    return RespPanel(r)


def crudo(e, ruta: str, metodo: str = "GET") -> int:
    """Petición HTTP sin normalizar la ruta, para probar ../ y codificaciones raras."""
    u = urlsplit(e.base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    try:
        c.putrequest(metodo, ruta, skip_accept_encoding=True)
        c.endheaders()
        return c.getresponse().status
    finally:
        c.close()


def entrar_panel(e) -> RespPanel:
    p1 = panel(e, "POST", "/v1/panel/sesion", json_={"identificador": "admin@fqs.mx", "password": ADMIN_PASSWORD})
    assert p1.status == 200, p1.body
    p2 = panel(e, "POST", "/v1/panel/sesion/2fa", json_={"desafio": p1.body["desafio"], "codigo": siguiente_codigo(e)})
    assert p2.status == 200, p2.body
    return p2


def test_el_panel_se_sirve_con_csp_estricta_y_sin_salir_de_su_carpeta(e):
    r = panel(e, "GET", "/panel")
    assert r.status == 301
    assert r.headers.get("location") == "/panel/"
    i = panel(e, "GET", "/panel/")
    assert i.status == 200
    assert "text/html" in i.headers.get("content-type", "")
    csp = i.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert i.headers.get("x-frame-options") == "DENY"
    assert panel(e, "GET", "/panel/js/app.js").headers.get("content-type") == "text/javascript; charset=utf-8"
    assert crudo(e, "/panel/../pyproject.toml") == 404
    assert crudo(e, "/panel/%2e%2e/pyproject.toml") == 404
    assert crudo(e, "/panel/..%2f..%2ffqs/config.py") == 404
    assert crudo(e, "/panel/no-existe.js") == 404
    assert crudo(e, "/panel/", "POST") == 405


def test_el_codigo_del_panel_nunca_arma_html_con_texto(e):
    carpeta = RAIZ / "panel"
    js = [p for p in carpeta.rglob("*.js")]
    assert len(js) >= 5
    for a in js:
        t = a.read_text(encoding="utf-8")
        assert not re.search(r"\.innerHTML|\.outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function|setTimeout\(\s*['\"`]", t), a
        assert not re.search(r"localStorage|sessionStorage", t), f"{a} no guarda nada en el navegador"
    html = (carpeta / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "sin scripts en línea"
    assert not re.search(r"\son[a-z]+=|\sstyle=|<style", html, re.IGNORECASE), "sin manejadores ni estilos en línea"


def test_una_familia_no_puede_abrir_el_panel_y_el_inicio_exige_venir_del_panel(e):
    e.registrar("panel1")
    cuerpo = {"identificador": "panel1@prueba.mx", "password": PASSWORD}
    sin_encabezado = panel(e, "POST", "/v1/panel/sesion", encabezado=False, json_=cuerpo)
    assert sin_encabezado.status == 403
    assert sin_encabezado.body["error"]["codigo"] == "csrf"
    assert panel(e, "POST", "/v1/panel/sesion", origen="https://sitio-malo.example", json_=cuerpo).status == 403
    fam = panel(e, "POST", "/v1/panel/sesion", origen=e.base, json_=cuerpo)
    assert fam.status == 403
    assert fam.body["error"]["codigo"] == "solo_admin"
    assert len(fam.set_cookie) == 0
    ev = e.sql("SELECT 1 FROM fqs.bitacora_seguridad WHERE accion = 'acceso_denegado' AND ruta = 'POST /v1/panel/sesion'")
    assert len(ev) == 1
    # La contraseña equivocada sigue el mismo trato que en la app
    assert panel(e, "POST", "/v1/panel/sesion", json_={"identificador": "admin@fqs.mx", "password": "otra-cosa-123"}).status == 401


def test_sesion_del_panel_en_cookies_httponly_con_csrf_renovacion_y_salida(e):
    p1 = panel(e, "POST", "/v1/panel/sesion", json_={"identificador": "admin@fqs.mx", "password": ADMIN_PASSWORD})
    assert p1.body["requiere2fa"] is True
    assert len(p1.set_cookie) == 0, "sin código no hay cookies"
    p2 = panel(e, "POST", "/v1/panel/sesion/2fa", json_={"desafio": p1.body["desafio"], "codigo": siguiente_codigo(e)})
    assert p2.status == 200
    assert p2.body["sesionConSegundoFactor"] is True
    assert not re.search(r"fqs_at_|fqs_rt_", json.dumps(p2.body)), "los tokens no llegan al JavaScript"
    acceso = next(c for c in p2.set_cookie if c.startswith("fqs_panel="))
    renov = next(c for c in p2.set_cookie if c.startswith("fqs_panel_r="))
    assert "; Path=/; " in acceso
    assert "HttpOnly" in acceso
    assert "SameSite=Strict" in acceso
    assert "Path=/v1/panel/sesion;" in renov
    assert "HttpOnly" in renov
    cookies = p2.cookies

    yo = panel(e, "GET", "/v1/panel/sesion", cookies={"fqs_panel": cookies["fqs_panel"]})
    assert yo.status == 200
    assert yo.body["usuario"]["rol"] == "admin"
    assert panel(e, "GET", "/v1/admin/resumen", cookies=cookies, encabezado=False).status == 200, "leer no necesita el encabezado"

    # Cambiar algo con cookie exige el encabezado del panel y el mismo origen
    nivel = {"nombre": "Panel Nivel", "participacionesMinimas": 77}
    sin_enc = panel(e, "POST", "/v1/admin/niveles", cookies=cookies, encabezado=False, json_=nivel)
    assert sin_enc.status == 403
    assert sin_enc.body["error"]["codigo"] == "csrf"
    assert panel(e, "POST", "/v1/admin/niveles", cookies=cookies, origen="https://sitio-malo.example", json_=nivel).status == 403
    assert panel(e, "POST", "/v1/admin/niveles", cookies=cookies, origen="null", json_=nivel).status == 403
    assert len(e.sql("SELECT 1 FROM fqs.niveles WHERE nombre = 'Panel Nivel'")) == 0
    bien = panel(e, "POST", "/v1/admin/niveles", cookies=cookies, origen=e.base, json_=nivel)
    assert bien.status == 201, bien.body
    # La acción hecha desde el panel queda en la bitácora como cualquier otra
    ev = e.sql(
        "SELECT 1 FROM fqs.bitacora_seguridad WHERE accion = 'admin_accion' AND ruta = 'POST /v1/admin/niveles' AND actor_id = %s", [e.admin_id]
    )
    assert len(ev) >= 1

    # Renovación con rotación
    r = panel(e, "POST", "/v1/panel/sesion/renovar", cookies={"fqs_panel_r": cookies["fqs_panel_r"]})
    assert r.status == 204
    assert r.cookies["fqs_panel"] != cookies["fqs_panel"]
    assert panel(e, "GET", "/v1/panel/sesion", cookies={"fqs_panel": cookies["fqs_panel"]}).status == 401, "el acceso anterior ya no sirve"
    nueva = panel(e, "GET", "/v1/panel/sesion", cookies={"fqs_panel": r.cookies["fqs_panel"]})
    assert nueva.status == 200
    assert nueva.body["sesionConSegundoFactor"] is True, "la renovación conserva el segundo factor"
    assert panel(e, "POST", "/v1/panel/sesion/renovar", cookies={"fqs_panel_r": cookies["fqs_panel_r"]}, encabezado=False).status == 403

    # Salir revoca y borra las cookies
    s = panel(e, "POST", "/v1/panel/sesion/salir", cookies={"fqs_panel_r": r.cookies["fqs_panel_r"]})
    assert s.status == 204
    assert all("Max-Age=0" in c for c in s.set_cookie)
    assert panel(e, "GET", "/v1/panel/sesion", cookies={"fqs_panel": r.cookies["fqs_panel"]}).status == 401
    reuso = panel(e, "POST", "/v1/panel/sesion/renovar", cookies={"fqs_panel_r": r.cookies["fqs_panel_r"]})
    assert reuso.status == 401
    assert reuso.set_cookie and all("Max-Age=0" in c for c in reuso.set_cookie), "si la sesión ya no sirve se borran las cookies"


def test_en_produccion_las_cookies_llevan_prefijos():
    n = nombres_cookies(True)
    t = {"accessToken": "fqs_at_x", "refreshToken": "fqs_rt_y", "accessExpiraEn": en(minutes=1), "refreshExpiraEn": en(minutes=10)}
    a, r = cookies_sesion(n, t)
    assert re.match(r"^__Host-fqs_panel=fqs_at_x; Path=/; Max-Age=\d+; HttpOnly; SameSite=Strict; Secure$", a)
    assert re.match(r"^__Secure-fqs_panel_r=fqs_rt_y; Path=/v1/panel/sesion; Max-Age=\d+; HttpOnly; SameSite=Strict; Secure$", r)
    assert "domain=" not in a.lower()


def test_el_qr_del_segundo_factor_se_dibuja_en_el_servidor(e):
    m = matriz_qr("otpauth://totp/Familias%20que%20Suman:admin%40fqs.mx?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Familias%20que%20Suman")
    assert (len(m) - 17) % 4 == 0
    # Los tres patrones de esquina, borde oscuro de 7 y centro de 3
    for x, y in [(0, 0), (len(m) - 7, 0), (0, len(m) - 7)]:
        for i in range(7):
            assert m[y][x + i] and m[y + 6][x + i] and m[y + i][x] and m[y + i][x + 6]
            assert i in (0, 6) or not m[y + 1][x + i]
        assert m[y + 3][x + 3]
    svg = svg_qr("hola")
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert not re.search(r"<script|on[a-z]+=", svg, re.IGNORECASE)

    # Una cuenta nueva de administración recibe el QR al iniciar la activación
    h = e.correr(hash_contrasena(ADMIN_PASSWORD))
    n = e.sql(
        """INSERT INTO fqs.usuarios (nombre, username, correo, password_hash, rol, correo_verificado_en)
           VALUES ('Admin Panel', 'admin_panel', 'admin.panel@fqs.mx', %s, 'admin', now()) RETURNING id""",
        [h],
    )
    lo = e.login("admin.panel@fqs.mx", ADMIN_PASSWORD)
    ini = e.api("POST", "/v1/admin/2fa/iniciar", token=lo.body["tokens"]["accessToken"], json_={"password": ADMIN_PASSWORD})
    assert ini.status == 200
    assert ini.body["qrSvg"].startswith("<svg")
    assert ini.body["qrSvg"] == svg_qr(ini.body["uri"])
    # Sin segundo factor en obligatorio, el panel solo deja ver su sesión y activarlo
    cookie = {"fqs_panel": lo.body["tokens"]["accessToken"]}
    assert panel(e, "GET", "/v1/panel/sesion", cookies=cookie).status == 200
    assert panel(e, "GET", "/v1/admin/resumen", cookies=cookie).status == 403
    e.sql("UPDATE fqs.usuarios SET estado = 'suspendido' WHERE id = %s", [n[0]["id"]])


def test_listados_del_panel_solo_para_administracion_y_sin_datos_de_acceso(e):
    t = entrar_panel(e).cookies
    fam = e.registrar("panel2")
    assert e.api("GET", "/v1/admin/usuarios", token=fam["tokens"]["accessToken"]).status == 403
    u = panel(e, "GET", "/v1/admin/usuarios?q=panel2", cookies=t)
    assert u.status == 200
    assert len(u.body) == 1
    assert u.body[0]["correo"] == "panel2@prueba.mx"
    assert not re.search(r"password|hash|scrypt", json.dumps(u.body), re.IGNORECASE)
    assert len(panel(e, "GET", "/v1/admin/usuarios?q=%25", cookies=t).body) == 0, "el % se busca como texto"
    assert panel(e, "GET", "/v1/admin/usuarios?rol=superadmin", cookies=t).status == 400
    assert panel(e, "GET", "/v1/admin/actividades?estado=borrado", cookies=t).status == 400
    res = panel(e, "GET", "/v1/admin/resumen", cookies=t)
    assert isinstance(res.body["familiasActivas"], int)
    assert isinstance(res.body["proximas"], list)
    aso = panel(e, "GET", "/v1/admin/asociaciones?limite=50", cookies=t)
    assert len(aso.body) >= 1
    ficha = panel(e, "GET", f"/v1/admin/asociaciones/{aso.body[0]['id']}", cookies=t)
    assert ficha.status == 200
    assert "verificada" in ficha.body and "categoriaId" in ficha.body
    for ruta in ["/v1/admin/proyectos", "/v1/admin/campanas", "/v1/admin/niveles", "/v1/admin/insignias", "/v1/admin/avisos-privacidad"]:
        assert panel(e, "GET", ruta, cookies=t).status == 200, ruta


# ---------------- Correo a acompañantes ----------------


def test_acompanantes_adultos_con_correo_reciben_confirmacion_y_cancelacion(e):
    fam = e.registrar("acomp1")
    tf = fam["tokens"]["accessToken"]
    tope = e.servicios.limites.correos_acompanantes
    clave = f"acompanantes {fam['usuario']['id']}"
    tope.reiniciar(clave)

    def nuevo(**datos) -> str:
        return e.api("POST", "/v1/yo/comunidad", token=tf, json_=datos).body["id"]

    laura = nuevo(nombre="Laura Adulta", relacion="Hermana", fechaNacimiento="1990-05-05", correo="laura@prueba.mx")
    tito = nuevo(nombre="Tito Menor", relacion="Hijo", fechaNacimiento="2015-05-05", correo="tito@prueba.mx")
    sin_correo = nuevo(nombre="Pepe Sin Correo", relacion="Tío", fechaNacimiento="1970-01-01")
    mismo = nuevo(nombre="Mismo Correo", relacion="Pareja", fechaNacimiento="1985-01-01", correo="acomp1@prueba.mx")

    aso = e.api(
        "POST",
        "/v1/admin/asociaciones",
        token=e.admin,
        json_={
            "nombre": "Huerto Común",
            "descripcion": "Huertos urbanos comunitarios",
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "direccion": "Calle Morelos 100, Centro",
            "verificada": True,
        },
    )
    assert aso.status == 201, aso.body
    inicio = en(days=6)
    act = e.api(
        "POST",
        "/v1/admin/actividades",
        token=e.admin,
        json_={
            "asociacionId": aso.body["id"],
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "titulo": "Siembra de otoño",
            "descripcionCorta": "Sembramos",
            "descripcion": "Siembra de hortalizas de temporada",
            "inicio": inicio,
            "fin": mas(inicio, hours=2),
            "direccion": "Huerto Morelos, Centro",
            "cupoTotal": 10,
            "aptaNinos": True,
        },
    )
    e.api("POST", f"/v1/admin/actividades/{act.body['id']}/estado", token=e.admin, json_={"estado": "publicada"})
    antes = len(e.correo.enviados)
    ins = e.api("POST", f"/v1/actividades/{act.body['id']}/inscripcion", token=tf, json_={"titularAsiste": True, "miembros": [laura, tito, sin_correo, mismo]})
    assert ins.status == 201, ins.body

    def nuevos() -> list:
        return [x for x in e.correo.enviados[antes:] if x.tipo == "aviso"]

    assert [x.destino for x in nuevos()] == ["laura@prueba.mx"], "ni menores, ni sin correo, ni el correo del titular"
    c = nuevos()[0]
    assert c.asunto == "Te inscribieron a Siembra de otoño"
    assert "Familia acomp1 te inscribió" in c.texto
    assert "Huerto Morelos, Centro" in c.texto
    assert "Huerto Común" in c.texto
    assert "acomp1@prueba.mx" not in c.texto, "no se comparte el contacto de quien inscribe"

    can = e.api("POST", f"/v1/admin/actividades/{act.body['id']}/cancelar", token=e.admin, json_={"motivo": "Helada pronosticada"})
    assert can.body["acompanantesAvisados"] == 1
    aviso = next(x for x in nuevos() if x.asunto == "Se canceló Siembra de otoño")
    assert aviso.destino == "laura@prueba.mx"
    assert "Helada pronosticada" in aviso.texto

    # Tope diario por titular, el correo del acompañante no está verificado
    while not tope.bloqueado(clave):
        try:
            tope.consumir(clave)
        except Exception:  # noqa: BLE001
            break
    act2 = e.api(
        "POST",
        "/v1/admin/actividades",
        token=e.admin,
        json_={
            "asociacionId": aso.body["id"],
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "titulo": "Cosecha",
            "descripcionCorta": "Cosechamos",
            "descripcion": "Cosecha de hortalizas",
            "inicio": inicio,
            "fin": mas(inicio, hours=2),
            "direccion": "Huerto Morelos, Centro",
            "cupoTotal": 10,
        },
    )
    e.api("POST", f"/v1/admin/actividades/{act2.body['id']}/estado", token=e.admin, json_={"estado": "publicada"})
    n = len(nuevos())
    assert e.api("POST", f"/v1/actividades/{act2.body['id']}/inscripcion", token=tf, json_={"titularAsiste": True, "miembros": [laura]}).status == 201
    time.sleep(0.2)
    e.pendientes()
    assert len(nuevos()) == n, "con el tope alcanzado ya no se manda"
    tope.reiniciar(clave)


def test_las_fotos_oficiales_pueden_ser_de_cualquier_admin_nunca_de_una_familia(e):
    fam = e.registrar("foto1")
    de_familia = e.api("POST", "/v1/archivos", token=fam["tokens"]["accessToken"], crudo=png_con_texto(), tipo="image/png")
    assert de_familia.status == 201
    datos = {
        "nombre": "Foto Oficial",
        "descripcion": "Asociación para probar fotos",
        "categoriaId": e.cat_medio,
        "ciudadId": e.ciudad_id,
        "direccion": "Calle Hidalgo 1, Centro",
        "verificada": True,
    }
    assert e.api("POST", "/v1/admin/asociaciones", token=e.admin, json_={**datos, "fotoClave": de_familia.body["clave"]}).status == 422
    # Foto subida por otra cuenta de administración
    otro = e.sql("SELECT id FROM fqs.usuarios WHERE username = 'admin_panel'")
    f = e.sql(
        "INSERT INTO fqs.archivos (usuario_id, tipo_mime, tamano, sha256) VALUES (%s, 'image/png', 10, repeat('a', 64)) RETURNING id", [otro[0]["id"]]
    )
    bien = e.api("POST", "/v1/admin/asociaciones", token=e.admin, json_={**datos, "fotoClave": str(f[0]["id"])})
    assert bien.status == 201, bien.body
