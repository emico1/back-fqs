"""
Middleware de la API (ASGI puro, envuelve a toda la aplicación).

  Identificador de petición (X-Request-Id) e IP real del cliente detrás de los proxies de
  confianza.
  Encabezados de seguridad en todas las respuestas.
  Tamaño máximo del cuerpo (64 KB en JSON, 6 MB en la subida de imágenes) y tipo de contenido.
  Bitácora de cada petición sin cuerpos ni encabezados sensibles.
  Métricas para Prometheus por plantilla de ruta, método y código de respuesta.
  Cualquier error no controlado responde 500 genérico, el detalle solo queda en la bitácora.
"""

import time
import traceback
import uuid
from typing import Any, Awaitable, Callable

from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import metricas
from ..jsonfmt import a_json
from ..log import log

LIMITE_JSON = 64 * 1024
LIMITE_ARCHIVO = 5 * 1024 * 1024 + 64 * 1024

Scope = dict[str, Any]
Mensaje = dict[str, Any]
Receive = Callable[[], Awaitable[Mensaje]]
Send = Callable[[Mensaje], Awaitable[None]]

_CSP_API = b"default-src 'none'; frame-ancestors 'none'"


def _encabezados_seguridad(produccion: bool) -> list[tuple[bytes, bytes]]:
    e = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-origin"),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]
    if produccion:
        e.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
    return e


def ip_cliente(scope: Scope, encabezados: dict[bytes, bytes], proxies: int) -> str:
    directa = scope.get("client")[0] if scope.get("client") else "desconocida"
    if proxies == 0:
        return directa
    cadena = [x.strip() for x in encabezados.get(b"x-forwarded-for", b"").decode("latin1").split(",") if x.strip()]
    # Con N proxies de confianza, el cliente real es la entrada que agregó el más externo
    return cadena[len(cadena) - proxies] if len(cadena) >= proxies else directa


class CuerpoGrande(StarletteHTTPException):
    """El cuerpo pasó del límite mientras se leía (sin Content-Length o con uno falso)."""

    def __init__(self) -> None:
        super().__init__(413, "El contenido excede el tamaño permitido")


def _error(status: int, codigo: str, mensaje: str, request_id: str) -> bytes:
    return a_json({"error": {"codigo": codigo, "mensaje": mensaje}, "requestId": request_id})


class MiddlewareFqs:
    def __init__(self, app: Callable, trust_proxy: int, produccion: bool) -> None:
        self.app = app
        self.trust_proxy = trust_proxy
        self.produccion = produccion
        self.seguridad = _encabezados_seguridad(produccion)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inicio = time.perf_counter()
        request_id = str(uuid.uuid4())
        encabezados = dict(scope.get("headers") or [])
        ip = ip_cliente(scope, encabezados, self.trust_proxy)
        estado = scope.setdefault("state", {})
        estado["request_id"] = request_id
        estado["ip"] = ip
        metodo = scope.get("method", "GET")
        ruta = scope.get("path", "")
        status = 500
        enviado = False
        metricas.EN_CURSO.inc()

        async def enviar(m: Mensaje) -> None:
            nonlocal status, enviado
            if m["type"] == "http.response.start":
                status = m["status"]
                enviado = True
                h = list(m.get("headers") or [])
                nombres = {k.lower() for k, _ in h}
                h.append((b"x-request-id", request_id.encode()))
                h.extend(x for x in self.seguridad if x[0] not in nombres)
                if b"content-security-policy" not in nombres:
                    h.append((b"content-security-policy", _CSP_API))
                if b"cache-control" not in nombres:
                    h.append((b"cache-control", b"no-store"))
                h = [(k, v) for k, v in h if k.lower() not in (b"server", b"x-powered-by")]
                m = {**m, "headers": h}
            await send(m)

        async def responder_error(codigo_http: int, codigo: str, mensaje: str, extra: list[tuple[bytes, bytes]] | None = None) -> None:
            cuerpo = _error(codigo_http, codigo, mensaje, request_id)
            await enviar(
                {
                    "type": "http.response.start",
                    "status": codigo_http,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(cuerpo)).encode()),
                        *(extra or []),
                    ],
                }
            )
            await enviar({"type": "http.response.body", "body": cuerpo})

        try:
            # El carácter nulo no tiene uso legítimo en una ruta ni en un parámetro de consulta
            consulta = scope.get("query_string", b"").lower()
            if b"%00" in consulta or b"\x00" in consulta or "\x00" in ruta:
                await responder_error(400, "formato_invalido", "Formato de dato inválido")
                return
            # Tamaño y tipo del cuerpo antes de que llegue a la ruta
            limite = LIMITE_ARCHIVO if ruta == "/v1/archivos" else LIMITE_JSON
            declarado = encabezados.get(b"content-length")
            tiene_cuerpo = (declarado not in (None, b"0")) or b"transfer-encoding" in encabezados
            if declarado is not None and declarado.isdigit() and int(declarado) > limite:
                await responder_error(413, "demasiado_grande", "El contenido excede el tamaño permitido")
                return
            if (
                metodo in ("POST", "PUT", "PATCH")
                and tiene_cuerpo
                and ruta.startswith("/v1/")
                and ruta != "/v1/archivos"
            ):
                tipo = encabezados.get(b"content-type", b"").split(b";")[0].strip().lower()
                if tipo != b"application/json":
                    await responder_error(415, "tipo_no_soportado", "Se esperaba Content-Type application/json")
                    return

            recibido = 0

            async def recibir() -> Mensaje:
                nonlocal recibido
                m = await receive()
                if m["type"] == "http.request":
                    recibido += len(m.get("body", b""))
                    if recibido > limite:
                        raise CuerpoGrande()
                return m

            await self.app(scope, recibir, enviar)
        except CuerpoGrande:
            if not enviado:
                await responder_error(413, "demasiado_grande", "El contenido excede el tamaño permitido")
        except Exception as e:  # noqa: BLE001
            log.error(
                "Error no controlado",
                {
                    "requestId": request_id,
                    "ruta": ruta,
                    "error": str(e),
                    "pila": None if self.produccion else traceback.format_exc(),
                },
            )
            if not enviado:
                await responder_error(500, "interno", "Ocurrió un error inesperado")
        finally:
            plantilla = getattr(scope.get("route"), "path", None) or ("/panel" if ruta.startswith("/panel") else "desconocida")
            segundos = time.perf_counter() - inicio
            ms = round(segundos * 1000)
            metricas.EN_CURSO.dec()
            metricas.registrar_peticion(plantilla, metodo, status, segundos)
            log.info("peticion", {"requestId": request_id, "metodo": metodo, "ruta": plantilla, "status": status, "ms": ms, "ip": ip})
