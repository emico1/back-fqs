"""
Pruebas de integración contra una base PostgreSQL real y el servidor corriendo de verdad.

Necesitan dos URLs en el entorno
  TEST_OWNER_DATABASE_URL  rol dueño, se usa para recrear el schema
  TEST_DATABASE_URL        rol del grupo fqs_backend, es con el que corre la API
La base indicada se BORRA y se vuelve a crear, nunca apuntes a producción.

El servidor (uvicorn) corre en un hilo con su propio ciclo de eventos. Las pruebas le hablan
por HTTP como lo haría la app, y cuando necesitan llamar a un servicio directamente lo hacen
dentro de ese ciclo con Entorno.correr().
"""

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable

import httpx
import psycopg
import pytest
import uvicorn

from fqs.almacen import Almacen
from fqs.app import crear_app
from fqs.config import Config, cargar_config
from fqs.correo import CorreoBitacora
from fqs.db import Db
from fqs.http_cliente import RespuestaHttp
from fqs.limites import limiter
from fqs.log import nivel_log
from fqs.push import Push
from fqs.seguridad.contrasenas import hash_contrasena
from fqs.seguridad.filtradas import RevisorFiltradas
from fqs.seguridad.segundo_factor import SegundoFactor
from fqs.seguridad.totp import CifradoSecretos, desde_base32, totp
from fqs.servicios import Servicios
from fqs.sms import ControlSms, SmsBitacora
from fqs.tareas import esperar_pendientes
from fqs.tiempo_real import CanalCupos
from fqs.vigilancia import Vigilancia

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS_DB = [
    "01_esquema.sql",
    "02_catalogos.sql",
    "03_roles.sql",
    "04_backend.sql",
    "05_fase1.sql",
    "06_fase2.sql",
    "07_seguridad.sql",
    "08_seguridad2.sql",
    "09_telefono.sql",
    "10_idempotencia.sql",
]

# Pwned Passwords simulado. Estas contraseñas aparecen como filtradas, las demás no
FILTRADAS_FALSAS = ["Laguna-Brava-Azul-77", "Contrasena-Comun-123"]
PASSWORD = "Arbol-Nogal-2026!"
ADMIN_PASSWORD = "Admin-Seguro-Fqs-2026"


@dataclass
class Resp:
    status: int
    body: Any
    headers: httpx.Headers


