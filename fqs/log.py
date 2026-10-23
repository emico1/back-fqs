"""
Bitácora del servidor en JSON por línea, lista para cualquier recolector de logs.

Nunca se registran cuerpos de petición, contraseñas, tokens ni el encabezado
Authorization. Los campos con nombres sensibles se reemplazan aunque lleguen por error.
"""

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

_ORDEN = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_SENSIBLES = re.compile(r"pass|token|secret|authorization|cookie|hash", re.IGNORECASE)
_minimo = "info"


def nivel_log(nivel: str) -> None:
    global _minimo
    _minimo = nivel


def _ahora() -> str:
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _escribir(nivel: str, msg: str, datos: dict[str, Any] | None) -> None:
    if _ORDEN[nivel] < _ORDEN[_minimo]:
        return
    limpio = {k: ("[omitido]" if _SENSIBLES.search(k) else v) for k, v in (datos or {}).items() if v is not None}
    linea = json.dumps({"t": _ahora(), "nivel": nivel, "msg": msg, **limpio}, ensure_ascii=False, default=str)
    salida = sys.stderr if nivel in ("warn", "error") else sys.stdout
    salida.write(linea + "\n")
    salida.flush()


class _Log:
    def debug(self, msg: str, datos: dict[str, Any] | None = None) -> None:
        _escribir("debug", msg, datos)

    def info(self, msg: str, datos: dict[str, Any] | None = None) -> None:
        _escribir("info", msg, datos)

    def warn(self, msg: str, datos: dict[str, Any] | None = None) -> None:
        _escribir("warn", msg, datos)

    def error(self, msg: str, datos: dict[str, Any] | None = None) -> None:
        _escribir("error", msg, datos)


log = _Log()
