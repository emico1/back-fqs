"""
Reintentos con Idempotency-Key. La app manda después las escrituras que se hicieron sin
conexión, y si la respuesta se pierde vuelve a mandar la misma petición con la misma clave.
"""

import secrets

import pytest

from fqs.idempotencia import _huella, purgar
from fqs.rutas.social import Reporte

F: dict = {}


@pytest.fixture(scope="module", autouse=True)
def cuentas(e):
    e.reiniciar_limites()
    F["a"] = e.registrar("idempa")
    F["b"] = e.registrar("idempb")


def _t(c: str) -> str:
    return F[c]["tokens"]["accessToken"]


def _clave() -> str:
    return secrets.token_urlsafe(24)


def _reporte(texto: str = "La actividad empezó una hora tarde") -> dict:
    return {"tipo": "problema_aplicacion", "descripcion": texto}


def _contar(usuario_id: str) -> int:
    return e_global.sql("SELECT count(*)::int AS n FROM fqs.reportes_experiencia WHERE usuario_id = %s", [usuario_id])[0]["n"]


@pytest.fixture(autouse=True)
def _entorno(e):
    global e_global
    e_global = e
    e.reiniciar_limites()


def test_misma_clave_devuelve_la_misma_respuesta_sin_duplicar(e):
    clave = _clave()
    antes = _contar(F["a"]["usuario"]["id"])
    r1 = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    r2 = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    assert r1.status == 201 and r2.status == 201
    assert r1.body["id"] == r2.body["id"]
    assert "idempotent-replayed" not in r1.headers
    assert r2.headers["idempotent-replayed"] == "true"
    assert _contar(F["a"]["usuario"]["id"]) == antes + 1


def test_sin_clave_cada_peticion_crea_un_registro(e):
    antes = _contar(F["a"]["usuario"]["id"])
    e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte())
    e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte())
    assert _contar(F["a"]["usuario"]["id"]) == antes + 2


def test_misma_clave_con_otro_cuerpo_u_otra_ruta_se_rechaza(e):
    clave = _clave()
    assert e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave}).status == 201
    r = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte("Otro texto distinto del primero"), encabezados={"Idempotency-Key": clave})
    assert r.status == 422
    assert r.body["error"]["codigo"] == "idempotencia_conflicto"
    propuesta = {"tipo": "iniciativa_vecinal", "titulo": "Huerto comunitario", "descripcion": "Un huerto en el parque de la colonia"}
    r = e.api("POST", "/v1/propuestas", token=_t("a"), json_=propuesta, encabezados={"Idempotency-Key": clave})
    assert r.status == 422


def test_la_clave_es_de_cada_cuenta(e):
    clave = _clave()
    ra = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    rb = e.api("POST", "/v1/reportes", token=_t("b"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    assert ra.status == 201 and rb.status == 201
    assert ra.body["id"] != rb.body["id"]
    assert "idempotent-replayed" not in rb.headers


@pytest.mark.parametrize("clave", ["corta", "con espacios y mas de dieciseis", "x" * 65, "abc'; DROP TABLE x;--abcdef"])
def test_clave_con_formato_invalido(e, clave):
    r = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    assert r.status == 400


def test_una_propuesta_reintentada_no_choca_con_la_regla_de_duplicados(e):
    clave = _clave()
    propuesta = {"tipo": "asociacion", "titulo": "Banco de alimentos del barrio", "descripcion": "Recolecta alimentos para familias del barrio"}
    r1 = e.api("POST", "/v1/propuestas", token=_t("b"), json_=propuesta, encabezados={"Idempotency-Key": clave})
    r2 = e.api("POST", "/v1/propuestas", token=_t("b"), json_=propuesta, encabezados={"Idempotency-Key": clave})
    assert r1.status == 201 and r2.status == 201 and r1.body["id"] == r2.body["id"]
    # Sin la clave, la misma propuesta sí es un duplicado
    r3 = e.api("POST", "/v1/propuestas", token=_t("b"), json_=propuesta)
    assert r3.status == 409 and r3.body["error"]["codigo"] == "propuesta_duplicada"


def test_si_la_peticion_falla_la_clave_se_libera(e):
    clave = _clave()
    ajena = "11111111-2222-4333-8444-555555555555"
    r = e.api("POST", "/v1/reportes", token=_t("a"), json_={**_reporte(), "fotoClave": ajena}, encabezados={"Idempotency-Key": clave})
    assert r.status == 422 and r.body["error"]["codigo"] == "archivo_invalido"
    assert not e.sql("SELECT 1 FROM fqs.idempotencia WHERE clave = %s", [clave])
    r = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    assert r.status == 201


def test_peticion_en_proceso_y_clave_vencida(e):
    clave = _clave()
    usuario = F["a"]["usuario"]["id"]
    e.sql(
        "INSERT INTO fqs.idempotencia (usuario_id, clave, ruta, huella) VALUES (%s, %s, '/v1/reportes', %s)",
        [usuario, clave, _huella("/v1/reportes", Reporte(**_reporte()))],
    )
    r = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    assert r.status == 409 and r.body["error"]["codigo"] == "idempotencia_en_proceso"
    # Pasadas 48 horas la clave se puede volver a usar
    e.sql("UPDATE fqs.idempotencia SET creado_en = now() - interval '3 days' WHERE clave = %s", [clave])
    r = e.api("POST", "/v1/reportes", token=_t("a"), json_=_reporte(), encabezados={"Idempotency-Key": clave})
    assert r.status == 201


def test_la_limpieza_borra_las_claves_vencidas(e):
    clave = _clave()
    assert e.api("POST", "/v1/reportes", token=_t("b"), json_=_reporte(), encabezados={"Idempotency-Key": clave}).status == 201
    e.sql("UPDATE fqs.idempotencia SET creado_en = now() - interval '49 hours' WHERE clave = %s", [clave])
    e.correr(purgar(e.servicios.db))
    assert not e.sql("SELECT 1 FROM fqs.idempotencia WHERE clave = %s", [clave])
    assert e.sql("SELECT count(*)::int AS n FROM fqs.idempotencia WHERE creado_en > now() - interval '1 hour'")[0]["n"] > 0
