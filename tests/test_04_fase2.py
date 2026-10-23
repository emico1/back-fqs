"""Fase 2. Avisos, favoritos, encuestas, calidad, propuestas, testimonios y push."""

import base64
import json
import os
from urllib.parse import parse_qs

import psycopg
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from fqs.http_cliente import RespuestaHttp
from fqs.push import Push
from utiles import en, mas

F: dict = {}


def _publicar(e, horas: float = 96, **datos) -> str:
    inicio = en(hours=horas)
    r = e.api(
        "POST",
        "/v1/admin/actividades",
        token=e.admin,
        json_={
            "asociacionId": F["aso"],
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "titulo": "Actividad fase 2",
            "descripcionCorta": "Breve descripción",
            "descripcion": "Descripción completa de la actividad",
            "inicio": inicio,
            "fin": mas(inicio, hours=2),
            "direccion": "Calle Hidalgo 300",
            "cupoTotal": 10,
            **datos,
        },
    )
    assert r.status == 201, r.body
    e.api("POST", f"/v1/admin/actividades/{r.body['id']}/estado", token=e.admin, json_={"estado": "publicada"})
    return r.body["id"]


def _notis(e, t: str) -> list:
    return e.api("GET", "/v1/notificaciones", token=t).body


def _t(clave: str) -> str:
    return F[clave]["tokens"]["accessToken"]


PREFERENCIAS = {"quiereDonar": False, "quiereParticipar": True, "quiereProponer": False, "categorias": ["MEDIO_AMBIENTE"]}


@pytest.fixture(scope="module", autouse=True)
def preparar(e):
    e.reiniciar_limites()
    a = e.api(
        "POST",
        "/v1/admin/asociaciones",
        token=e.admin,
        json_={
            "nombre": "Bosque Urbano A.C.",
            "descripcion": "Cuidado de parques y bosques urbanos",
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "direccion": "Parque Rufino Tamayo",
            "verificada": True,
        },
    )
    F["aso"] = a.body["id"]
    c = e.api("POST", "/v1/admin/ciudades", token=e.admin, json_={"nombre": "Torreón", "estado": "Coahuila", "zonaHoraria": "America/Monterrey"})
    F["ciudad_lejos"] = c.body["id"]
    # registrar() deja MEDIO_AMBIENTE como interés, la categoría de las actividades de prueba
    F["fav"] = e.registrar("fase2fav")
    F["sug"] = e.registrar("fase2sug")
    F["lejos"] = e.registrar("fase2lejos", ciudadId=F["ciudad_lejos"])
    e.api("PUT", f"/v1/asociaciones/{F['aso']}/favorito", token=_t("fav"), json_={"notificacionesActivas": True})
    # Las sugerencias son una al día, se limpian las que dejaron las pruebas anteriores
    e.sql("DELETE FROM fqs.notificaciones WHERE tipo = 'sugerencia'")


def test_publicar_avisa_a_favoritos_y_sugiere_a_interesados(e):
    act = _publicar(e, titulo="Siembra en el Rufino Tamayo")
    fav = [n for n in _notis(e, _t("fav")) if n["actividadId"] == act]
    assert [n["tipo"] for n in fav] == ["nueva_actividad"], "el favorito no recibe además la sugerencia"
    assert "Bosque Urbano A.C. publicó una actividad" in fav[0]["titulo"]
    sug = [n for n in _notis(e, _t("sug")) if n["actividadId"] == act]
    assert [n["tipo"] for n in sug] == ["sugerencia"]
    assert not [n for n in _notis(e, _t("lejos")) if n["actividadId"] == act]
    # Una segunda actividad el mismo día no genera otra sugerencia
    otra = _publicar(e, titulo="Riego de árboles")
    assert not [n for n in _notis(e, _t("sug")) if n["actividadId"] == otra]
    assert len([n for n in _notis(e, _t("fav")) if n["actividadId"] == otra]) == 1


def test_sin_aceptar_sugerencias_no_llegan(e):
    g = e.api(
        "PUT", "/v1/yo/preferencias", token=_t("sug"), json_={**PREFERENCIAS, "recibirRecordatorios": True, "recibirSugerencias": False}
    )
    assert g.status == 200
    e.sql("DELETE FROM fqs.notificaciones WHERE tipo = 'sugerencia'")
    act = _publicar(e, titulo="Sin sugerencias")
    assert not [n for n in _notis(e, _t("sug")) if n["actividadId"] == act]


