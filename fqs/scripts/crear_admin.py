"""
Crea la cuenta de administración, o le restablece la contraseña si ya existe una cuenta admin
con ese correo. La contraseña se escribe dos veces sin mostrarse y nunca se pasa como argumento
(no queda en el historial de la terminal).
Uso  python -m fqs.scripts.crear_admin
"""

import getpass

from ..seguridad.contrasenas import hash_contrasena, problema_contrasena
from ..seguridad.filtradas import RevisorFiltradas
from ..seguridad.sesiones import revocar_todas
from .comun import abrir_db, configuracion, correr


async def principal() -> None:
    config = configuracion()
    db = await abrir_db(config)
    try:
        correo = input("Correo ").strip().lower()
        r = await db.query("SELECT id, nombre, username, rol FROM usuarios WHERE lower(correo) = $1", [correo])
        cuenta = r.rows[0] if r.rows else None
        if cuenta and cuenta["rol"] != "admin":
            raise RuntimeError("Ese correo pertenece a una cuenta de familia, no se modifica desde aquí")
        if cuenta:
            nombre, username = cuenta["nombre"], cuenta["username"]
            print(f"Ya existe la cuenta admin @{username}, se va a restablecer su contraseña")
        else:
            nombre = input("Nombre completo ").strip()
            username = input("Username ").strip()

        clave = getpass.getpass("Contraseña (no se muestra) ")
        confirmacion = getpass.getpass("Repite la contraseña ")
        # Solo se muestra la longitud, para comparar con lo que se escribió
        print(f"Se capturaron {len(clave)} caracteres")
        if clave != confirmacion:
            raise RuntimeError("Las contraseñas no coinciden, no se guardó nada")
        problema = problema_contrasena(clave, [nombre, username, correo])
        if problema:
            raise RuntimeError(problema)
        if len(clave) < 14:
            raise RuntimeError("Para una cuenta de administración usa al menos 14 caracteres")
        veces = await RevisorFiltradas(config.CONTRASENAS_FILTRADAS == "revisar").veces(clave)
        if veces:
            raise RuntimeError("Esa contraseña aparece en filtraciones de datos conocidas, elige otra")
        if veces is None:
            print("Aviso, no se pudo consultar Pwned Passwords")

        h = await hash_contrasena(clave)
        if cuenta:
            await db.query("UPDATE usuarios SET password_hash = $1 WHERE id = $2", [h, cuenta["id"]])
            await revocar_todas(db, cuenta["id"])
            print(f"Contraseña restablecida para @{username}")
        else:
            n = await db.query(
                # El correo lo escribió quien administra el servidor, se toma como verificado
                """INSERT INTO usuarios (nombre, username, correo, password_hash, rol, tipo_cuenta, correo_verificado_en)
                   VALUES ($1, $2, $3, $4, 'admin', 'individual', now()) RETURNING id""",
                [nombre, username, correo, h],
            )
            print(f"Administrador creado con id {n.rows[0]['id']}")
    finally:
        await db.cerrar()


if __name__ == "__main__":
    correr(principal)
