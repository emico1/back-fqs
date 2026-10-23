"""
Tipos reutilizables para los modelos de entrada (Pydantic).

Todos los modelos son estrictos, así que un campo que no está declarado (por ejemplo rol o
estado) provoca 400 en lugar de colarse en un UPDATE (protección contra asignación masiva).
Los textos se recortan, los correos se pasan a minúsculas y los teléfonos se normalizan
antes de validarse.
"""

import re
from datetime import date
from typing import Annotated, Any

from fastapi import Query
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, field_validator

from .errores import HttpError

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_CORREO_RE = re.compile(r"^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+\-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$")
_INSTANTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")


def _sin_nulos(v: Any) -> bool:
    if isinstance(v, str):
        return "\x00" not in v
    if isinstance(v, (list, tuple)):
        return all(_sin_nulos(x) for x in v)
    return True


class Modelo(BaseModel):
    """
    Base de todos los cuerpos de petición, rechaza campos no declarados. Ningún texto puede
    traer el carácter nulo, PostgreSQL no lo acepta y algunos programas lo usan para cortar
    cadenas.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def _rechazar_nulos(cls, v: Any) -> Any:
        if not _sin_nulos(v):
            raise ValueError("No puede contener el carácter nulo")
        return v


def _recortar(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


def _vacio_a_none(v: Any) -> Any:
    return None if v == "" else v


def Texto(minimo: int, maximo: int) -> Any:
    return Annotated[str, BeforeValidator(_recortar), Field(min_length=minimo, max_length=maximo)]


def TextoOpcional(maximo: int) -> Any:
    return Annotated[str | None, AfterValidator(_vacio_a_none), BeforeValidator(_recortar), Field(default=None, max_length=maximo)]


def _correo(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _CORREO_RE.match(v):
        raise ValueError("Correo inválido")
    return v


def _telefono(v: str) -> str:
    v = re.sub(r"[\s()\-]", "", v)
    if not re.fullmatch(r"\+?[0-9]{10,15}", v):
        raise ValueError("Teléfono inválido")
    return v


def _fecha(v: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ValueError("Usa el formato AAAA-MM-DD")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("Fecha inválida") from None
    return v


def _instante(v: str) -> str:
    if not _INSTANTE_RE.match(v):
        raise ValueError("Fecha y hora inválidas, usa ISO 8601 con zona horaria")
    return v


def _uuid(v: str) -> str:
    if not UUID_RE.match(v):
        raise ValueError("Identificador inválido")
    return v


def _username(v: str) -> str:
    v = v.strip()
    if not 3 <= len(v) <= 30:
        raise ValueError("Debe tener de 3 a 30 caracteres")
    if not re.fullmatch(r"[A-Za-z0-9_.]+", v):
        raise ValueError("Solo letras, números, punto y guion bajo")
    return v


def _clave_categoria(v: str) -> str:
    if not re.fullmatch(r"[A-Z][A-Z_]{1,40}", v):
        raise ValueError("Clave inválida")
    return v


Correo = Annotated[str, AfterValidator(_correo)]
Telefono = Annotated[str, AfterValidator(_telefono)]
Fecha = Annotated[str, AfterValidator(_fecha)]
Instante = Annotated[str, AfterValidator(_instante)]
Uuid = Annotated[str, AfterValidator(_uuid)]
Username = Annotated[str, AfterValidator(_username)]
Contrasena = Annotated[str, Field(min_length=1, max_length=128)]
ClaveCategoria = Annotated[str, AfterValidator(_clave_categoria)]
Entero = StrictInt
Numero = StrictFloat
Booleano = StrictBool


def telefono_canonico(v: str) -> str:
    """
    Formato único de teléfono. 10 dígitos son de México (+52), 52 seguido de 10 dígitos
    también. Los demás se guardan con + y sus dígitos.
    """
    d = re.sub(r"\D", "", v)
    if re.fullmatch(r"\d{10}", d):
        return f"+52{d}"
    return f"+{d}"


def es_telefono_mexicano(canonico: str) -> bool:
    """Solo se mandan SMS a México, así nadie puede usar el registro para enviar SMS caros a otros países."""
    return bool(re.fullmatch(r"\+52\d{10}", canonico))


def error_validacion(campo: str, mensaje: str) -> HttpError:
    """Mismo formato que los errores de los modelos, para reglas que cruzan varios campos."""
    return HttpError(400, "validacion", "Revisa los datos enviados", [{"campo": campo, "mensaje": mensaje}])


# ---------------- Parámetros de consulta comunes ----------------

Limite = Annotated[int, Query(ge=1, le=50)]
Desplazamiento = Annotated[int, Query(ge=0, le=10_000)]
UuidQuery = Annotated[str | None, Query(pattern=UUID_RE.pattern)]


def edad_en_anios(nacimiento: str, hoy: date | None = None) -> int:
    a, m, d = (int(x) for x in nacimiento.split("-"))
    from datetime import datetime, timezone

    h = hoy or datetime.now(timezone.utc).date()
    edad = h.year - a
    if h.month < m or (h.month == m and h.day < d):
        edad -= 1
    return edad