def test_favoritos_de_actividades_y_lista_de_favoritos(e):
    t = _t("fav")
    act = _publicar(e, titulo="Favorita")
    assert e.api("PUT", f"/v1/actividades/{act}/favorito", token=t).status == 200
    assert e.api("GET", f"/v1/actividades/{act}", token=t).body["esFavorita"] is True
    f = e.api("GET", "/v1/yo/favoritos", token=t)
    assert any(a["id"] == F["aso"] and a["notificacionesActivas"] for a in f.body["asociaciones"])
    assert any(a["id"] == act for a in f.body["actividades"])
    # Otra ciudad no puede marcar algo que no ve
    assert e.api("PUT", f"/v1/actividades/{act}/favorito", token=_t("lejos")).status == 404
    assert e.api("DELETE", f"/v1/actividades/{act}/favorito", token=t).status == 204
    assert not any(a["id"] == act for a in e.api("GET", "/v1/yo/favoritos", token=t).body["actividades"])


def test_recordatorio_un_dia_antes_una_vez_y_respetando_la_preferencia(e):
    act = _publicar(e, horas=12, titulo="Mañana temprano")
    t_fav, t_sug = _t("fav"), _t("sug")
    e.api("POST", f"/v1/actividades/{act}/inscripcion", token=t_fav, json_={"titularAsiste": True})
    e.api("POST", f"/v1/actividades/{act}/inscripcion", token=t_sug, json_={"titularAsiste": True})
    e.api("PUT", "/v1/yo/preferencias", token=t_fav, json_={**PREFERENCIAS, "recibirRecordatorios": False, "recibirSugerencias": True})
    e.sql("SELECT fqs.generar_avisos()")
    e.sql("SELECT fqs.generar_avisos()")
    rec = [n for n in _notis(e, t_sug) if n["tipo"] == "recordatorio" and n["actividadId"] == act]
    assert len(rec) == 1
    assert "Mañana temprano empieza el" in rec[0]["mensaje"]
    assert not [n for n in _notis(e, t_fav) if n["tipo"] == "recordatorio" and n["actividadId"] == act]


def test_encuesta_valoracion_sin_asistir_y_resultados(e):
    t = _t("sug")
    act = _publicar(e, titulo="Con encuesta")
    ins = e.api("POST", f"/v1/actividades/{act}/inscripcion", token=t, json_={"titularAsiste": True})
    iid = ins.body["inscripcionId"]
    # Validación cruzada de cada pregunta
    mala = e.api(
        "POST",
        "/v1/admin/encuestas",
        token=e.admin,
        json_={"actividadId": act, "titulo": "Mal armada", "momento": "despues", "preguntas": [{"texto": "¿Sí o no?", "tipo": "opcion_unica", "opciones": ["Sí"]}]},
    )
    assert mala.status == 400
    assert mala.body["error"]["detalles"][0]["campo"] == "preguntas.0"
    enc = e.api(
        "POST",
        "/v1/admin/encuestas",
        token=e.admin,
        json_={
            "actividadId": act,
            "titulo": "Después de la actividad",
            "momento": "despues",
            "preguntas": [
                {"texto": "¿Volverías a participar?", "tipo": "opcion_unica", "opciones": ["Sí", "No"]},
                {"texto": "¿Qué podemos mejorar?", "tipo": "texto", "obligatoria": False},
            ],
        },
    )
    assert enc.status == 201, enc.body
    encuesta = e.api("GET", f"/v1/actividades/{act}/encuestas", token=t).body[0]
    p1, p2 = encuesta["preguntas"]
    respuestas = {"respuestas": [{"preguntaId": p1["id"], "opcionId": p1["opciones"][0]["id"]}, {"preguntaId": p2["id"], "texto": "Más sombra"}]}
    # Sin asistencia no se puede evaluar
    assert e.api("POST", f"/v1/yo/inscripciones/{iid}/respuestas", token=t, json_=respuestas).status == 409
    voto = e.api("PUT", f"/v1/yo/inscripciones/{iid}/valoracion", token=t, json_={"valor": 1})
    assert voto.status == 409
    assert voto.body["error"]["mensaje"] == "Se requiere una participación con asistencia confirmada"
    # La actividad ocurre y el admin registra asistencia
    e.sql("UPDATE fqs.actividades SET inicio = now() - interval '3 hours', fin = now() - interval '1 hour' WHERE id = %s", [act])
    partes = e.api("GET", f"/v1/admin/actividades/{act}/participantes", token=e.admin)
    e.api("PUT", f"/v1/admin/participantes/{partes.body[0]['id']}/asistencia", token=e.admin, json_={"estado": "asistio"})
    e.sql("SELECT fqs.generar_avisos()")
    assert any(n["tipo"] == "encuesta" and n["actividadId"] == act for n in _notis(e, t))
    assert e.api("POST", f"/v1/yo/inscripciones/{iid}/respuestas", token=t, json_=respuestas).status == 204
    assert e.api("PUT", f"/v1/yo/inscripciones/{iid}/valoracion", token=t, json_={"valor": 1}).status == 204
    lista = e.api("GET", f"/v1/admin/actividades/{act}/encuestas", token=e.admin)
    assert lista.body[0]["respondieron"] == 1
    res = e.api("GET", f"/v1/admin/encuestas/{enc.body['id']}/resultados", token=e.admin)
    assert res.body["preguntas"][0]["opciones"][0]["total"] == 1
    assert res.body["preguntas"][1]["textos"] == ["Más sombra"]
    assert "fase2sug" not in json.dumps(res.body), "los resultados no llevan nombres"
    # Calidad visible en la asociación y en el reporte del admin
    assert e.api("GET", f"/v1/asociaciones/{F['aso']}", token=t).body["meGusta"] == 1
    cal = e.api("GET", "/v1/admin/calidad", token=e.admin)
    fila = next(x for x in cal.body if x["id"] == F["aso"])
    assert fila["calidad"] == 0.667
    assert e.api("DELETE", f"/v1/yo/inscripciones/{iid}/valoracion", token=t).status == 204
    assert e.api("GET", f"/v1/asociaciones/{F['aso']}", token=t).body["meGusta"] == 0


