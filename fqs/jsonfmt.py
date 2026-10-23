"""
Formato JSON de las respuestas. Las fechas salen en UTC con milisegundos y Z al final
(2026-10-20T02:21:42.829Z), el formato que espera la app Android.
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.responses import JSONResponse


def iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    u = d.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + f"{u.microsecond // 1000:03d}Z"


def _por_defecto(v: Any) -> Any:
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (Decimal, UUID)):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None
    raise TypeError(f"No se puede convertir {type(v).__name__} a JSON")


def a_json(datos: Any) -> bytes:
    return json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=_por_defecto).encode("utf-8")


class RespuestaJson(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return a_json(content)

    def init_headers(self, headers: Any = None) -> None:  # charset explícito
        super().init_headers(headers)
        for i, (k, v) in enumerate(self.raw_headers):
            if k == b"content-type":
                self.raw_headers[i] = (k, b"application/json; charset=utf-8")
