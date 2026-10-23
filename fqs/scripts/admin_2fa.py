"""
Soporte para cuando una persona de administración pierde el teléfono y sus códigos de
respaldo. Borra su segundo factor y cierra todas sus sesiones. Al volver a entrar con su
contraseña tendrá que activarlo otra vez antes de poder administrar. Solo lo puede correr
alguien con acceso al servidor, y queda en la bitácora.
Uso  python -m fqs.scripts.admin_2fa
"""

from ..seguridad.bitacora import registrar_evento
from ..seguridad.segundo_factor import SegundoFactor
from ..seguridad.sesiones import revocar_todas
from .comun import abrir_db, configuracion, correr


async def principal() -> None:
    config = configuracion()
    db = await abrir_db(config)
    try:
        correo = input("Correo de la cuenta de administración ").strip().lower()
        r = await db.query("SELECT id, username, rol FROM usuarios WHERE lower(correo) = $1", [correo])
        u = r.rows[0] if r.rows else None
        if not u or u["rol"] != "admin":
            raise RuntimeError("No hay una cuenta de administración con ese correo")
        ok = input(f"Se borrará el segundo factor de @{u['username']} y se cerrarán sus sesiones. Escribe SI para continuar ").strip()
        if ok != "SI":
            raise RuntimeError("Cancelado, no se cambió nada")
        sf = SegundoFactor(db, None)
        async with db.transaccion() as c:
            await sf.reiniciar(c, u["id"])
            await revocar_todas(c, u["id"])
        await registrar_evento(db, "2fa_reiniciado", actor_id=u["id"], actor_rol="admin", detalles={"origen": "script de soporte"})
        print(f"Listo. @{u['username']} debe iniciar sesión y activar su app de autenticación de nuevo")
    finally:
        await db.cerrar()


if __name__ == "__main__":
    correr(principal)
