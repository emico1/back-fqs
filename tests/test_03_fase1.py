"""Fase 1. Ciudad, verificación, tipos, cupos en vivo, proyectos y privacidad."""

import json
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from conftest import PASSWORD
from utiles import en, mas

F: dict = {}


class Flujo:
    """Abre el flujo de cupos en tiempo real en un hilo y permite esperar eventos."""

    def __init__(self, base: str, token: str) -> None:
        self.cliente = httpx.Client(timeout=httpx.Timeout(30, read=60))
        self.eventos: queue.Queue = queue.Queue()
        self._listo = threading.Event()
        self.status = 0
        self.tipo = ""
        self._cerrado = False
        self._hilo = threading.Thread(target=self._leer, args=(base, token), daemon=True)
        self._hilo.start()
        self._listo.wait(10)

    def _leer(self, base: str, token: str) -> None:
        try:
            with self.cliente.stream("GET", base + "/v1/cupos/stream", headers={"authorization": f"Bearer {token}"}) as r:
                self.status = r.status_code
                self.tipo = r.headers.get("content-type", "")
                self._listo.set()
                bloque: list[str] = []
                for linea in r.iter_lines():
                    if self._cerrado:
                        return
                    if linea == "":
                        if "event: cupos" in bloque:
                            datos = next((x[6:] for x in bloque if x.startswith("data: ")), None)
                            if datos:
                                self.eventos.put(json.loads(datos))
                        bloque = []
                    else:
                        bloque.append(linea)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._listo.set()

    def evento(self, filtro, segundos: float = 5):  # noqa: ANN001, ANN201
        limite = time.time() + segundos
        while time.time() < limite:
            try:
                d = self.eventos.get(timeout=max(0.05, limite - time.time()))
            except queue.Empty:
                break
            if filtro(d):
                return d
        raise AssertionError("No llegó el evento esperado")

    def cerrar(self) -> None:
        self._cerrado = True
        self.cliente.close()


def _actividad(e, **datos) -> str:
    inicio = en(days=4)
    cuerpo = {
        "categoriaId": e.cat_medio,
        "ciudadId": e.ciudad_id,
        "titulo": "Actividad",
        "descripcionCorta": "Breve descripción",
        "descripcion": "Descripción completa de la actividad",
        "inicio": inicio,
        "fin": mas(inicio, hours=2),
        "direccion": "Calle Morelos 100",
        "cupoTotal": 10,
        **datos,
    }
    r = e.api("POST", "/v1/admin/actividades", token=e.admin, json_=cuerpo)
    assert r.status == 201, r.body
    p = e.api("POST", f"/v1/admin/actividades/{r.body['id']}/estado", token=e.admin, json_={"estado": "publicada"})
    assert p.status == 200
    return r.body["id"]


def _asociacion(e, nombre: str, ciudad: str, verificada: bool) -> str:
    r = e.api(
        "POST",
        "/v1/admin/asociaciones",
        token=e.admin,
        json_={
            "nombre": nombre,
            "descripcion": "Asociación de prueba para la fase 1",
            "categoriaId": e.cat_medio,
            "ciudadId": ciudad,
            "direccion": "Av. Constitución 500",
            "verificada": verificada,
        },
    )
    assert r.status == 201, r.body
    return r.body["id"]


@pytest.fixture(scope="module", autouse=True)
def preparar(e):
    e.reiniciar_limites()
    F["a"] = e.registrar("fase1a")
    F["b"] = e.registrar("fase1b")
    c = e.api("POST", "/v1/admin/ciudades", token=e.admin, json_={"nombre": "Saltillo", "estado": "Coahuila", "zonaHoraria": "America/Monterrey"})
    assert c.status == 201
    F["ciudad2"] = c.body["id"]
    F["verificada"] = _asociacion(e, "Casa Hogar Esperanza", e.ciudad_id, True)
    F["sin_verificar"] = _asociacion(e, "Grupo Sin Revisar", e.ciudad_id, False)
    otra = _asociacion(e, "Asociación Saltillense", F["ciudad2"], True)
    F["visita"] = _actividad(e, asociacionId=F["verificada"], titulo="Tarde de lotería en la casa hogar", tipo="visita")
    F["act_sin_verificar"] = _actividad(e, asociacionId=F["sin_verificar"], titulo="Actividad no verificada")
    F["otra_ciudad"] = _actividad(e, asociacionId=otra, ciudadId=F["ciudad2"], titulo="Actividad en Saltillo")