def test_proponer_una_asociacion_que_ya_existe(e):
    t = _t("sug")
    r = e.api("POST", "/v1/propuestas", token=t, json_={"tipo": "asociacion", "titulo": "bosque urbano", "descripcion": "Quiero registrar esta asociación de mi colonia"})
    assert r.status == 409
    assert r.body["error"]["codigo"] == "asociacion_existente"
    assert r.body["error"]["detalles"]["asociacionId"] == F["aso"]
    # Desde otra ciudad sí se puede proponer una con el mismo nombre
    lejos = e.api("POST", "/v1/propuestas", token=_t("lejos"), json_={"tipo": "asociacion", "titulo": "Bosque Urbano", "descripcion": "Una asociación nueva en Torreón"})
    assert lejos.status == 201
    otra = e.api("POST", "/v1/propuestas", token=t, json_={"tipo": "iniciativa_vecinal", "titulo": "Huerto en la plaza", "descripcion": "Un huerto comunitario en la plaza"})
    assert otra.status == 201
    repetida = e.api(
        "POST", "/v1/propuestas", token=t, json_={"tipo": "iniciativa_vecinal", "titulo": "HUERTO en la Plaza!", "descripcion": "Un huerto comunitario en la plaza"}
    )
    assert repetida.status == 409
    assert repetida.body["error"]["codigo"] == "propuesta_duplicada"


def test_limite_de_escrituras_por_cuenta(e):
    """30 escrituras por hora por cuenta (propuestas, reportes, entregas, testimonios, respuestas)."""
    from fqs.limites import limiter

    limiter.reset()
    t = _t("lejos")
    estados = []
    for i in range(31):
        r = e.api("POST", "/v1/reportes", token=t, json_={"tipo": "otro", "descripcion": f"Reporte de prueba número {i}"})
        estados.append(r.status)
    assert estados[:30] == [estados[0]] * 30 and estados[0] in (201, 422)
    assert estados[30] == 429
    # Otra cuenta desde la misma IP no se ve afectada, el límite es por cuenta
    assert e.api("POST", "/v1/reportes", token=_t("sug"), json_={"tipo": "otro", "descripcion": "Reporte de otra cuenta"}).status != 429
    limiter.reset()