@dataclass
class Entorno:
    base: str
    cliente: httpx.Client
    owner: psycopg.Connection
    servicios: Servicios
    correo: CorreoBitacora
    sms: SmsBitacora
    loop: asyncio.AbstractEventLoop
    dir_subidas: Path
    consultas_filtradas: list[str]
    admin: str = ""
    admin_refresh: str = ""
    admin_id: str = ""
    admin_secreto: bytes = b""
    ciudad_id: str = ""
    cat_medio: str = ""
    aviso_id: str = ""
    datos: dict[str, Any] = field(default_factory=dict)

    # ---------------- Utilidades ----------------

    def correr(self, coro: Awaitable[Any]) -> Any:
        """Corre una corutina dentro del ciclo de eventos del servidor y devuelve su resultado."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(30)  # type: ignore[arg-type]

    def pendientes(self) -> None:
        """Espera a que terminen los envíos en segundo plano (correos, SMS, push)."""
        self.correr(esperar_pendientes())

    def api(
        self,
        metodo: str,
        ruta: str,
        token: str | None = None,
        json_: Any = None,
        crudo: bytes | None = None,
        tipo: str | None = None,
        encabezados: dict[str, str] | None = None,
    ) -> Resp:
        h: dict[str, str] = dict(encabezados or {})
        contenido: bytes | None = None
        if token:
            h["authorization"] = f"Bearer {token}"
        if json_ is not None:
            h["content-type"] = "application/json"
            contenido = json.dumps(json_).encode()
        elif crudo is not None:
            h["content-type"] = tipo or "application/octet-stream"
            contenido = crudo
        r = self.cliente.request(metodo, self.base + ruta, headers=h, content=contenido)
        self.pendientes()
        cuerpo: Any = r.json() if "json" in r.headers.get("content-type", "") and r.content else r.content
        return Resp(r.status_code, cuerpo, r.headers)

    def sql(self, consulta: str, params: Any = None) -> list[dict[str, Any]]:
        """Consulta directa como dueño de la base, para preparar datos o revisar resultados."""
        with self.owner.cursor(row_factory=psycopg.rows.dict_row) as c:
            c.execute(consulta, params)
            return c.fetchall() if c.description else []

    def ultimo_sms(self, destino: str) -> str:
        texto = [x for x in self.sms.enviados if x.destino == destino][-1].texto
        m = re.search(r"\d{8}", texto)
        assert m
        return m.group(0)

    def ultimo_correo(self, tipo: str) -> Any:
        return [x for x in self.correo.enviados if x.tipo == tipo][-1]

    def reiniciar_limites(self) -> None:
        """Las pruebas vienen todas de 127.0.0.1, así que entre secciones se limpian los contadores."""
        limiter.reset()
        for nombre in ("login_cuenta", "recuperacion_cuenta", "correos_acompanantes"):
            getattr(self.servicios.limites, nombre).limpiar()

    def registrar(self, sufijo: str, **extra: Any) -> dict[str, Any]:
        """Registro completo. Toma el código que se mandó por correo o SMS y lo verifica."""
        # El límite real es de 10 registros por hora por IP, en pruebas todas vienen de 127.0.0.1
        limiter.reset()
        datos = {
            "nombre": f"Familia {sufijo}",
            "username": f"fam_{sufijo}",
            "correo": f"{sufijo}@prueba.mx",
            "password": PASSWORD,
            "fechaNacimiento": "1988-04-12",
            "ciudadId": self.ciudad_id,
            "avisoPrivacidadId": self.aviso_id,
            "preferencias": {"quiereParticipar": True},
            "categorias": ["MEDIO_AMBIENTE", "NO_EXISTE"],
        }
        datos.update(extra)
        datos = {k: v for k, v in datos.items() if v is not None}
        r = self.api("POST", "/v1/auth/registro", json_=datos)
        assert r.status == 202, r.body
        if r.body["canal"] == "sms":
            codigo = re.search(r"\d{8}", self.sms.enviados[-1].texto).group(0)  # type: ignore[union-attr]
        else:
            codigo = self.ultimo_correo("verificacion").token
        v = self.api("POST", "/v1/auth/registro/verificar", json_={"registroId": r.body["registroId"], "codigo": codigo})
        assert v.status == 201, v.body
        return v.body

    def login(self, identificador: str, password: str = PASSWORD) -> Resp:
        limiter.reset()
        return self.api("POST", "/v1/auth/login", json_={"identificador": identificador, "password": password})

    def codigo_admin(self) -> str:
        return totp(self.admin_secreto)


def _http_filtradas(consultas: list[str]):  # noqa: ANN202
    async def http(metodo: str, url: str, encabezados: dict[str, str], cuerpo: bytes | None, tiempo: float) -> RespuestaHttp:
        consultas.append(url)
        prefijo = url[-5:]
        lineas = ["0018A45C4D1DEF81644B54AB7F969B88D65:0"]
        for p in FILTRADAS_FALSAS:
            h = hashlib.sha1(p.encode()).hexdigest().upper()
            if h.startswith(prefijo):
                lineas.append(f"{h[5:]}:4127")
        return RespuestaHttp(200, "\r\n".join(lineas))

    return http


def _preparar_base(owner_url: str) -> psycopg.Connection:
    owner = psycopg.connect(owner_url, autocommit=True)
    owner.execute("DROP SCHEMA IF EXISTS fqs CASCADE")
    for f in SCRIPTS_DB:
        owner.execute((RAIZ / "db" / f).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    owner.execute(
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_api_test') THEN
             CREATE ROLE fqs_api_test LOGIN PASSWORD 'prueba-local-fqs' IN ROLE fqs_backend; END IF; END $$"""
    )
    return owner


