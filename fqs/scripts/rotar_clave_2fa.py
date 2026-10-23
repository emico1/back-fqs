"""
Vuelve a cifrar todos los secretos del segundo factor con la clave actual.

Para rotar la clave (por ejemplo si se sospecha que se filtró)
  1. python -m fqs.scripts.generar_clave
  2. En .env mueve la clave vieja a CLAVES_CIFRADO_2FA_ANTERIORES y pon la nueva en
     CLAVE_CIFRADO_2FA. Reinicia la API, ya funciona con las dos.
  3. python -m fqs.scripts.rotar_clave_2fa
  4. Borra CLAVES_CIFRADO_2FA_ANTERIORES y reinicia la API.
Nadie tiene que volver a activar su app de autenticación, el secreto no cambia, solo la clave
con la que se guarda.
"""

from ..config import claves_anteriores_2fa
from ..seguridad.bitacora import registrar_evento
from ..seguridad.totp import CifradoSecretos
from .comun import abrir_db, configuracion, correr


async def principal() -> None:
    config = configuracion()
    if not config.CLAVE_CIFRADO_2FA:
        raise RuntimeError("Falta CLAVE_CIFRADO_2FA")
    cifrado = CifradoSecretos(config.CLAVE_CIFRADO_2FA, claves_anteriores_2fa(config))
    db = await abrir_db(config)
    try:
        async with db.transaccion() as c:
            r = await c.query("SELECT usuario_id, secreto_cifrado FROM usuarios_2fa FOR UPDATE")
            recifrados = 0
            for f in r.rows:
                blob = bytes(f["secreto_cifrado"])
                if not cifrado.necesita_recifrar(blob):
                    continue
                secreto = cifrado.descifrar(blob, f["usuario_id"])
                await c.query(
                    "UPDATE usuarios_2fa SET secreto_cifrado = $2 WHERE usuario_id = $1", [f["usuario_id"], cifrado.cifrar(secreto, f["usuario_id"])]
                )
                recifrados += 1
            revisados = len(r.rows)
        await registrar_evento(db, "clave_2fa_rotada", detalles={"revisados": revisados, "recifrados": recifrados})
        print(f"Listo. {revisados} secretos revisados, {recifrados} cifrados de nuevo con la clave actual")
        if revisados:
            print("Ya puedes quitar CLAVES_CIFRADO_2FA_ANTERIORES de .env y reiniciar la API")
    finally:
        await db.cerrar()


if __name__ == "__main__":
    correr(principal)
