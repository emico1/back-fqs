"""Flujo completo de familia y administración, subida de imágenes y ciclo de vida de la cuenta."""

import pytest

from conftest import PASSWORD
from utiles import en, jpeg_con_exif, mas, png_con_texto

F: dict = {}


@pytest.fixture(scope="module", autouse=True)
def familias(e):
    e.reiniciar_limites()
    F["fam"] = e.registrar("flujo")["tokens"]["accessToken"]
    F["otra"] = e.registrar("intrusa")["tokens"]["accessToken"]


# ---------------- Flujo completo de familia y administración ----------------


def test_la_cuenta_de_administracion_no_se_inscribe(e):
    act = e.sql("SELECT id FROM fqs.actividades LIMIT 1")
    destino = act[0]["id"] if act else e.ciudad_id
    r = e.api("POST", f"/v1/actividades/{destino}/inscripcion", token=e.admin, json_={"titularAsiste": True})
    assert r.status == 403
    assert r.body["error"]["codigo"] == "solo_familias"


def test_una_familia_no_puede_usar_rutas_de_administracion(e):
    r = e.api("POST", "/v1/admin/asociaciones", token=F["fam"], json_={})
    assert r.status == 403
    # El intento queda en la bitácora de seguridad
    b = e.sql("SELECT accion, ruta FROM fqs.bitacora_seguridad WHERE accion = 'acceso_denegado' ORDER BY id DESC LIMIT 1")
    assert b[0]["ruta"] == "POST /v1/admin/asociaciones"


def test_admin_crea_asociacion_y_actividad_publicada(e):
    a = e.api(
        "POST",
        "/v1/admin/asociaciones",
        token=e.admin,
        json_={
            "nombre": "Raíces Vivas",
            "descripcion": "Reforestación urbana en familia",
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "direccion": "Parque Fundidora, Monterrey",
            "telefono": "+528112345678",
            "verificada": True,
            "familiasBeneficiadas": 50,
        },
    )
    assert a.status == 201, a.body
    F["asociacion"] = a.body["id"]
    # La acción de administración queda en la bitácora con el id creado
    b = e.sql("SELECT entidad_id, ruta FROM fqs.bitacora_seguridad WHERE accion = 'admin_accion' ORDER BY id DESC LIMIT 1")
    assert str(b[0]["entidad_id"]) == F["asociacion"]
    assert b[0]["ruta"] == "POST /v1/admin/asociaciones"
    inicio = en(days=3)
    act = e.api(
        "POST",
        "/v1/admin/actividades",
        token=e.admin,
        json_={
            "asociacionId": F["asociacion"],
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "titulo": "Jornada de Reforestación",
            "descripcionCorta": "Plantamos nativos",
            "descripcion": "Plantación de especies nativas en familia",
            "inicio": inicio,
            "fin": mas(inicio, hours=3),
            "direccion": "Parque Fundidora",
            "cupoTotal": 3,
            "aptaNinos": True,
        },
    )
    assert act.status == 201, act.body
    F["actividad"] = act.body["id"]
    assert e.api("GET", f"/v1/actividades/{F['actividad']}", token=F["fam"]).status == 404, "borrador no visible"
    pub = e.api("POST", f"/v1/admin/actividades/{F['actividad']}/estado", token=e.admin, json_={"estado": "publicada"})
    assert pub.status == 200


def test_listados_con_filtros_y_busqueda_segura(e):
    fam = F["fam"]
    lista = e.api("GET", f"/v1/asociaciones?ciudadId={e.ciudad_id}&categoria=MEDIO_AMBIENTE&q=raíces", token=fam)
    assert lista.status == 200
    assert len(lista.body) == 1
    inj = e.api("GET", "/v1/asociaciones?q=%27%20OR%201%3D1%20--", token=fam)
    assert inj.status == 200
    assert len(inj.body) == 0
    comodin = e.api("GET", "/v1/asociaciones?q=%25", token=fam)
    assert len(comodin.body) == 0
    act = e.api("GET", f"/v1/actividades?ciudadId={e.ciudad_id}", token=fam)
    assert act.body[0]["cuposDisponibles"] == 3
    assert act.body[0]["categoria"]["clave"] == "MEDIO_AMBIENTE"
    det = e.api("GET", f"/v1/asociaciones/{F['asociacion']}", token=fam)
    assert len(det.body["proximasActividades"]) == 1
    assert det.body["esFavorita"] is False


