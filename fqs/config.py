"""
Toda la configuración sale de variables de entorno y se valida al arrancar.
Si falta algo obligatorio el proceso termina en lugar de arrancar inseguro.

Las variables se pueden poner en un archivo .env en la carpeta del proyecto (se lee al
iniciar con  python -m fqs). Una variable que ya existe en el entorno tiene prioridad.
"""

import base64
import binascii
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorConfig(Exception):
    pass


def cargar_env(ruta: str | Path = ".env") -> None:
    """Lee un archivo .env sencillo (CLAVE=valor, # comentarios). No pisa variables existentes."""
    p = Path(ruta)
    if not p.is_file():
        return
    for linea in p.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        if clave.startswith("export "):
            clave = clave[7:].strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        os.environ.setdefault(clave, valor)


@dataclass(frozen=True)
class Config:
    ENTORNO: Literal["development", "test", "production"]
    HOST: str
    PORT: int
    DATABASE_URL: str
    DB_SSL: Literal["disable", "require", "verify-full"]
    DB_SSL_CA: str | None
    DB_POOL_MAX: int
    DB_RED_AISLADA: bool
    TRUST_PROXY: int
    ACCESS_TTL_MINUTOS: int
    REFRESH_TTL_DIAS: int
    UPLOAD_DIR: str
    LOG_LEVEL: Literal["debug", "info", "warn", "error"]
    FCM_CUENTA_SERVICIO: str | None
    AVISOS_CADA_MINUTOS: int
    ADMIN_2FA: Literal["obligatorio", "opcional"]
    CLAVE_CIFRADO_2FA: str | None
    BREVO_API_KEY: str | None
    CORREO_REMITENTE: str | None
    CORREO_REMITENTE_NOMBRE: str
    CLAVES_CIFRADO_2FA_ANTERIORES: str | None
    SMS: Literal["brevo", "desactivado"]
    SMS_REMITENTE: str
    SMS_MAX_DIA: int
    SMS_MAX_NUMERO_DIA: int
    CONTRASENAS_FILTRADAS: Literal["revisar", "no_revisar"]
    ALERTAS_CORREO: str | None
    ANCLA_CADA_DIAS: int
    ADMIN_INACTIVIDAD_MINUTOS: int
    ADMIN_SESION_HORAS: int
    CUENTAS_INACTIVAS_MESES: int
    METRICAS_HOST: str
    METRICAS_PUERTO: int

    @property
    def produccion(self) -> bool:
        return self.ENTORNO == "production"

    @property
    def desarrollo(self) -> bool:
        return self.ENTORNO == "development"


def correos_alerta(c: Config) -> list[str]:
    return [x.strip().lower() for x in (c.ALERTAS_CORREO or "").split(",") if x.strip()]


def claves_anteriores_2fa(c: Config) -> list[str]:
    return [x.strip() for x in (c.CLAVES_CIFRADO_2FA_ANTERIORES or "").split(",") if x.strip()]


def _clave_32(v: str) -> bool:
    try:
        return len(base64.b64decode(v, validate=False)) == 32
    except (binascii.Error, ValueError):
        return False


