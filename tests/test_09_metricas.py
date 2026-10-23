"""
Métricas para Prometheus. Se revisa que salgan por un puerto aparte, que el puerto de la API
no las exponga, que las etiquetas no lleven datos personales y que cuenten lo que el tablero
de Grafana y las alertas necesitan.
"""

import re
import uuid

import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from fqs import metricas
from fqs.config import ErrorConfig, cargar_config
from fqs.limites import limiter

from conftest import ADMIN_PASSWORD

F: dict = {}


@pytest.fixture(scope="module", autouse=True)
def servidor(e):
    e.reiniciar_limites()
    F["cuenta"] = e.registrar("metricas")
    s = metricas.ServidorMetricas("127.0.0.1", 0).iniciar()
    F["url"] = f"http://127.0.0.1:{s.puerto}"
    F["cliente"] = httpx.Client(trust_env=False, timeout=10)
    yield
    F["cliente"].close()
    s.detener()


def _texto() -> str:
    r = F["cliente"].get(F["url"] + "/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    return r.text


def _valor(nombre: str, **etiquetas: str) -> float:
    for familia in text_string_to_metric_families(_texto()):
        for m in familia.samples:
            if m.name == nombre and all(m.labels.get(k) == v for k, v in etiquetas.items()):
                return m.value
    return 0.0


def test_el_puerto_de_la_api_no_publica_metricas(e):
    for ruta in ("/metrics", "/v1/metrics", "/metricas"):
        r = e.api("GET", ruta)
        assert r.status == 404
        assert b"fqs_peticiones" not in (r.body if isinstance(r.body, bytes) else str(r.body).encode())


def test_el_servidor_de_metricas_solo_responde_get_metrics():
    c = F["cliente"]
    assert c.get(F["url"] + "/").status_code == 404
    assert c.get(F["url"] + "/v1/salud").status_code == 404
    assert c.post(F["url"] + "/metrics", content=b"x").status_code == 405
    assert c.head(F["url"] + "/metrics").status_code == 405
    assert c.delete(F["url"] + "/metrics").status_code == 405


def test_peticiones_por_plantilla_de_ruta_sin_ids(e):
    token = F["cuenta"]["tokens"]["accessToken"]
    falso = str(uuid.uuid4())
    antes = _valor("fqs_peticiones_total", ruta="/v1/actividades/{actividadId}", metodo="GET", status="404")
    assert e.api("GET", f"/v1/actividades/{falso}", token=token).status == 404
    assert _valor("fqs_peticiones_total", ruta="/v1/actividades/{actividadId}", metodo="GET", status="404") == antes + 1
    # Una ruta que no existe no crea etiquetas nuevas
    antes = _valor("fqs_peticiones_total", ruta="desconocida", metodo="GET", status="404")
    e.api("GET", f"/v1/no-existe/{falso}")
    assert _valor("fqs_peticiones_total", ruta="desconocida", metodo="GET", status="404") == antes + 1
    texto = _texto()
    assert falso not in texto
    assert _valor("fqs_peticion_duracion_segundos_count", ruta="/v1/salud", metodo="GET") >= 0


def test_metricas_sin_datos_personales(e):
    texto = _texto()
    assert "@" not in texto
    assert "metricas@prueba.mx" not in texto
    assert F["cuenta"]["tokens"]["accessToken"] not in texto
    assert not re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", texto)
    assert "127.0.0.1" not in texto


def test_inicios_de_sesion_por_resultado(e):
    correctos = _valor("fqs_inicios_sesion_total", resultado="correcto")
    fallidos = _valor("fqs_inicios_sesion_total", resultado="credenciales")
    assert e.login("metricas@prueba.mx", "Otra-Contrasena-Mala-1").status == 401
    assert e.login("metricas@prueba.mx").status == 200
    assert _valor("fqs_inicios_sesion_total", resultado="credenciales") == fallidos + 1
    assert _valor("fqs_inicios_sesion_total", resultado="correcto") == correctos + 1


def test_eventos_de_seguridad_por_accion(e):
    antes = _valor("fqs_eventos_seguridad_total", accion="login_admin_fallido")
    limiter.reset()
    r = e.api("POST", "/v1/auth/login", json_={"identificador": "admin@fqs.mx", "password": ADMIN_PASSWORD + "x"})
    assert r.status == 401
    assert _valor("fqs_eventos_seguridad_total", accion="login_admin_fallido") == antes + 1


def test_respuestas_429_por_ruta(e):
    e.reiniciar_limites()
    antes = _valor("fqs_limite_excedido_total", ruta="/v1/auth/login")
    estados = [
        e.api("POST", "/v1/auth/login", json_={"identificador": f"nadie{i}@prueba.mx", "password": "Cualquier-Cosa-1"}).status
        for i in range(21)
    ]
    assert estados[-1] == 429
    assert _valor("fqs_limite_excedido_total", ruta="/v1/auth/login") == antes + estados.count(429)
    e.reiniciar_limites()


def test_conexiones_en_tiempo_real_y_proceso(e):
    metricas.vigilar_flujos(lambda: 3)
    assert _valor("fqs_flujos_tiempo_real") == 3
    metricas.vigilar_flujos(lambda: e.servicios.cupos.conectados)
    assert _valor("fqs_flujos_tiempo_real") == e.servicios.cupos.conectados
    assert _valor("process_resident_memory_bytes") > 0
    assert _valor("fqs_info", entorno="test") == 1


def test_el_puerto_de_metricas_no_puede_ser_el_de_la_api():
    base = {"DATABASE_URL": "postgresql://x@localhost/x", "ADMIN_2FA": "opcional", "PORT": "3000"}
    with pytest.raises(ErrorConfig, match="METRICAS_PUERTO"):
        cargar_config({**base, "METRICAS_PUERTO": "3000"})
    c = cargar_config({**base, "METRICAS_PUERTO": "9464"})
    assert c.METRICAS_PUERTO == 9464 and c.METRICAS_HOST == "127.0.0.1"
    assert cargar_config(base).METRICAS_PUERTO == 0


def test_series_de_las_alertas_existen_desde_el_arranque():
    texto = _texto()
    for linea in (
        'fqs_inicios_sesion_total{resultado="credenciales"}',
        'fqs_eventos_seguridad_total{accion="refresh_reutilizado"}',
        'fqs_eventos_seguridad_total{accion="acceso_denegado"}',
        'fqs_limite_excedido_total{ruta="/v1/auth/registro"}',
    ):
        assert linea in texto