def test_zona_horaria_desconocida(e):
    r = e.api("POST", "/v1/admin/ciudades", token=e.admin, json_={"nombre": "Atlántida", "estado": "Mar", "zonaHoraria": "Mar/Profundo"})
    assert r.status == 422


def test_la_cuenta_es_individual_y_ya_no_acepta_tipo_cuenta(e):
    assert "tipoCuenta" not in F["a"]["usuario"]
    r = e.api(
        "POST",
        "/v1/auth/registro",
        json_={
            "nombre": "Familia Vieja",
            "username": "vieja",
            "correo": "vieja@x.mx",
            "password": PASSWORD,
            "fechaNacimiento": "1990-01-01",
            "ciudadId": e.ciudad_id,
            "avisoPrivacidadId": e.aviso_id,
            "tipoCuenta": "familiar",
        },
    )
    assert r.status == 400
    u = e.sql("SELECT tipo_cuenta FROM fqs.usuarios WHERE id = %s", [F["a"]["usuario"]["id"]])
    assert u[0]["tipo_cuenta"] == "individual"


def test_la_familia_solo_ve_su_ciudad(e):
    t = F["a"]["tokens"]["accessToken"]
    pedida = e.api("GET", f"/v1/actividades?ciudadId={F['ciudad2']}", token=t)
    assert pedida.status == 200
    assert not any(a["id"] == F["otra_ciudad"] for a in pedida.body)
    assert all(a["ciudad"]["id"] == e.ciudad_id for a in pedida.body)
    assert e.api("GET", f"/v1/actividades/{F['otra_ciudad']}", token=t).status == 404
    # Cambia su ciudad en el perfil y ahora sí la ve, y deja de ver la anterior
    cambio = e.api("PATCH", "/v1/yo", token=t, json_={"ciudadId": F["ciudad2"]})
    assert cambio.status == 200
    assert cambio.body["ciudad"]["id"] == F["ciudad2"]
    ahora = e.api("GET", "/v1/actividades", token=t)
    assert [a["id"] for a in ahora.body] == [F["otra_ciudad"]]
    assert e.api("GET", f"/v1/actividades/{F['visita']}", token=t).status == 404
    e.api("PATCH", "/v1/yo", token=t, json_={"ciudadId": e.ciudad_id})


def test_solo_asociaciones_verificadas_para_las_familias(e):
    t = F["a"]["tokens"]["accessToken"]
    asos = e.api("GET", "/v1/asociaciones", token=t)
    assert all(a["verificada"] is True for a in asos.body)
    assert not any(a["id"] == F["sin_verificar"] for a in asos.body)
    assert e.api("GET", f"/v1/asociaciones/{F['sin_verificar']}", token=t).status == 404
    acts = e.api("GET", "/v1/actividades", token=t)
    assert not any(a["id"] == F["act_sin_verificar"] for a in acts.body)
    assert e.api("GET", f"/v1/actividades/{F['act_sin_verificar']}", token=t).status == 404
    insc = e.api("POST", f"/v1/actividades/{F['act_sin_verificar']}/inscripcion", token=t, json_={"titularAsiste": True})
    assert insc.status == 404
    de_admin = e.api("GET", f"/v1/actividades?ciudadId={e.ciudad_id}", token=e.admin)
    assert any(a["id"] == F["act_sin_verificar"] for a in de_admin.body)


def test_filtro_por_tipo(e):
    t = F["a"]["tokens"]["accessToken"]
    visitas = e.api("GET", "/v1/actividades?tipo=visita", token=t)
    assert [a["id"] for a in visitas.body] == [F["visita"]]
    assert visitas.body[0]["tipo"] == "visita"
    vol = e.api("GET", "/v1/actividades?tipo=voluntariado", token=t)
    assert len(vol.body) > 0 and all(a["tipo"] == "voluntariado" for a in vol.body)
    assert e.api("GET", "/v1/actividades?tipo=otra", token=t).status == 400