def test_comunidad_con_proteccion_contra_idor(e):
    fam, otra = F["fam"], F["otra"]
    a = e.api("POST", "/v1/yo/comunidad", token=fam, json_={"nombre": "Ana", "relacion": "Hija", "fechaNacimiento": "2016-10-20"})
    assert a.status == 201
    F["ana"] = a.body["id"]
    b = e.api("POST", "/v1/yo/comunidad", token=otra, json_={"nombre": "Ajeno", "relacion": "Hijo", "fechaNacimiento": "2010-01-01"})
    F["ajeno"] = b.body["id"]
    assert len(e.api("GET", "/v1/yo/comunidad", token=otra).body) == 1
    editar = e.api(
        "PUT", f"/v1/yo/comunidad/{F['ana']}", token=otra, json_={"nombre": "Robada", "relacion": "Hija", "fechaNacimiento": "2016-10-20"}
    )
    assert editar.status == 404
    assert e.api("DELETE", f"/v1/yo/comunidad/{F['ana']}", token=otra).status == 409
    assert e.api("GET", "/v1/yo/comunidad", token=fam).body[0]["nombre"] == "Ana"


def test_inscripcion_respeta_dueno_de_acompanantes_y_cupo(e):
    fam, otra, act = F["fam"], F["otra"], F["actividad"]
    ajeno = e.api("POST", f"/v1/actividades/{act}/inscripcion", token=fam, json_={"titularAsiste": True, "miembros": [F["ajeno"]]})
    assert ajeno.status == 409
    ok = e.api("POST", f"/v1/actividades/{act}/inscripcion", token=fam, json_={"titularAsiste": True, "miembros": [F["ana"]]})
    assert ok.status == 201, ok.body
    assert ok.body["cuposDisponibles"] == 1
    F["inscripcion"] = ok.body["inscripcionId"]
    sobrecupo = e.api("POST", f"/v1/actividades/{act}/inscripcion", token=otra, json_={"titularAsiste": True, "miembros": [F["ajeno"]]})
    assert sobrecupo.status == 409
    det = e.api("GET", f"/v1/actividades/{act}", token=fam)
    assert det.body["miInscripcion"]["titularAsiste"] is True
    assert det.body["miInscripcion"]["miembros"] == [F["ana"]]
    mias = e.api("GET", "/v1/yo/inscripciones?momento=proximas", token=fam)
    assert len(mias.body) == 1


def test_testimonio_exige_asistencia_y_la_otra_familia_no_usa_la_inscripcion(e):
    fam, otra, act, ins = F["fam"], F["otra"], F["actividad"], F["inscripcion"]
    subida = e.api("POST", "/v1/archivos", token=fam, crudo=jpeg_con_exif(), tipo="image/jpeg")
    assert subida.status == 201
    foto = subida.body["clave"]
    texto = {"texto": "Fue una gran experiencia familiar", "fotoClave": foto}
    assert e.api("POST", f"/v1/yo/inscripciones/{ins}/testimonio", token=fam, json_=texto).status == 409
    ajena = e.api("POST", f"/v1/yo/inscripciones/{ins}/testimonio", token=otra, json_={**texto, "texto": "Intento usar inscripción ajena"})
    assert ajena.status == 404
    # Se simula que la actividad ya empezó
    e.sql("UPDATE fqs.actividades SET inicio = now() - interval '1 hour', fin = now() + interval '1 hour' WHERE id = %s", [act])
    partes = e.api("GET", f"/v1/admin/actividades/{act}/participantes", token=e.admin)
    assert len(partes.body) == 2
    for p in partes.body:
        assert e.api("PUT", f"/v1/admin/participantes/{p['id']}/asistencia", token=e.admin, json_={"estado": "asistio"}).status == 200
    t = e.api("POST", f"/v1/yo/inscripciones/{ins}/testimonio", token=fam, json_=texto)
    assert t.status == 201
    # Pendiente de moderación, la otra familia todavía no ve la foto
    assert e.api("GET", f"/v1/archivos/{foto}", token=otra).status == 404
    mod = e.api("GET", "/v1/admin/testimonios?estado=pendiente", token=e.admin)
    e.api("PUT", f"/v1/admin/testimonios/{mod.body[0]['id']}", token=e.admin, json_={"estado": "aprobado"})
    assert e.api("GET", f"/v1/archivos/{foto}", token=otra).status == 200
    assert len(e.api("GET", f"/v1/actividades/{act}/testimonios", token=otra).body) == 1
    assert e.api("GET", "/v1/yo", token=fam).body["participaciones"] == 1


