"""
Respaldo cifrado de la base y de las fotos subidas.

Variables
  RESPALDO_DATABASE_URL  usuario dueño del schema (postgres), el del backend no alcanza
  RESPALDO_CLAVE         32 bytes en base64, distinta de CLAVE_CIFRADO_2FA. Guárdala fuera
                         del servidor, sin ella el respaldo no se puede abrir
  RESPALDO_DIR           carpeta destino (por omisión ./respaldos)
  RESPALDO_CONSERVAR     cuántos respaldos guardar (por omisión 14)
  UPLOAD_DIR             carpeta de fotos (por omisión ./uploads)
  PG_BIN                 carpeta de pg_dump si no está en el PATH

Crea tres archivos con la misma marca de tiempo
  respaldo-AAAAMMDD-HHMMSS-db.fqsr        pg_dump del schema fqs, cifrado
  respaldo-AAAAMMDD-HHMMSS-archivos.fqsr  tar de las fotos, cifrado
  respaldo-AAAAMMDD-HHMMSS.json           manifiesto con tamaños y SHA-256
Uso  python -m fqs.scripts.respaldo
"""

import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..config import cargar_env
from ..jsonfmt import iso
from .respaldo_cifrado import TROZO, cifrar_flujo, clave_respaldo


def comando(nombre: str) -> str:
    pg_bin = os.environ.get("PG_BIN")
    return str(Path(pg_bin) / nombre) if pg_bin else nombre


def _salida_de(proceso: subprocess.Popen) -> Iterator[bytes]:
    assert proceso.stdout
    while b := proceso.stdout.read(TROZO):
        yield b


def _leer_archivo(ruta: str) -> Iterator[bytes]:
    with open(ruta, "rb") as f:
        while b := f.read(TROZO):
            yield b


def main() -> None:
    cargar_env(".env")
    url = os.environ.get("RESPALDO_DATABASE_URL")
    if not url:
        raise RuntimeError("Falta RESPALDO_DATABASE_URL")
    clave = clave_respaldo(os.environ.get("RESPALDO_CLAVE"))
    carpeta = Path(os.environ.get("RESPALDO_DIR", "./respaldos")).resolve()
    conservar = int(os.environ.get("RESPALDO_CONSERVAR", "14"))
    subidas = Path(os.environ.get("UPLOAD_DIR", "./uploads")).resolve()
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)

    base = f"respaldo-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    archivos: list[dict] = []

    # Formato custom de pg_dump, comprimido y restaurable por partes con pg_restore
    dump = subprocess.Popen(
        [comando("pg_dump"), "--format=custom", "--schema=fqs", "--no-password", f"--dbname={url}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    nombre_db = f"{base}-db.fqsr"
    datos = cifrar_flujo(_salida_de(dump), carpeta / nombre_db, clave, "db")
    errores = dump.stderr.read().decode(errors="replace").strip() if dump.stderr else ""
    if dump.wait() != 0:
        (carpeta / nombre_db).unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump terminó con código {dump.returncode}. {errores}")
    archivos.append({"tipo": "db", "nombre": nombre_db, **datos})

    if subidas.is_dir():
        # El tar se arma en un temporal y se cifra, así funciona igual en Windows, Mac y Linux
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            with tarfile.open(fileobj=tmp, mode="w") as tar:
                tar.add(subidas, arcname=".")
        try:
            nombre_tar = f"{base}-archivos.fqsr"
            t = cifrar_flujo(_leer_archivo(tmp.name), carpeta / nombre_tar, clave, "archivos")
            archivos.append({"tipo": "archivos", "nombre": nombre_tar, **t})
        finally:
            os.unlink(tmp.name)

    manifiesto = {"formato": "fqs-respaldo-1", "creadoEn": iso(datetime.now(timezone.utc)), "cifrado": "AES-256-GCM", "archivos": archivos}
    ruta_manifiesto = carpeta / f"{base}.json"
    ruta_manifiesto.write_text(json.dumps(manifiesto, indent=2) + "\n", encoding="utf-8")
    os.chmod(ruta_manifiesto, 0o600)

    # Se borran los más viejos, se conservan los últimos N
    todos = sorted(f.name for f in carpeta.iterdir() if re.fullmatch(r"respaldo-\d{8}-\d{6}\.json", f.name))
    for viejo in todos[: max(0, len(todos) - conservar)]:
        prefijo = viejo[: -len(".json")]
        for f in carpeta.iterdir():
            if f.name.startswith(prefijo):
                f.unlink()

    print(f"Respaldo listo en {ruta_manifiesto}")
    for a in archivos:
        print(f"  {a['nombre']}  {a['bytes']} bytes  sha256 {a['sha256']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Error, {e}\n")
        sys.exit(1)
