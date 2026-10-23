"""
Tareas periódicas de seguridad.
  revisar_bitacora   lee los eventos nuevos y manda los avisos que correspondan
  anclar             cada ANCLA_CADA_DIAS verifica la cadena y manda el último hash por correo
  revisar_inactivas  aplica la política de cuentas sin uso
Cada una guarda su avance en tareas_estado, así un reinicio no repite ni pierde avisos.
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import Config, correos_alerta
from .correo import Correo
from .db import Db
from .jsonfmt import iso
from .log import log

# Umbrales dentro de una ventana de 15 minutos por la misma cuenta
UMBRALES = {
    "2fa_fallido": (
        5,
        "Varios códigos de verificación equivocados",
        "Se escribieron 5 o más códigos de verificación equivocados en una cuenta de administración en 15 minutos. Alguien podría conocer su contraseña.",
    ),
    "login_admin_fallido": (
        5,
        "Varios intentos de entrar a una cuenta de administración",
        "Hubo 5 o más contraseñas equivocadas para una cuenta de administración en 15 minutos.",
    ),
    "acceso_denegado": (
        5,
        "Una cuenta de familia intentó usar la administración",
        "Una cuenta sin permisos intentó usar rutas de administración 5 o más veces en 15 minutos.",
    ),
    "requiere_2fa": (
        10,
        "Intentos de administrar sin segundo factor",
        "Una sesión de administración sin verificación en dos pasos intentó usar rutas de administración 10 o más veces en 15 minutos.",
    ),
}

# Eventos que siempre generan un aviso (asunto, texto, a todas las cuentas de administración, a quien lo hizo)
INMEDIATOS = {
    "login_admin": (
        "Nuevo inicio de sesión en tu cuenta de administración",
        "Se inició sesión en tu cuenta de administración sin verificación en dos pasos.",
        False,
        True,
    ),
    "2fa_correcto": (
        "Nuevo inicio de sesión en tu cuenta de administración",
        "Se inició sesión en tu cuenta de administración con contraseña y código.",
        False,
        True,
    ),
    "2fa_codigo_respaldo_usado": (
        "Se usó un código de respaldo",
        "Alguien entró a una cuenta de administración con un código de respaldo. Si fue por pérdida del teléfono, conviene generar códigos nuevos.",
        True,
        True,
    ),
    "2fa_activado": (
        "Verificación en dos pasos activada",
        "Una cuenta de administración activó su verificación en dos pasos.",
        False,
        True,
    ),
    "2fa_reiniciado": (
        "Se reinició la verificación en dos pasos de una cuenta",
        "Desde el servidor se borró la verificación en dos pasos de una cuenta de administración. Debe volver a activarla.",
        True,
        True,
    ),
    "2fa_codigos_regenerados": (
        "Códigos de respaldo nuevos",
        "Se generaron códigos de respaldo nuevos para tu cuenta. Los anteriores ya no sirven.",
        False,
        True,
    ),
    "refresh_reutilizado": (
        "Cerramos tus sesiones por seguridad",
        "Detectamos que alguien intentó usar una sesión vieja de tu cuenta, lo que puede significar que se copió. Cerramos todas tus sesiones. Vuelve a entrar y, si no reconoces la actividad, cambia tu contraseña.",
        False,
        True,
    ),
    "contrasena_restablecida": (
        "Tu contraseña cambió",
        "La contraseña de tu cuenta se cambió con un código de recuperación y se cerraron todas tus sesiones. Si no fuiste tú, escríbenos de inmediato.",
        False,
        True,
    ),
}

_MONTERREY = ZoneInfo("America/Monterrey")


class Vigilancia:
    def __init__(self, db: Db, correo: Correo, config: Config) -> None:
        self.db = db
        self.correo = correo
        self.config = config

    async def _leer_estado(self, clave: str) -> str | None:
        r = await self.db.query("SELECT valor FROM tareas_estado WHERE clave = $1", [clave])
        return r.rows[0]["valor"] if r.rows else None

    async def _guardar_estado(self, clave: str, valor: str) -> None:
        await self.db.query(
            """INSERT INTO tareas_estado (clave, valor) VALUES ($1, $2)
               ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado_en = now()""",
            [clave, valor],
        )

    async def _destinatarios_admin(self) -> list[str]:
        """Cuentas de administración activas más ALERTAS_CORREO."""
        r = await self.db.query(
            "SELECT lower(correo) AS correo FROM usuarios WHERE rol = 'admin' AND estado = 'activo' AND correo IS NOT NULL"
        )
        return list(dict.fromkeys([f["correo"] for f in r.rows] + correos_alerta(self.config)))

    async def _correo_de(self, usuario_id: str | None) -> str | None:
        if not usuario_id:
            return None
        r = await self.db.query("SELECT correo FROM usuarios WHERE id = $1 AND correo_verificado_en IS NOT NULL", [usuario_id])
        return r.rows[0]["correo"] if r.rows else None

    async def _alertar(self, regla: str, clave: str, destinos: list[str], asunto: str, parrafos: list[str], detalle: dict) -> bool:
        """Manda el aviso salvo que la misma regla y clave ya se haya avisado en la última hora."""
        reciente = await self.db.query(
            "SELECT 1 FROM alertas_seguridad WHERE regla = $1 AND clave = $2 AND creado_en > now() - interval '1 hour'",
            [regla, clave],
        )
        if reciente.rows:
            return False
        enviados = 0
        for d in dict.fromkeys(x for x in destinos if x):
            try:
                await self.correo.enviar_aviso(d, asunto, parrafos)
                enviados += 1
            except Exception as e:  # noqa: BLE001
                log.error("No se pudo enviar una alerta de seguridad", {"regla": regla, "error": str(e)})
        await self.db.query(
            "INSERT INTO alertas_seguridad (regla, clave, detalle, destinatarios) VALUES ($1, $2, $3, $4)",
            [regla, clave[:120], json.dumps(detalle), enviados],
        )
        return True

    @staticmethod
    def _detalle_evento(e: dict) -> list[str]:
        cuando = e["creado_en"].astimezone(_MONTERREY).strftime("%d/%m/%Y, %H:%M:%S")
        lineas = [f"Fecha y hora {cuando} (hora de Monterrey)."]
        if e["ip"]:
            lineas.append(f"Dirección IP {e['ip']}.")
        detalles = e["detalles"] or {}
        if isinstance(detalles.get("dispositivo"), str):
            lineas.append(f"Dispositivo {detalles['dispositivo']}.")
        lineas.append(f"Evento número {e['id']} de la bitácora de seguridad.")
        return lineas

    async def revisar_bitacora(self) -> int:
        cursor = int(await self._leer_estado("bitacora_cursor") or "0")
        r = await self.db.query(
            """SELECT id::text, accion, actor_id, actor_rol, ip, ruta, detalles, creado_en
               FROM bitacora_seguridad WHERE id > $1 ORDER BY id LIMIT 500""",
            [cursor],
        )
        avisos = 0
        admins = await self._destinatarios_admin() if r.rows else []
        for e in r.rows:
            inmediato = INMEDIATOS.get(e["accion"])
            if inmediato:
                asunto, texto, a_todos, al_actor = inmediato
                destinos = [*(admins if a_todos else []), *([(await self._correo_de(e["actor_id"])) or ""] if al_actor else [])]
                if await self._alertar(
                    e["accion"],
                    f"evento {e['id']}",
                    destinos,
                    asunto,
                    [texto, *self._detalle_evento(e), "Si no reconoces esta actividad, avisa al equipo de inmediato."],
                    {"eventoId": e["id"]},
                ):
                    avisos += 1
            umbral = UMBRALES.get(e["accion"])
            if umbral and e["actor_id"]:
                veces, asunto, texto = umbral
                n = await self.db.query(
                    """SELECT count(*) AS n FROM bitacora_seguridad
                       WHERE accion = $1 AND actor_id = $2 AND creado_en > $3::timestamptz - interval '15 minutes' AND id <= $4""",
                    [e["accion"], e["actor_id"], e["creado_en"], int(e["id"])],
                )
                total = int(n.rows[0]["n"])
                if total >= veces:
                    destinos = [*admins, *([] if e["accion"] == "acceso_denegado" else [(await self._correo_de(e["actor_id"])) or ""])]
                    if await self._alertar(
                        f"umbral {e['accion']}",
                        e["actor_id"],
                        destinos,
                        asunto,
                        [texto, f"Cuenta {e['actor_id']}.", *self._detalle_evento(e)],
                        {"eventoId": e["id"], "veces": total},
                    ):
                        avisos += 1
        if r.rows:
            await self._guardar_estado("bitacora_cursor", r.rows[-1]["id"])
        return avisos

    async def anclar(self, forzar: bool = False) -> dict | None:
        """
        Verifica la cadena y manda el último hash a las cuentas de administración y a
        ALERTAS_CORREO. Esa copia fuera del servidor es la que permite demostrar después que
        nadie rehízo la bitácora. Si la cadena no cuadra, el aviso es urgente.
        """
        ultima = await self._leer_estado("ultima_ancla")
        if ultima and not forzar:
            dias = (datetime.now(timezone.utc) - datetime.fromisoformat(ultima.replace("Z", "+00:00"))).total_seconds() / 86_400
            if dias < self.config.ANCLA_CADA_DIAS:
                return None
        v = await self.db.query("SELECT * FROM verificar_bitacora()")
        f = v.rows[0]
        hasta = await self.db.query("SELECT max(id)::text AS id FROM bitacora_seguridad")
        hasta_id = hasta.rows[0]["id"] if hasta.rows else None
        destinos = await self._destinatarios_admin()
        if f["valida"]:
            asunto = "Ancla semanal de la bitácora de seguridad"
            parrafos = [
                "Guarda este correo. Sirve para comprobar más adelante que nadie modificó la bitácora de seguridad.",
                f"Último evento {hasta_id or 'ninguno'}.",
                f"Hash {f['ultimo_hash'] or 'sin eventos'}.",
                f"Eventos revisados {f['revisadas']}, la cadena está completa.",
                "Para comprobarlo, en el panel ve a Seguridad y usa Comprobar contra un ancla con el número y el hash de este correo.",
            ]
        else:
            asunto = "URGENTE, la bitácora de seguridad fue alterada"
            parrafos = [
                f"La verificación encontró una fila alterada o borrada, la primera es la {f['primer_error']}.",
                "Revisa quién tuvo acceso al servidor de base de datos y conserva una copia de la base antes de tocar nada.",
            ]
        enviados = 0
        for d in destinos:
            try:
                await self.correo.enviar_aviso(d, asunto, parrafos)
                enviados += 1
            except Exception as e:  # noqa: BLE001
                log.error("No se pudo enviar el ancla de la bitácora", {"error": str(e)})
        await self.db.query(
            "INSERT INTO anclas_bitacora (hasta_id, hash, revisadas, valida, destinatarios) VALUES ($1, $2, $3, $4, $5)",
            [int(hasta_id) if hasta_id else None, f["ultimo_hash"], int(f["revisadas"]), f["valida"], enviados],
        )
        await self._guardar_estado("ultima_ancla", iso(datetime.now(timezone.utc)) or "")
        if not f["valida"]:
            log.error("La bitácora de seguridad no pasó la verificación", {"primerError": f["primer_error"]})
        return {"hastaId": hasta_id, "hash": f["ultimo_hash"], "valida": f["valida"], "destinatarios": enviados}

    async def revisar_inactivas(self) -> dict:
        """
        Política de cuentas sin uso (minimización de datos, LFPDPPP).
          1. Una cuenta de familia sin entrar en CUENTAS_INACTIVAS_MESES recibe un aviso por correo.
          2. Si 30 días después sigue sin entrar, se crea una solicitud de eliminación con origen
             inactividad. El equipo la atiende igual que las demás (anonimiza y borra fotos).
        Entrar a la app en cualquier momento cancela el aviso y la solicitud.
        """
        meses = self.config.CUENTAS_INACTIVAS_MESES
        nuevas = await self.db.query(
            """SELECT u.id, CASE WHEN u.correo_verificado_en IS NOT NULL THEN u.correo END AS correo
               FROM usuarios u
               WHERE u.rol = 'familia' AND u.estado = 'activo' AND u.ultimo_acceso_en < now() - make_interval(months => $1)
                 AND NOT EXISTS (SELECT 1 FROM avisos_inactividad a WHERE a.usuario_id = u.id)
               LIMIT 200""",
            [meses],
        )
        for u in nuevas.rows:
            await self.db.query("INSERT INTO avisos_inactividad (usuario_id) VALUES ($1) ON CONFLICT DO NOTHING", [u["id"]])
            if u["correo"]:
                try:
                    await self.correo.enviar_aviso(
                        u["correo"],
                        "Tu cuenta se eliminará por falta de uso",
                        [
                            f"No has entrado a Familias que Suman en {meses} meses. Para cuidar tus datos, eliminaremos tu cuenta en 30 días.",
                            "Si quieres conservarla, solo abre la app e inicia sesión antes de esa fecha.",
                        ],
                    )
                except Exception as e:  # noqa: BLE001
                    log.error("No se pudo enviar el aviso de inactividad", {"error": str(e)})
        vencidas = await self.db.query(
            """INSERT INTO solicitudes_eliminacion (usuario_id, origen)
               SELECT a.usuario_id, 'inactividad' FROM avisos_inactividad a JOIN usuarios u ON u.id = a.usuario_id
               WHERE a.enviado_en < now() - interval '30 days' AND u.estado = 'activo' AND u.ultimo_acceso_en < a.enviado_en
                 AND NOT EXISTS (SELECT 1 FROM solicitudes_eliminacion s WHERE s.usuario_id = a.usuario_id AND s.estado <> 'resuelta')
               RETURNING usuario_id"""
        )
        return {"avisadas": len(nuevas.rows), "solicitudes": len(vencidas.rows)}