def test_campana_entrega_registrada_y_confirmada_por_admin(e):
    fam = F["fam"]
    c = e.api(
        "POST",
        "/v1/admin/campanas",
        token=e.admin,
        json_={
            "asociacionId": F["asociacion"],
            "ciudadId": e.ciudad_id,
            "titulo": "Abrigos para el invierno",
            "descripcion": "Recolecta de abrigos en buen estado",
            "inicio": en(hours=-1),
            "fin": en(days=10),
            "urgente": True,
            "articulos": [{"nombre": "Abrigos", "unidad": "prendas", "cantidadMeta": 100, "prioridad": "alta"}],
            "puntosEntrega": [
                {"ciudadId": e.ciudad_id, "nombre": "Centro Comunitario", "direccion": "Av. Las Rosas 1234", "horarios": "Lunes a viernes de 9 a 18"}
            ],
        },
    )
    assert c.status == 201, c.body
    cid = c.body["id"]
    e.api("POST", f"/v1/admin/campanas/{cid}/estado", token=e.admin, json_={"estado": "publicada"})
    det = e.api("GET", f"/v1/campanas/{cid}", token=fam)
    articulo = det.body["articulos"][0]
    punto = det.body["puntosEntrega"][0]
    ent = e.api(
        "POST", f"/v1/campanas/{cid}/entregas", token=fam, json_={"articuloId": articulo["id"], "puntoEntregaId": punto["id"], "cantidad": 25}
    )
    assert ent.status == 201, ent.body
    assert e.api("GET", f"/v1/campanas/{cid}", token=fam).body["articulos"][0]["cantidadRecibida"] == 0
    e.api("PUT", f"/v1/admin/entregas/{ent.body['id']}", token=e.admin, json_={"estado": "recibida"})
    despues = e.api("GET", f"/v1/campanas/{cid}", token=fam)
    assert despues.body["articulos"][0]["cantidadRecibida"] == 25
    assert despues.body["progreso"] == 0.25
    assert e.api("GET", "/v1/campanas", token=fam).body[0]["organizacion"] == "Raíces Vivas"


def test_propuesta_con_historial_revision_y_notificacion(e):
    fam, otra = F["fam"], F["otra"]
    base = {"tipo": "iniciativa_vecinal", "titulo": "Limpieza del parque", "descripcion": "Recolectar basura en el parque del barrio"}
    p = e.api("POST", "/v1/propuestas", token=fam, json_=base)
    assert p.status == 201
    pid = p.body["id"]
    assert e.api("GET", f"/v1/propuestas/{pid}", token=otra).status == 404
    e.api("PUT", f"/v1/admin/propuestas/{pid}/revision", token=e.admin, json_={"estado": "necesita_cambios", "comentario": "Indica la ubicación"})
    notis = e.api("GET", "/v1/notificaciones", token=fam)
    assert any(n["propuestaId"] == pid and not n["leida"] for n in notis.body)
    edit = e.api("PUT", f"/v1/propuestas/{pid}", token=fam, json_={**base, "ubicacion": "Parque Fundidora"})
    assert edit.status == 200
    assert edit.body["estado"] == "en_revision"
    det = e.api("GET", f"/v1/propuestas/{pid}", token=fam)
    assert [h["estado"] for h in det.body["historial"]] == ["en_revision", "necesita_cambios", "en_revision"]
    noti = next(n for n in notis.body if n["propuestaId"] == pid)
    assert e.api("POST", f"/v1/notificaciones/{noti['id']}/leida", token=otra).status == 204
    assert next(n for n in e.api("GET", "/v1/notificaciones", token=fam).body if n["id"] == noti["id"])["leida"] is False
    e.api("POST", f"/v1/notificaciones/{noti['id']}/leida", token=fam)
    assert next(n for n in e.api("GET", "/v1/notificaciones", token=fam).body if n["id"] == noti["id"])["leida"] is True


def test_reportes_validan_el_objetivo_segun_el_tipo(e):
    fam = F["fam"]
    assert e.api("POST", "/v1/reportes", token=fam, json_={"tipo": "problema_asociacion", "descripcion": "No contestan nunca"}).status == 422
    r = e.api(
        "POST",
        "/v1/reportes",
        token=fam,
        json_={"tipo": "problema_asociacion", "asociacionId": F["asociacion"], "nivelSatisfaccion": 2, "descripcion": "No contestan nunca"},
    )
    assert r.status == 201