def test_el_ultimo_lugar_es_para_una_sola_familia(e):
    act = _actividad(e, asociacionId=F["verificada"], titulo="Último lugar", cupoTotal=1)

    def inscribir(token: str):  # noqa: ANN202
        with httpx.Client(timeout=30) as c:
            r = c.post(
                f"{e.base}/v1/actividades/{act}/inscripcion",
                headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
                content=json.dumps({"titularAsiste": True}),
            )
            return r.status_code, r.json()

    with ThreadPoolExecutor(2) as hilos:
        r1, r2 = list(hilos.map(inscribir, [F["a"]["tokens"]["accessToken"], F["b"]["tokens"]["accessToken"]]))
    e.pendientes()
    assert sorted([r1[0], r2[0]]) == [201, 409]
    perdedora = r1 if r1[0] == 409 else r2
    assert perdedora[1]["error"]["mensaje"] == "Lo sentimos, esta actividad ya no tiene lugares disponibles"
    fila = e.sql("SELECT cupos_ocupados FROM fqs.actividades WHERE id = %s", [act])
    assert fila[0]["cupos_ocupados"] == 1


def test_si_el_grupo_no_cabe_se_dice_cuantos_lugares_quedan(e):
    act = _actividad(e, asociacionId=F["verificada"], titulo="Pocos lugares", cupoTotal=2, aptaNinos=True)
    t = F["b"]["tokens"]["accessToken"]
    m1 = e.api("POST", "/v1/yo/comunidad", token=t, json_={"nombre": "Luis", "relacion": "Hijo", "fechaNacimiento": "2015-05-05"})
    m2 = e.api("POST", "/v1/yo/comunidad", token=t, json_={"nombre": "Sara", "relacion": "Hija", "fechaNacimiento": "2017-07-07"})
    r = e.api("POST", f"/v1/actividades/{act}/inscripcion", token=t, json_={"titularAsiste": True, "miembros": [m1.body["id"], m2.body["id"]]})
    assert r.status == 409
    assert r.body["error"]["mensaje"] == "Solo quedan 2 lugares y tu registro es para 3 personas"


def test_cupos_en_tiempo_real_por_server_sent_events(e):
    assert e.api("GET", "/v1/cupos/stream").status == 401
    flujo = Flujo(e.base, F["a"]["tokens"]["accessToken"])
    try:
        assert flujo.status == 200
        assert flujo.tipo.startswith("text/event-stream")
        act = _actividad(e, asociacionId=F["verificada"], titulo="En vivo", cupoTotal=5)
        r = e.api("POST", f"/v1/actividades/{act}/inscripcion", token=F["b"]["tokens"]["accessToken"], json_={"titularAsiste": True})
        assert r.status == 201
        ev = flujo.evento(lambda d: d["actividadId"] == act)
        assert ev == {"actividadId": act, "cupoTotal": 5, "cuposOcupados": 1, "cuposDisponibles": 4}
        # Cancelar libera el lugar y también se anuncia
        e.api("DELETE", f"/v1/actividades/{act}/inscripcion", token=F["b"]["tokens"]["accessToken"])
        ev2 = flujo.evento(lambda d: d["actividadId"] == act and d["cuposDisponibles"] == 5)
        assert ev2["cuposOcupados"] == 0
    finally:
        flujo.cerrar()


def test_maximo_tres_flujos_abiertos_por_persona(e):
    t = F["b"]["tokens"]["accessToken"]
    abiertos = [Flujo(e.base, t) for _ in range(3)]
    try:
        assert all(f.status == 200 for f in abiertos)
        assert e.api("GET", "/v1/cupos/stream", token=t).status == 429
    finally:
        for f in abiertos:
            f.cerrar()


