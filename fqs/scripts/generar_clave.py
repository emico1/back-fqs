"""
Imprime una clave aleatoria de 32 bytes en base64, para CLAVE_CIFRADO_2FA o RESPALDO_CLAVE.
Cada variable debe tener su propia clave.
Uso  python -m fqs.scripts.generar_clave
"""

import base64
import secrets

if __name__ == "__main__":
    print(base64.b64encode(secrets.token_bytes(32)).decode())