def test_historias_de_la_comunidad_solo_aprobadas_y_de_la_misma_ciudad(e):
    lista = e.api("GET", "/v1/testimonios", token=_t("sug"))
    assert lista.status == 200
    assert len(lista.body) >= 1
    assert all(x["texto"] and x["actividad"]["titulo"] for x in lista.body)
    assert len(e.api("GET", "/v1/testimonios", token=_t("lejos")).body) == 0


def test_push_con_firebase_jwt_firmado_token_borrado_y_sin_envios_dobles(e):
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    llamadas: list[dict] = []
    respuesta_fcm = {"status": 200, "texto": '{"name":"projects/p/messages/1"}'}

    async def http(metodo, url, encabezados, cuerpo, tiempo):  # noqa: ANN001, ANN202
        llamadas.append({"url": url, "headers": encabezados, "cuerpo": cuerpo})
        if url.startswith("https://oauth2.googleapis.com/token"):
            return RespuestaHttp(200, json.dumps({"access_token": "ya29.prueba", "expires_in": 3600}))
        return RespuestaHttp(respuesta_fcm["status"], respuesta_fcm["texto"])

    push = Push(
        e.servicios.db,
        {"project_id": "fqs-prueba", "client_email": "push@fqs-prueba.iam.gserviceaccount.com", "private_key": pem},
        http,
    )
    t = _t("fav")
    token_tel = "token-fcm-de-prueba-" + "x" * 40
    assert e.api("PUT", "/v1/yo/dispositivos", token=t, json_={"tokenFcm": token_tel}).status == 204

    n = e.sql(
        "INSERT INTO fqs.notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (%s, 'aviso', 'Hola', 'Prueba de push') RETURNING id",
        [F["fav"]["usuario"]["id"]],
    )
    nid = str(n[0]["id"])
    e.correr(push.procesar(nid))
    e.correr(push.procesar(nid))
    envios = [x for x in llamadas if "fcm.googleapis.com" in x["url"]]
    assert len(envios) == 1, "se manda una sola vez"
    assert envios[0]["url"] == "https://fcm.googleapis.com/v1/projects/fqs-prueba/messages:send"
    assert envios[0]["headers"]["authorization"] == "Bearer ya29.prueba"
    cuerpo = json.loads(envios[0]["cuerpo"])
    assert cuerpo["message"]["token"] == token_tel
    assert cuerpo["message"]["notification"] == {"title": "Hola", "body": "Prueba de push"}
    assert cuerpo["message"]["data"]["notificacionId"] == nid

    # El JWT que se cambia por el token OAuth está firmado con la llave de la cuenta
    oauth = next(x for x in llamadas if x["url"].startswith("https://oauth2"))
    jwt = parse_qs(oauth["cuerpo"].decode())["assertion"][0]
    h, c, f = jwt.split(".")

    def b64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    llave.public_key().verify(b64(f), f"{h}.{c}".encode(), padding.PKCS1v15(), hashes.SHA256())
    claims = json.loads(b64(c))
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    assert claims["exp"] - claims["iat"] == 3600

    # Firebase dice que el token ya no existe, se borra del dispositivo
    respuesta_fcm.update(
        status=404, texto=json.dumps({"error": {"code": 404, "status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})
    )
    n2 = e.sql(
        "INSERT INTO fqs.notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (%s, 'aviso', 'Otra', 'Segunda') RETURNING id",
        [F["fav"]["usuario"]["id"]],
    )
    e.correr(push.procesar(str(n2[0]["id"])))
    quedan = e.sql("SELECT count(*)::int AS n FROM fqs.dispositivos WHERE token_fcm = %s", [token_tel])
    assert quedan[0]["n"] == 0
    # Solo se pidió un token OAuth, el resto reutilizó el de la caché
    assert len([x for x in llamadas if x["url"].startswith("https://oauth2")]) == 1


def test_cada_notificacion_nueva_avisa_por_el_canal(e):
    with psycopg.connect(os.environ["TEST_OWNER_DATABASE_URL"], autocommit=True) as escucha:
        escucha.execute("LISTEN fqs_notificaciones")
        n = e.sql(
            "INSERT INTO fqs.notificaciones (usuario_id, tipo, titulo, mensaje) VALUES (%s, 'aviso', 'Canal', 'Prueba') RETURNING id",
            [F["fav"]["usuario"]["id"]],
        )
        avisos = list(escucha.notifies(timeout=5, stop_after=1))
        assert avisos and avisos[0].payload == str(n[0]["id"])
