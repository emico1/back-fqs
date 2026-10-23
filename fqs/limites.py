"""
Límites de peticiones (rate limiting).

Cada ruta sensible declara su propio límite con un decorador de slowapi, no hay un límite
global para toda la API. Así cada endpoint tiene el tope que corresponde a su riesgo.

| Límite          | Rutas                                                        | Por    |
|-----------------|--------------------------------------------------------------|--------|
| 20 / 15 minutos | inicio de sesión, segundo paso con código (app y panel)      | IP     |
| 20 / 15 minutos | renovación de sesión (app y panel)                           | IP     |
| 10 / hora       | registro                                                     | IP     |
| 30 / 15 minutos | verificar y reenviar códigos de registro, correo y teléfono  | IP     |
| 5 / hora        | recuperar y restablecer contraseña                           | IP     |
| 30 / hora       | propuestas, reportes, entregas, testimonios, respuestas      | cuenta |
| 30 / hora       | subidas de imágenes                                          | cuenta |

Además hay límites por cuenta que no dependen de la IP (clase Limitador), por ejemplo 5
contraseñas equivocadas bloquean la cuenta 15 minutos aunque el atacante cambie de IP.

Los contadores viven en memoria. Sirve para una sola instancia del backend. Si algún día se
corren varias instancias detrás de un balanceador hay que usar storage_uri con Redis.
"""

import math
import time

from slowapi import Limiter
from starlette.requests import Request

from .errores import HttpError

# Límites por ruta
LOGIN = "20/15 minutes"
REFRESH = "20/15 minutes"
REGISTRO = "10/hour"
VERIFICACION = "30/15 minutes"
RECUPERACION = "5/hour"
ESCRITURA = "30/hour"
SUBIDAS = "30/hour"


def ip_de(request: Request) -> str:
    """IP real del cliente, la calcula el middleware según TRUST_PROXY."""
    return getattr(request.state, "ip", None) or (request.client.host if request.client else "desconocida")


def cuenta_de(request: Request) -> str:
    """Id de la cuenta con sesión. Las rutas con este límite siempre exigen sesión."""
    usuario = getattr(request.state, "usuario", None)
    return f"usuario {usuario.id}" if usuario else f"ip {ip_de(request)}"


limiter = Limiter(key_func=ip_de, storage_uri="memory://", headers_enabled=False, strategy="fixed-window")


def segundos_para_reintentar(request: Request) -> int:
    """Segundos que faltan para que se libere el límite que se pasó."""
    vista = getattr(request.state, "view_rate_limit", None)
    if not vista:
        return 60
    limite, args = vista
    try:
        reinicio, _ = limiter.limiter.get_window_stats(limite, *args)
        return max(1, math.ceil(reinicio - time.time()))
    except Exception:  # noqa: BLE001
        return 60


class Limitador:
    """
    Contador de ventana fija en memoria para límites por cuenta (no por IP), que además se
    pueden consultar sin sumar y reiniciar al tener éxito.
    """

    def __init__(self, maximo: int, ventana_segundos: float) -> None:
        self.maximo = maximo
        self.ventana = ventana_segundos
        self._cubetas: dict[str, list[float]] = {}

    def _cubeta(self, clave: str) -> list[float]:
        ahora = time.monotonic()
        c = self._cubetas.get(clave)
        if c is None or c[1] <= ahora:
            c = [0, ahora + self.ventana]
            self._cubetas[clave] = c
            if len(self._cubetas) > 10_000:
                self._purgar(ahora)
        return c

    def consumir(self, clave: str) -> None:
        """Suma un intento. Lanza 429 si ya se pasó del límite."""
        c = self._cubeta(clave)
        c[0] += 1
        if c[0] > self.maximo:
            segundos = math.ceil(c[1] - time.monotonic())
            raise HttpError(
                429, "demasiadas_solicitudes", "Demasiados intentos, espera un momento", {"reintentarEnSegundos": segundos}
            )

    def bloqueado(self, clave: str) -> bool:
        """Revisa sin sumar."""
        c = self._cubetas.get(clave)
        return c is not None and c[1] > time.monotonic() and c[0] >= self.maximo

    def reiniciar(self, clave: str) -> None:
        self._cubetas.pop(clave, None)

    def limpiar(self) -> None:
        self._cubetas.clear()

    def _purgar(self, ahora: float) -> None:
        for k in [k for k, c in self._cubetas.items() if c[1] <= ahora]:
            del self._cubetas[k]


class LimitesCuenta:
    def __init__(self) -> None:
        # Por cuenta, intentos fallidos de contraseña o código antes de bloquear 15 minutos
        self.login_cuenta = Limitador(5, 15 * 60)
        # Por cuenta, solicitudes de código de recuperación
        self.recuperacion_cuenta = Limitador(5, 60 * 60)
        # Por titular, correos de confirmación a acompañantes (su correo no está verificado)
        self.correos_acompanantes = Limitador(30, 24 * 60 * 60)
