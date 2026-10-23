"""Servicios compartidos por todas las rutas. Se arman una vez al iniciar el servidor."""

from dataclasses import dataclass, field

from .almacen import Almacen
from .config import Config
from .correo import Correo
from .db import Db
from .limites import LimitesCuenta
from .push import Push
from .seguridad.filtradas import RevisorFiltradas
from .seguridad.segundo_factor import SegundoFactor
from .sms import ControlSms
from .tiempo_real import CanalCupos
from .vigilancia import Vigilancia


@dataclass
class Servicios:
    db: Db
    config: Config
    almacen: Almacen
    correo: Correo
    cupos: CanalCupos
    push: Push
    segundo_factor: SegundoFactor
    filtradas: RevisorFiltradas
    vigilancia: Vigilancia
    sms: ControlSms
    limites: LimitesCuenta = field(default_factory=LimitesCuenta)
    # Carpeta del panel web. Por omisión la carpeta panel junto al código
    panel_dir: str | None = None
