"""
Genera docs/openapi.json a partir de las rutas registradas de verdad en la aplicación FastAPI,
así la descripción no se desactualiza. Incluye los modelos de cada cuerpo con sus reglas de
validación, y sirve para importarla en OWASP ZAP, Postman o Burp.
Uso  python -m fqs.scripts.openapi [https://servidor]
"""

import json
import sys
from pathlib import Path

from ..app import crear_app
from ..config import cargar_config


def main(servidor: str) -> None:
    config = cargar_config({"DATABASE_URL": "postgresql://nadie@localhost/nada", "ADMIN_2FA": "opcional", "LOG_LEVEL": "error"})
    # Solo se registran rutas, ningún servicio se usa ni se conecta la base
    app = crear_app(config=config)
    doc = app.openapi()
    doc["servers"] = [{"url": servidor}]
    doc.setdefault("components", {}).setdefault("securitySchemes", {})["panelEncabezado"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-FQS-Panel",
        "description": "Valor 1. Obligatorio con cookie en todo lo que no sea GET (defensa contra CSRF)",
    }
    subida = doc["paths"].get("/v1/archivos", {}).get("post")
    if subida is not None:
        subida["requestBody"] = {
            "required": True,
            "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in ("image/jpeg", "image/png")},
        }
    destino = Path("docs") / "openapi.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    operaciones = sum(len(v) for v in doc["paths"].values())
    print(f"{destino} con {len(doc['paths'])} rutas y {operaciones} operaciones")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "https://localhost")
