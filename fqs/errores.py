"""
Errores controlados. Su mensaje sí se muestra al cliente. Cualquier otro error se responde
como 500 genérico y el detalle queda solo en la bitácora del servidor.
"""

from typing import Any

import psycopg


class HttpError(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, detalles: Any = None) -> None:
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles


def no_encontrado(que: str = "Recurso") -> HttpError:
    return HttpError(404, "no_encontrado", f"{que} no encontrado")


def prohibido() -> HttpError:
    return HttpError(403, "prohibido", "No tienes permiso para esta acción")


def no_autenticado() -> HttpError:
    return HttpError(401, "no_autenticado", "Sesión inválida o expirada")


# Mensajes para restricciones con nombre definidas en db/01_esquema.sql
_MENSAJES_UNICOS = {
    "usuarios_correo_uq": "Ese correo ya está registrado",
    "usuarios_username_uq": "Ese username ya está en uso",
    "usuarios_telefono_uq": "Ese teléfono ya está registrado",
    "inscripciones_usuario_id_actividad_id_key": "Ya tienes una inscripción para esta actividad",
    "testimonios_inscripcion_id_key": "Ya publicaste un testimonio para esta actividad",
    "respuestas_encuesta_inscripcion_id_pregunta_id_key": "Ya respondiste esta pregunta",
    "una_solicitud_abierta": "Ya tienes una solicitud de eliminación en curso",
    "categorias_clave_key": "Ya existe una categoría con esa clave",
    "avisos_privacidad_version_key": "Ya existe un aviso con esa versión",
    "insignias_nombre_key": "Ya existe una insignia con ese nombre",
    "niveles_nombre_key": "Ya existe un nivel con ese nombre",
    "niveles_participaciones_minimas_key": "Ya existe un nivel con ese número de participaciones",
}

_MENSAJES_CHECK = {
    "usuarios_solo_individual": "Solo se permiten cuentas individuales",
    "usuarios_requiere_contacto": "Se requiere un correo o un teléfono",
    "usuarios_telefono_check": "Teléfono inválido",
    "miembros_comunidad_telefono_check": "Teléfono inválido",
    "actividades_apta_ninos_edad": "Una actividad apta para niños no puede pedir 18 años o más",
    "actividades_check2": "La fecha de fin debe ser posterior al inicio",
    "actividades_cupos_ocupados_check": "El cupo no puede ser menor que los lugares ya ocupados",
    "campanas_requiere_origen": "La campaña debe pertenecer a una asociación o a un proyecto",
    "reportes_objetivo_actividad": "Indica la actividad que quieres reportar",
    "reportes_objetivo_asociacion": "Indica la asociación que quieres reportar",
    "reportes_objetivo_campana": "Indica la campaña que quieres reportar",
    "reportes_aplicacion_sin_objetivo": "Un problema de la aplicación no lleva actividad, asociación ni campaña",
    "reportes_un_objetivo": "Un reporte solo puede referirse a un elemento",
}


def traducir_error_pg(e: BaseException) -> HttpError | None:
    """Convierte errores de PostgreSQL en respuestas HTTP sin filtrar detalles internos."""
    if isinstance(e, psycopg.DataError) and not getattr(e, "sqlstate", None):
        # Errores que psycopg detecta antes de mandar la consulta, por ejemplo un texto con
        # el carácter nulo. La validación ya los rechaza, esto es la última barrera
        return HttpError(400, "formato_invalido", "Formato de dato inválido")
    if not isinstance(e, psycopg.Error) or not getattr(e, "sqlstate", None):
        return None
    codigo = e.sqlstate
    restriccion = e.diag.constraint_name or ""
    if codigo == "23505":
        return HttpError(409, "duplicado", _MENSAJES_UNICOS.get(restriccion, "El registro ya existe"))
    if codigo == "23514":
        return HttpError(422, "invalido", _MENSAJES_CHECK.get(restriccion, "Los datos no cumplen las reglas"))
    if codigo == "23503":
        return HttpError(422, "referencia_invalida", "Uno de los elementos referidos no existe o está en uso")
    if codigo == "23502":
        return HttpError(422, "invalido", "Falta un dato obligatorio")
    if codigo == "P0001":
        # Mensajes escritos por nosotros en las funciones y triggers del esquema
        return HttpError(409, "regla_de_negocio", e.diag.message_primary or "Regla de negocio")
    if codigo in ("22P02", "22007", "22008", "22003"):
        return HttpError(400, "formato_invalido", "Formato de dato inválido")
    if codigo in ("40001", "40P01", "55P03"):
        return HttpError(503, "reintentar", "El servidor está ocupado, intenta de nuevo")
    if codigo == "57014":
        return HttpError(503, "tiempo_agotado", "La operación tardó demasiado")
    return None