def test_cancelar_actividad_avisa_a_las_familias(e):
    inicio = en(days=5)
    act = e.api(
        "POST",
        "/v1/admin/actividades",
        token=e.admin,
        json_={
            "asociacionId": F["asociacion"],
            "categoriaId": e.cat_medio,
            "ciudadId": e.ciudad_id,
            "titulo": "Limpieza de río",
            "descripcionCorta": "Limpiamos",
            "descripcion": "Limpieza del río Santa Catarina",
            "inicio": inicio,
            "fin": mas(inicio, hours=2),
            "direccion": "Río Santa Catarina",
            "cupoTotal": 10,
        },
    )
    aid = act.body["id"]
    e.api("POST", f"/v1/admin/actividades/{aid}/estado", token=e.admin, json_={"estado": "publicada"})
    e.api("POST", f"/v1/actividades/{aid}/inscripcion", token=F["otra"], json_={"titularAsiste": True})
    c = e.api("POST", f"/v1/admin/actividades/{aid}/cancelar", token=e.admin, json_={"motivo": "Lluvia intensa"})
    assert c.body["inscripcionesCanceladas"] == 1
    n = e.api("GET", "/v1/notificaciones", token=F["otra"])
    assert any(x["tipo"] == "actividad_cancelada" for x in n.body)


# ---------------- Subida de imágenes ----------------


def test_png_sin_metadatos_y_solo_lo_ve_su_dueno(e):
    fam = e.registrar("fotos")["tokens"]["accessToken"]
    otra = e.registrar("fotos2")["tokens"]["accessToken"]
    F["fotos"], F["fotos2"] = fam, otra
    r = e.api("POST", "/v1/archivos", token=fam, crudo=png_con_texto(), tipo="image/png")
    assert r.status == 201
    propio = e.api("GET", f"/v1/archivos/{r.body['clave']}", token=fam)
    assert propio.status == 200
    assert b"Monterrey" not in propio.body
    assert b"IEND" in propio.body
    assert propio.headers.get("x-content-type-options") == "nosniff"
    assert propio.headers.get("cache-control") == "private, max-age=86400"
    assert e.api("GET", f"/v1/archivos/{r.body['clave']}", token=otra).status == 404


def test_jpeg_pierde_el_exif(e):
    fam = F["fotos"]
    r = e.api("POST", "/v1/archivos", token=fam, crudo=jpeg_con_exif(), tipo="image/jpeg")
    datos = e.api("GET", f"/v1/archivos/{r.body['clave']}", token=fam).body
    assert b"GPSLatitude" not in datos
    assert b"JFIF" in datos


def test_rechaza_contenido_disfrazado_tipo_distinto_y_archivos_grandes(e):
    fam = F["fotos"]
    html = b"<html><script>alert(1)</script></html>"
    assert e.api("POST", "/v1/archivos", token=fam, crudo=html, tipo="image/png").status == 415
    assert e.api("POST", "/v1/archivos", token=fam, crudo=png_con_texto(), tipo="image/jpeg").status == 415
    grande = png_con_texto() + bytes(6 * 1024 * 1024)
    assert e.api("POST", "/v1/archivos", token=fam, crudo=grande, tipo="image/png").status == 413


def test_no_se_puede_enlazar_la_imagen_de_otra_persona(e):
    fam, otra = F["fotos"], F["fotos2"]
    r = e.api("POST", "/v1/archivos", token=fam, crudo=png_con_texto(), tipo="image/png")
    assert e.api("PATCH", "/v1/yo", token=otra, json_={"fotoClave": r.body["clave"]}).status == 422
    assert e.api("PATCH", "/v1/yo", token=fam, json_={"fotoClave": r.body["clave"]}).status == 200


# ---------------- Cuenta, suspensión, recuperación y eliminación ----------------