def test_proyectos_con_sus_campanas_el_borrador_no_se_ve(e):
    p = e.api(
        "POST",
        "/v1/admin/proyectos",
        token=e.admin,
        json_={
            "asociacionId": F["verificada"],
            "ciudadId": e.ciudad_id,
            "titulo": "Equipar el comedor comunitario",
            "descripcion": "Reunimos utensilios y despensa para el comedor",
            "fechaInicio": "2026-01-01",
        },
    )
    assert p.status == 201, p.body
    pid = p.body["id"]
    otra = e.api(
        "POST",
        "/v1/admin/proyectos",
        token=e.admin,
        json_={"asociacionId": F["verificada"], "ciudadId": F["ciudad2"], "titulo": "Mal", "descripcion": "Ciudad que no coincide", "fechaInicio": "2026-01-01"},
    )
    assert otra.status == 422
    al_reves = e.api(
        "POST",
        "/v1/admin/proyectos",
        token=e.admin,
        json_={"ciudadId": e.ciudad_id, "titulo": "Fechas", "descripcion": "Fin antes del inicio", "fechaInicio": "2026-02-01", "fechaFin": "2026-01-01"},
    )
    assert al_reves.status == 400
    assert al_reves.body["error"]["detalles"][0]["campo"] == "fechaFin"
    t = F["a"]["tokens"]["accessToken"]
    assert e.api("GET", f"/v1/proyectos/{pid}", token=t).status == 404
    c = e.api(
        "POST",
        "/v1/admin/campanas",
        token=e.admin,
        json_={
            "proyectoId": pid,
            "asociacionId": F["verificada"],
            "ciudadId": e.ciudad_id,
            "titulo": "Utensilios de cocina",
            "descripcion": "Ollas, cucharones y charolas",
            "inicio": en(hours=-1),
            "fin": en(days=20),
            "articulos": [{"nombre": "Ollas", "unidad": "piezas", "cantidadMeta": 10}],
            "puntosEntrega": [{"ciudadId": e.ciudad_id, "nombre": "Comedor", "direccion": "Calle Juárez 200", "horarios": "Sábados de 9 a 13"}],
        },
    )
    assert c.status == 201, c.body
    e.api("POST", f"/v1/admin/campanas/{c.body['id']}/estado", token=e.admin, json_={"estado": "publicada"})
    e.api("POST", f"/v1/admin/proyectos/{pid}/estado", token=e.admin, json_={"estado": "publicado"})
    lista = e.api("GET", "/v1/proyectos", token=t)
    mio = next(x for x in lista.body if x["id"] == pid)
    assert mio["campanasActivas"] == 1
    assert mio["asociacion"]["nombre"] == "Casa Hogar Esperanza"
    det = e.api("GET", f"/v1/proyectos/{pid}", token=t)
    assert det.status == 200
    assert [x["id"] for x in det.body["campanas"]] == [c.body["id"]]
    assert det.body["campanas"][0]["proyectoId"] == pid
    assert len(e.api("GET", f"/v1/campanas?proyectoId={pid}", token=t).body) == 1


def test_entregas_solo_con_articulo_y_punto_de_la_misma_campana(e):
    t = F["a"]["tokens"]["accessToken"]
    campanas = e.api("GET", "/v1/campanas", token=t)
    assert len(campanas.body) >= 2
    a, b = campanas.body[0], campanas.body[1]
    det_a = e.api("GET", f"/v1/campanas/{a['id']}", token=t)
    det_b = e.api("GET", f"/v1/campanas/{b['id']}", token=t)
    cruzada = e.api(
        "POST",
        f"/v1/campanas/{a['id']}/entregas",
        token=t,
        json_={"articuloId": det_a.body["articulos"][0]["id"], "puntoEntregaId": det_b.body["puntosEntrega"][0]["id"], "cantidad": 1},
    )
    assert cruzada.status == 422


def test_aviso_de_privacidad_consulta_nueva_version_y_aceptacion(e):
    t = F["a"]["tokens"]["accessToken"]
    p = e.api("GET", "/v1/yo/privacidad", token=t)
    assert p.status == 200
    assert p.body["aceptado"] is True
    assert p.body["aviso"]["id"] == e.aviso_id
    assert p.body["solicitudEliminacion"] is None
    nuevo = e.api(
        "POST",
        "/v1/admin/avisos-privacidad",
        token=e.admin,
        json_={"version": "2026.2", "contenido": "Aviso de privacidad actualizado en lenguaje claro. " * 3},
    )
    assert nuevo.status == 201
    viejo = e.aviso_id
    e.aviso_id = nuevo.body["id"]
    assert e.api("GET", "/v1/yo", token=t).body["avisoPendiente"] is True
    assert e.api("POST", "/v1/yo/privacidad/aceptar", token=t, json_={"avisoId": viejo}).status == 409
    acepta = e.api("POST", "/v1/yo/privacidad/aceptar", token=t, json_={"avisoId": e.aviso_id})
    assert acepta.status == 200
    assert acepta.body["avisoPendiente"] is False
    assert e.api("GET", "/v1/yo/privacidad", token=t).body["aceptado"] is True