def cargar_config(env: dict[str, str] | None = None) -> Config:
    e = dict(os.environ if env is None else env)
    errores: list[str] = []

    def texto(nombre: str, defecto: str | None = None) -> str | None:
        v = e.get(nombre)
        return v if v not in (None, "") else defecto

    def opcion(nombre: str, opciones: tuple[str, ...], defecto: str) -> str:
        v = texto(nombre, defecto)
        if v not in opciones:
            errores.append(f"{nombre} debe ser uno de {', '.join(opciones)}")
            return defecto
        return v

    def entero(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
        v = texto(nombre)
        if v is None:
            return defecto
        try:
            n = int(v)
        except ValueError:
            errores.append(f"{nombre} debe ser un número entero")
            return defecto
        if not minimo <= n <= maximo:
            errores.append(f"{nombre} debe estar entre {minimo} y {maximo}")
        return n

    entorno = texto("ENTORNO") or "development"
    if entorno not in ("development", "test", "production"):
        errores.append("ENTORNO debe ser development, test o production")
        entorno = "development"

    database_url = texto("DATABASE_URL")
    if not database_url:
        errores.append("DATABASE_URL es obligatoria")

    remitente = texto("CORREO_REMITENTE")
    if remitente and not _CORREO.match(remitente):
        errores.append("CORREO_REMITENTE no es un correo válido")
    nombre_remitente = texto("CORREO_REMITENTE_NOMBRE", "Familias que Suman") or ""
    if len(nombre_remitente) > 70:
        errores.append("CORREO_REMITENTE_NOMBRE es demasiado largo")
    sms_remitente = texto("SMS_REMITENTE", "FamSuman") or ""
    if not re.fullmatch(r"[A-Za-z0-9]{3,11}", sms_remitente):
        errores.append("SMS_REMITENTE debe tener de 3 a 11 letras o números")

    c = Config(
        ENTORNO=entorno,  # type: ignore[arg-type]
        HOST=texto("HOST", "127.0.0.1") or "127.0.0.1",
        PORT=entero("PORT", 3000, 1, 65535),
        DATABASE_URL=database_url or "",
        DB_SSL=opcion("DB_SSL", ("disable", "require", "verify-full"), "disable"),  # type: ignore[arg-type]
        DB_SSL_CA=texto("DB_SSL_CA"),
        DB_POOL_MAX=entero("DB_POOL_MAX", 10, 1, 100),
        DB_RED_AISLADA=opcion("DB_RED_AISLADA", ("0", "1"), "0") == "1",
        TRUST_PROXY=entero("TRUST_PROXY", 0, 0, 5),
        ACCESS_TTL_MINUTOS=entero("ACCESS_TTL_MINUTOS", 15, 5, 60),
        REFRESH_TTL_DIAS=entero("REFRESH_TTL_DIAS", 30, 1, 90),
        UPLOAD_DIR=texto("UPLOAD_DIR", "./uploads") or "./uploads",
        LOG_LEVEL=opcion("LOG_LEVEL", ("debug", "info", "warn", "error"), "info"),  # type: ignore[arg-type]
        FCM_CUENTA_SERVICIO=texto("FCM_CUENTA_SERVICIO"),
        AVISOS_CADA_MINUTOS=entero("AVISOS_CADA_MINUTOS", 5, 1, 60),
        ADMIN_2FA=opcion("ADMIN_2FA", ("obligatorio", "opcional"), "obligatorio"),  # type: ignore[arg-type]
        CLAVE_CIFRADO_2FA=texto("CLAVE_CIFRADO_2FA"),
        BREVO_API_KEY=texto("BREVO_API_KEY"),
        CORREO_REMITENTE=remitente,
        CORREO_REMITENTE_NOMBRE=nombre_remitente,
        CLAVES_CIFRADO_2FA_ANTERIORES=texto("CLAVES_CIFRADO_2FA_ANTERIORES"),
        SMS=opcion("SMS", ("brevo", "desactivado"), "desactivado"),  # type: ignore[arg-type]
        SMS_REMITENTE=sms_remitente,
        SMS_MAX_DIA=entero("SMS_MAX_DIA", 200, 1, 10_000),
        SMS_MAX_NUMERO_DIA=entero("SMS_MAX_NUMERO_DIA", 5, 1, 20),
        CONTRASENAS_FILTRADAS=opcion("CONTRASENAS_FILTRADAS", ("revisar", "no_revisar"), "revisar"),  # type: ignore[arg-type]
        ALERTAS_CORREO=texto("ALERTAS_CORREO"),
        ANCLA_CADA_DIAS=entero("ANCLA_CADA_DIAS", 7, 1, 31),
        ADMIN_INACTIVIDAD_MINUTOS=entero("ADMIN_INACTIVIDAD_MINUTOS", 30, 10, 240),
        ADMIN_SESION_HORAS=entero("ADMIN_SESION_HORAS", 12, 1, 72),
        CUENTAS_INACTIVAS_MESES=entero("CUENTAS_INACTIVAS_MESES", 24, 6, 120),
        METRICAS_HOST=texto("METRICAS_HOST", "127.0.0.1") or "127.0.0.1",
        # 0 apaga las métricas para Prometheus
        METRICAS_PUERTO=entero("METRICAS_PUERTO", 0, 0, 65535),
    )
    if errores:
        raise ErrorConfig(f"Configuración inválida ({', '.join(errores)})")

    if c.CLAVE_CIFRADO_2FA is not None and not _clave_32(c.CLAVE_CIFRADO_2FA):
        raise ErrorConfig("CLAVE_CIFRADO_2FA debe ser de 32 bytes en base64. Genera una con  python -m fqs.scripts.generar_clave")
    for k in claves_anteriores_2fa(c):
        if not _clave_32(k):
            raise ErrorConfig("Cada clave de CLAVES_CIFRADO_2FA_ANTERIORES debe ser de 32 bytes en base64")
    for correo in correos_alerta(c):
        if not _CORREO.match(correo):
            raise ErrorConfig(f"ALERTAS_CORREO tiene un correo inválido ({correo})")
    if c.ADMIN_2FA == "obligatorio" and not c.CLAVE_CIFRADO_2FA:
        raise ErrorConfig(
            "Falta CLAVE_CIFRADO_2FA, se necesita para el segundo factor de administración. "
            "Genera una con  python -m fqs.scripts.generar_clave  y pégala en .env"
        )
    if c.METRICAS_PUERTO and c.METRICAS_PUERTO == c.PORT:
        raise ErrorConfig("METRICAS_PUERTO debe ser distinto de PORT, las métricas nunca se publican en el puerto de la API")
    if c.SMS == "brevo" and not c.BREVO_API_KEY:
        raise ErrorConfig("SMS=brevo necesita BREVO_API_KEY")
    if c.BREVO_API_KEY and not c.CORREO_REMITENTE:
        raise ErrorConfig("Con BREVO_API_KEY también se necesita CORREO_REMITENTE (un remitente verificado en Brevo)")
    if c.produccion:
        if c.ADMIN_2FA != "obligatorio":
            raise ErrorConfig("En producción ADMIN_2FA debe ser obligatorio")
        local = bool(re.search(r"host=/|@/|localhost|127\.0\.0\.1", c.DATABASE_URL)) or c.DB_RED_AISLADA
        if c.DB_SSL == "disable" and not local:
            raise ErrorConfig("En producción DB_SSL debe ser require o verify-full cuando la base no es local")
    return c