@pytest.fixture(scope="session")
def e() -> Any:
    owner_url = os.environ.get("TEST_OWNER_DATABASE_URL")
    api_url = os.environ.get("TEST_DATABASE_URL")
    if not owner_url or not api_url:
        pytest.exit("Define TEST_OWNER_DATABASE_URL y TEST_DATABASE_URL", returncode=2)
    nivel_log("error")
    owner = _preparar_base(owner_url)
    h = asyncio.run(hash_contrasena(ADMIN_PASSWORD))
    with owner.cursor() as c:
        c.execute(
            """INSERT INTO fqs.usuarios (nombre, username, correo, password_hash, rol, tipo_cuenta)
               VALUES ('Admin', 'admin', 'admin@fqs.mx', %s, 'admin', 'individual') RETURNING id""",
            [h],
        )
        admin_id = str(c.fetchone()[0])  # type: ignore[index]
        c.execute("SELECT id FROM fqs.ciudades LIMIT 1")
        ciudad_id = str(c.fetchone()[0])  # type: ignore[index]
        c.execute("SELECT id FROM fqs.categorias WHERE clave = 'MEDIO_AMBIENTE'")
        cat_medio = str(c.fetchone()[0])  # type: ignore[index]

    dir_subidas = Path(tempfile.mkdtemp(prefix="fqs-test-"))
    import base64

    clave_cifrado = base64.b64encode(secrets.token_bytes(32)).decode()
    config: Config = cargar_config(
        {"DATABASE_URL": api_url, "ENTORNO": "test", "UPLOAD_DIR": str(dir_subidas), "CLAVE_CIFRADO_2FA": clave_cifrado, "LOG_LEVEL": "error"}
    )
    correo = CorreoBitacora(False)
    sms = SmsBitacora(False)
    consultas: list[str] = []

    async def fabrica(cfg: Config) -> Servicios:
        db = Db(cfg)
        await db.abrir()
        almacen = Almacen(str(dir_subidas))
        almacen.preparar()
        cupos = CanalCupos(db)
        await cupos.iniciar()
        return Servicios(
            db=db,
            config=cfg,
            almacen=almacen,
            correo=correo,
            cupos=cupos,
            # Push con Firebase falso, ver test_fase2
            push=Push(db, None),
            segundo_factor=SegundoFactor(db, CifradoSecretos(clave_cifrado)),
            filtradas=RevisorFiltradas(True, _http_filtradas(consultas)),
            vigilancia=Vigilancia(db, correo, cfg),
            sms=ControlSms(db, sms, cfg, True),
        )

    app = crear_app(config=config, fabrica=fabrica)
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on", server_header=False))
    loop = asyncio.new_event_loop()
    hilo = threading.Thread(target=lambda: loop.run_until_complete(servidor.serve()), daemon=True)
    hilo.start()
    limite = time.time() + 20
    while not servidor.started:
        if time.time() > limite or not hilo.is_alive():
            raise RuntimeError("El servidor de pruebas no arrancó")
        time.sleep(0.05)
    puerto = servidor.servers[0].sockets[0].getsockname()[1]

    ent = Entorno(
        base=f"http://127.0.0.1:{puerto}",
        cliente=httpx.Client(timeout=30),
        owner=owner,
        servicios=app.state.servicios,
        correo=correo,
        sms=sms,
        loop=loop,
        dir_subidas=dir_subidas,
        consultas_filtradas=consultas,
        admin_id=admin_id,
        ciudad_id=ciudad_id,
        cat_medio=cat_medio,
    )

    # La administración exige segundo factor. El admin de las pruebas lo activa como lo haría
    # una persona, con contraseña, QR y el primer código de su app
    login = ent.login("ADMIN@fqs.mx", ADMIN_PASSWORD)
    assert login.status == 200, login.body
    assert login.body["configurar2fa"] is True
    sin_factor = login.body["tokens"]["accessToken"]
    ini = ent.api("POST", "/v1/admin/2fa/iniciar", token=sin_factor, json_={"password": ADMIN_PASSWORD})
    assert ini.status == 200, ini.body
    ent.admin_secreto = desde_base32(ini.body["secreto"])
    conf = ent.api("POST", "/v1/admin/2fa/confirmar", token=sin_factor, json_={"codigo": totp(ent.admin_secreto)})
    assert conf.status == 200, conf.body
    ent.admin = sin_factor
    ent.admin_refresh = login.body["tokens"]["refreshToken"]

    yield ent

    ent.cliente.close()
    servidor.should_exit = True
    hilo.join(15)
    owner.close()
    shutil.rmtree(dir_subidas, ignore_errors=True)
