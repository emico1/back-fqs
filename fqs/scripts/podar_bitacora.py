"""
Retención de la bitácora de seguridad. Las filas más viejas que BITACORA_RETENCION_MESES (12 por
omisión) se guardan cifradas en un archivo y después se borran de la base. En la base queda un
corte con el hash de la última fila borrada, así la cadena se sigue verificando completa con
GET /v1/admin/bitacora/verificar.

Variables
  RESPALDO_DATABASE_URL     usuario dueño del schema, el del backend no puede borrar
  RESPALDO_CLAVE            la misma de los respaldos, sin ella el archivo no se abre
  RESPALDO_DIR              carpeta destino (./respaldos por omisión)
  BITACORA_RETENCION_MESES  meses que se conservan en la base
Uso  python -m fqs.scripts.podar_bitacora
"""

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from ..config import cargar_env
from ..jsonfmt import _por_defecto
from .respaldo_cifrado import cifrar_flujo, clave_respaldo


def main() -> None:
    cargar_env(".env")
    url = os.environ.get("RESPALDO_DATABASE_URL")
    if not url:
        raise RuntimeError("Falta RESPALDO_DATABASE_URL")
    clave = clave_respaldo(os.environ.get("RESPALDO_CLAVE"))
    meses = int(os.environ.get("BITACORA_RETENCION_MESES", "12"))
    if not 3 <= meses <= 120:
        raise RuntimeError("BITACORA_RETENCION_MESES debe estar entre 3 y 120")
    carpeta = Path(os.environ.get("RESPALDO_DIR", "./respaldos")).resolve()
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)

    with psycopg.connect(url, autocommit=True, options="-c search_path=fqs,pg_catalog", row_factory=dict_row) as db:
        # Nunca se poda la última fila, la cadena necesita un punto de partida
        r = db.execute(
            """SELECT max(id)::text AS hasta FROM bitacora_seguridad
               WHERE creado_en < now() - make_interval(months => %s) AND id < (SELECT max(id) FROM bitacora_seguridad)""",
            [meses],
        ).fetchone()
        hasta = r["hasta"] if r else None
        if not hasta:
            print(f"No hay eventos de más de {meses} meses, no se borró nada")
            return
        filas = db.execute("SELECT * FROM bitacora_seguridad WHERE id <= %s ORDER BY id", [hasta]).fetchall()
        nombre = f"bitacora-hasta-{hasta}.fqsr"
        lineas = (json.dumps(f, ensure_ascii=False, default=_por_defecto).encode() + b"\n" for f in filas)
        archivo = cifrar_flujo(lineas, carpeta / nombre, clave, "bitacora")
        n = db.execute("SELECT podar_bitacora(%s, %s)::text AS n", [hasta, nombre]).fetchone()
        print(f"Se archivaron y borraron {n['n'] if n else 0} eventos hasta el {hasta}")
        print(f"  {nombre}  {archivo['bytes']} bytes  sha256 {archivo['sha256']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Error, {e}\n")
        sys.exit(1)