def test_cambiar_correo_exige_contrasena_actual(e):
    t = e.registrar("correo")["tokens"]["accessToken"]
    assert e.api("PATCH", "/v1/yo", token=t, json_={"correo": "nuevo@x.mx"}).status == 400
    assert e.api("PATCH", "/v1/yo", token=t, json_={"correo": "nuevo@x.mx", "passwordActual": "mala-123456"}).status == 403
    cambio = e.api("PATCH", "/v1/yo", token=t, json_={"correo": "nuevo@x.mx", "passwordActual": PASSWORD})
    assert cambio.status == 200
    # El correo nuevo no se aplica hasta verificarlo
    assert cambio.body["correo"] == "correo@prueba.mx"
    assert cambio.body["correoPendiente"] == "nu•••@x.mx"
    codigo = [x for x in e.correo.enviados if x.tipo == "verificacion" and x.destino == "nuevo@x.mx"][-1].token
    malo = "11111111" if codigo == "00000000" else "00000000"
    assert e.api("POST", "/v1/yo/correo/verificar", token=t, json_={"codigo": malo}).status == 400
    verificado = e.api("POST", "/v1/yo/correo/verificar", token=t, json_={"codigo": codigo})
    assert verificado.status == 200
    assert verificado.body["correo"] == "nuevo@x.mx"
    # El correo anterior recibe un aviso del cambio
    assert any(x.tipo == "aviso" and x.destino == "correo@prueba.mx" for x in e.correo.enviados)


def test_suspender_una_cuenta_corta_su_sesion_al_instante(e):
    reg = e.registrar("suspendida")
    t = reg["tokens"]["accessToken"]
    assert e.api("GET", "/v1/yo", token=t).status == 200
    s = e.api("PUT", f"/v1/admin/usuarios/{reg['usuario']['id']}/estado", token=e.admin, json_={"estado": "suspendido"})
    assert s.status == 204
    assert e.api("GET", "/v1/yo", token=t).status == 401
    assert e.login("suspendida@prueba.mx").status == 403


def test_recuperacion_con_codigo_de_un_solo_uso_que_revoca_sesiones(e):
    reg = e.registrar("olvido")
    e.reiniciar_limites()
    r = e.api("POST", "/v1/auth/recuperar", json_={"identificador": "olvido@prueba.mx"})
    assert r.status == 202
    inexistente = e.api("POST", "/v1/auth/recuperar", json_={"identificador": "fantasma@prueba.mx"})
    assert inexistente.status == 202
    assert inexistente.body["mensaje"] == r.body["mensaje"]
    codigo = e.ultimo_correo("recuperacion").token
    assert len(codigo) == 8 and codigo.isdigit()
    malo = "11111111" if codigo == "00000000" else "00000000"
    nueva = "Nueva-Clave-Segura-1"
    assert e.api("POST", "/v1/auth/restablecer", json_={"identificador": "olvido@prueba.mx", "codigo": malo, "password": nueva}).status == 400
    bueno = e.api("POST", "/v1/auth/restablecer", json_={"identificador": "olvido@prueba.mx", "codigo": codigo, "password": nueva})
    assert bueno.status == 204
    assert e.api("GET", "/v1/yo", token=reg["tokens"]["accessToken"]).status == 401
    reuso = e.api("POST", "/v1/auth/restablecer", json_={"identificador": "olvido@prueba.mx", "codigo": codigo, "password": "Otra-Clave-Segura-2"})
    assert reuso.status == 400
    assert e.login("olvido@prueba.mx", nueva).status == 200


def test_eliminacion_de_cuenta_anonimiza_y_borra_fotos(e):
    reg = e.registrar("borrar")
    t = reg["tokens"]["accessToken"]
    foto = e.api("POST", "/v1/archivos", token=t, crudo=png_con_texto(), tipo="image/png")
    e.api("PATCH", "/v1/yo", token=t, json_={"fotoClave": foto.body["clave"]})
    assert e.api("POST", "/v1/yo/eliminacion", token=t, json_={"password": "mala-12345678"}).status == 403
    assert e.api("POST", "/v1/yo/eliminacion", token=t, json_={"password": PASSWORD}).status == 202
    assert e.api("GET", "/v1/yo", token=t).status == 401
    sol = e.api("GET", "/v1/admin/solicitudes-eliminacion", token=e.admin)
    mia = next(x for x in sol.body if x["usuarioId"] == reg["usuario"]["id"])
    res = e.api("POST", f"/v1/admin/solicitudes-eliminacion/{mia['id']}/resolver", token=e.admin)
    assert res.status == 200
    assert res.body["archivosEliminados"] >= 1
    u = e.sql("SELECT nombre, correo, estado FROM fqs.usuarios WHERE id = %s", [reg["usuario"]["id"]])
    assert u[0] == {"nombre": "Usuario eliminado", "correo": None, "estado": "eliminado"}
    assert e.login("borrar@prueba.mx").status == 401
