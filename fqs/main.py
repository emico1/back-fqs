"""
Punto de entrada para servidores ASGI externos, por ejemplo
  uvicorn fqs.main:app --host 0.0.0.0 --port 3000
Lee .env de la carpeta actual igual que  python -m fqs.
"""

from .app import crear_app
from .config import cargar_env

cargar_env(".env")
app = crear_app()
