"""
Restaura un respaldo hecho con  python -m fqs.scripts.respaldo

  python -m fqs.scripts.restaurar respaldos/respaldo-20261017-030000.json --solo-verificar
    Revisa los SHA-256 del manifiesto y que cada archivo se descifre con la clave. No toca la
    base. Conviene correrlo seguido, un respaldo que no se puede abrir no sirve.

  python -m fqs.scripts.restaurar respaldos/respaldo-20261017-030000.json
    Además reemplaza el schema fqs en RESPALDO_DATABASE_URL y, si se indica --fotos-en
    carpeta, extrae ahí las fotos. Pide escribir el nombre de la base.
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from ..config import cargar_env
from .respaldo import comando
from .respaldo_cifrado import clave_respaldo, descifrar_archivo, sha256_archivo


def _correr(args: list[str], mostrar: bool = True) -> None:
    r = subprocess.run(args, stdout=None if mostrar else subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} terminó con código {r.returncode}. {r.stderr.decode(errors='replace').strip()}")


def main(args: list[str]) -> None:
    cargar_env(".env")
    ruta_manifiesto = next((a for a in args if a.endswith(".json")), None)
    if not ruta_manifiesto:
        raise RuntimeError("Indica el manifiesto, por ejemplo  python -m fqs.scripts.restaurar respaldos/respaldo-AAAAMMDD-HHMMSS.json")
    solo_verificar = "--solo-verificar" in args
    fotos_en = args[args.index("--fotos-en") + 1] if "--fotos-en" in args else None
    clave = clave_respaldo(os.environ.get("RESPALDO_CLAVE"))

    carpeta = Path(ruta_manifiesto).resolve().parent
    m = json.loads(Path(ruta_manifiesto).read_text(encoding="utf-8"))
    if m.get("formato") != "fqs-respaldo-1":
        raise RuntimeError("Formato de manifiesto desconocido")

    temporal = Path(tempfile.mkdtemp(prefix="fqs-restaurar-"))
    try:
        descifrados: dict[str, Path] = {}
        for a in m["archivos"]:
            ruta = carpeta / Path(a["nombre"]).name
            if sha256_archivo(ruta) != a["sha256"]:
                raise RuntimeError(f"{a['nombre']} no coincide con el manifiesto (archivo dañado o cambiado)")
            salida = temporal / a["tipo"]
            descifrar_archivo(ruta, salida, clave, a["tipo"])
            descifrados[a["tipo"]] = salida
            print(f"  {a['nombre']} íntegro y descifrado")
        if "db" in descifrados:
            try:
                _correr([comando("pg_restore"), "--list", str(descifrados["db"])], mostrar=False)
            except RuntimeError as e:
                raise RuntimeError(f"El contenido descifrado no es un respaldo válido de pg_dump. {e}") from None
        if solo_verificar:
            print(f"Respaldo del {m['creadoEn']} verificado, se puede restaurar")
            return

        url = os.environ.get("RESPALDO_DATABASE_URL")
        if not url:
            raise RuntimeError("Falta RESPALDO_DATABASE_URL")
        nombre_base = urlsplit(url).path.lstrip("/")
        if input(f"Esto reemplaza el schema fqs de la base {nombre_base}. Escribe su nombre para continuar ").strip() != nombre_base:
            raise RuntimeError("Cancelado, no se cambió nada")

        if "db" in descifrados:
            # Todo o nada. Los triggers se crean después de cargar los datos, así la bitácora
            # conserva sus hashes y fechas originales
            _correr(
                [comando("pg_restore"), "--clean", "--if-exists", "--single-transaction", "--no-password", f"--dbname={url}", str(descifrados["db"])]
            )
            print("Base restaurada")
        if "archivos" in descifrados and fotos_en:
            destino = Path(fotos_en)
            destino.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tarfile.open(descifrados["archivos"]) as tar:
                # El filtro data rechaza rutas absolutas, ../ y enlaces que salgan de la carpeta
                tar.extractall(destino, filter="data")
            print(f"Fotos restauradas en {destino}")
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Error, {e}\n")
        sys.exit(1)
