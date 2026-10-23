"""
Carga datos de prueba con apariencia real para desarrollar y hacer demos. Los datos están en
datos_prueba.json junto a este archivo.

Las asociaciones son ficticias. Los lugares sí son espacios públicos de Monterrey, pero los
teléfonos y correos son de rangos reservados para que tocar Llamar, WhatsApp o Correo en la app
nunca contacte a una persona real. Las fechas se calculan a partir de hoy, así que siempre
quedan en el futuro.

Se puede correr varias veces. Cada elemento se busca por su nombre y solo se crea si falta, así
que al actualizar los datos se agregan las novedades sin duplicar nada. Las actividades que ya
terminaron y no tienen inscripciones se mueven a fechas nuevas.
Uso  python -m fqs.scripts.datos_prueba
"""

import json
from pathlib import Path

from .comun import abrir_db, configuracion, correr

DATOS = json.loads((Path(__file__).parent / "datos_prueba.json").read_text(encoding="utf-8"))


def _inicio_sql(b: int) -> str:
    """Inicio a partir de cinco parámetros seguidos desde $b, lunes base, semana, día, hora y minutos."""
    return f"((((${b}::date + (${b + 1}::int * 7) + (${b + 2}::int - 1)) + ${b + 3}::time) AT TIME ZONE 'America/Monterrey'))"


def _fin_sql(b: int) -> str:
    return f"{_inicio_sql(b)} + make_interval(mins => ${b + 4}::int)"


async def principal() -> None:
    db = await abrir_db(configuracion())
    cuenta = dict.fromkeys(["asociaciones", "actividades", "actualizadas", "campanas", "proyectos", "encuestas", "niveles", "insignias"], 0)
    try:
        async with db.transaccion() as c:
            admin = await c.query("SELECT id FROM usuarios WHERE rol = 'admin' AND estado = 'activo' ORDER BY creado_en LIMIT 1")
            if not admin.rows:
                raise RuntimeError("No hay una cuenta admin activa, corre primero  python -m fqs.scripts.crear_admin")
            admin_id = admin.rows[0]["id"]
            ciudad = await c.query("SELECT id FROM ciudades WHERE nombre = 'Monterrey' LIMIT 1")
            if not ciudad.rows:
                raise RuntimeError("No existe la ciudad Monterrey, revisa db/02_catalogos.sql")
            ciudad_id = ciudad.rows[0]["id"]
            categoria = {f["clave"]: f["id"] for f in (await c.query("SELECT id, clave FROM categorias")).rows}

            # Lunes de la próxima semana en hora de Monterrey, base de todas las fechas
            base = await c.query(
                """SELECT (d + (8 - extract(isodow FROM d)::int))::text AS lunes
                   FROM (SELECT (now() AT TIME ZONE 'America/Monterrey')::date AS d) x"""
            )
            lunes = base.rows[0]["lunes"]

            # ---------------- Asociaciones ----------------
            asoc_ids: dict[str, str] = {}
            for a in DATOS["asociaciones"]:
                existe = await c.query("SELECT id FROM asociaciones WHERE nombre = $1", [a["nombre"]])
                if existe.rows:
                    asoc_ids[a["clave"]] = existe.rows[0]["id"]
                    continue
                r = await c.query(
                    """INSERT INTO asociaciones (nombre, descripcion, mision, necesidades, familias_beneficiadas, categoria_id, ciudad_id,
                         direccion, latitud, longitud, telefono, whatsapp, correo, verificada, creado_por)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$11,$12,$13,$14) RETURNING id""",
                    [a["nombre"], a["descripcion"], a["mision"], a["necesidades"], a["familias"], categoria[a["categoria"]], ciudad_id,
                     a["direccion"], a["lat"], a["lon"], a["telefono"], a["correo"], a["verificada"], admin_id],
                )  # fmt: skip
                asoc_ids[a["clave"]] = r.rows[0]["id"]
                cuenta["asociaciones"] += 1

            # ---------------- Actividades ----------------
            categoria_de = {a["clave"]: a["categoria"] for a in DATOS["asociaciones"]}
            for act in DATOS["actividades"]:
                asociacion_id = asoc_ids[act["asociacion"]]
                tipo = act.get("tipo") or "voluntariado"
                fechas = [lunes, act["semana"], act["diaSemana"], act["hora"], act["minutos"]]
                existe = await c.query("SELECT id FROM actividades WHERE asociacion_id = $1 AND titulo = $2", [asociacion_id, act["titulo"]])
                if existe.rows:
                    # Actualiza el tipo y, si ya pasó y nadie se inscribió, la mueve a la fecha
                    # nueva para que siga en la demo
                    r = await c.query(
                        f"""UPDATE actividades SET
                              tipo = $2,
                              inicio = CASE WHEN fin < now() AND NOT EXISTS (SELECT 1 FROM inscripciones i WHERE i.actividad_id = $1)
                                            THEN {_inicio_sql(3)} ELSE inicio END,
                              fin = CASE WHEN fin < now() AND NOT EXISTS (SELECT 1 FROM inscripciones i WHERE i.actividad_id = $1)
                                         THEN {_fin_sql(3)} ELSE fin END
                            WHERE id = $1 AND (tipo <> $2 OR fin < now())""",
                        [existe.rows[0]["id"], tipo, *fechas],
                    )
                    cuenta["actualizadas"] += r.rowcount or 0
                    continue
                # Los cupos ocupados se fijan directo para que la demo se vea con movimiento. Las
                # inscripciones reales que se hagan desde la app se suman sobre esto
                await c.query(
                    f"""INSERT INTO actividades (asociacion_id, categoria_id, ciudad_id, titulo, descripcion_corta, descripcion, recomendaciones,
                          inicio, fin, direccion, latitud, longitud, apta_ninos, edad_minima, cupo_total, cupos_ocupados, estado, tipo, creado_por)
                        VALUES ($1,$2,$3,$4,$5,$6,$7, {_inicio_sql(8)}, {_fin_sql(8)},
                          $13,$14,$15,$16,$17,$18,$19,'publicada',$21,$20)""",
                    [asociacion_id, categoria[categoria_de[act["asociacion"]]], ciudad_id, act["titulo"], act["corta"], act["descripcion"],
                     act["recomendaciones"], *fechas, act["direccion"], act["lat"], act["lon"],
                     act["aptaNinos"], act["edadMinima"], act["cupo"], act["ocupados"], admin_id, tipo],
                )  # fmt: skip
                cuenta["actividades"] += 1

            # ---------------- Proyectos ----------------
            proy_ids: dict[str, str] = {}
            for p in DATOS["proyectos"]:
                existe = await c.query("SELECT id FROM proyectos WHERE titulo = $1", [p["titulo"]])
                if existe.rows:
                    proy_ids[p["clave"]] = existe.rows[0]["id"]
                    continue
                r = await c.query(
                    """INSERT INTO proyectos (asociacion_id, ciudad_id, titulo, descripcion, fecha_inicio, fecha_fin, estado, creado_por)
                       VALUES ($1, $2, $3, $4, current_date - $5::int,
                               CASE WHEN $6::int IS NULL THEN NULL ELSE current_date + $6::int END, 'publicado', $7)
                       RETURNING id""",
                    [asoc_ids[p["asociacion"]], ciudad_id, p["titulo"], p["descripcion"], p["diasDesdeInicio"], p["diasParaTerminar"], admin_id],
                )
                proy_ids[p["clave"]] = r.rows[0]["id"]
                cuenta["proyectos"] += 1

            # ---------------- Campañas ----------------
            for cp in DATOS["campanas"]:
                asociacion_id = asoc_ids[cp["asociacion"]]
                proyecto_id = proy_ids[cp["proyecto"]] if cp.get("proyecto") else None
                existe = await c.query("SELECT id FROM campanas WHERE asociacion_id = $1 AND titulo = $2", [asociacion_id, cp["titulo"]])
                if existe.rows:
                    # Campañas cargadas antes de que existieran los proyectos se ligan ahora
                    if proyecto_id:
                        await c.query("UPDATE campanas SET proyecto_id = $2 WHERE id = $1 AND proyecto_id IS NULL", [existe.rows[0]["id"], proyecto_id])
                    continue
                r = await c.query(
                    """INSERT INTO campanas (asociacion_id, proyecto_id, ciudad_id, titulo, descripcion, inicio, fin, urgente, estado, creado_por)
                       VALUES ($1, $2, $3, $4, $5, now() - interval '5 days', now() + make_interval(days => $6::int), $7, 'publicada', $8)
                       RETURNING id""",
                    [asociacion_id, proyecto_id, ciudad_id, cp["titulo"], cp["descripcion"], cp["diasRestantes"], cp["urgente"], admin_id],
                )
                campana_id = r.rows[0]["id"]
                for ar in cp["articulos"]:
                    await c.query(
                        """INSERT INTO campana_articulos (campana_id, nombre, descripcion, unidad, cantidad_meta, cantidad_recibida, prioridad)
                           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                        [campana_id, ar["nombre"], ar["descripcion"], ar["unidad"], ar["meta"], ar["recibido"], ar["prioridad"]],
                    )
                for pe in cp["puntos"]:
                    await c.query(
                        """INSERT INTO puntos_entrega (campana_id, ciudad_id, nombre, direccion, horarios, indicaciones, latitud, longitud)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                        [campana_id, ciudad_id, pe["nombre"], pe["direccion"], pe["horarios"], pe["indicaciones"], pe["lat"], pe["lon"]],
                    )
                cuenta["campanas"] += 1

            # ---------------- Encuestas ----------------
            for enc in DATOS["encuestas"]:
                act = await c.query("SELECT id FROM actividades WHERE titulo = $1 LIMIT 1", [enc["actividad"]])
                if not act.rows:
                    continue
                nueva = await c.query(
                    """INSERT INTO encuestas (actividad_id, titulo, momento) VALUES ($1, $2, $3)
                       ON CONFLICT (actividad_id, momento) DO NOTHING RETURNING id""",
                    [act.rows[0]["id"], enc["titulo"], enc["momento"]],
                )
                if not nueva.rows:
                    continue
                encuesta_id = nueva.rows[0]["id"]
                for i, p in enumerate(enc["preguntas"]):
                    q = await c.query(
                        "INSERT INTO preguntas_encuesta (encuesta_id, texto, tipo, obligatoria, orden) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                        [encuesta_id, p["texto"], "opcion_unica" if p["opciones"] else "texto", p.get("obligatoria", True), i + 1],
                    )
                    for j, o in enumerate(p["opciones"]):
                        await c.query("INSERT INTO opciones_pregunta (pregunta_id, texto, orden) VALUES ($1, $2, $3)", [q.rows[0]["id"], o, j + 1])
                cuenta["encuestas"] += 1

            # ---------------- Niveles e insignias ----------------
            for nv in DATOS["niveles"]:
                r = await c.query(
                    "INSERT INTO niveles (nombre, descripcion, participaciones_minimas) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                    [nv["nombre"], nv["descripcion"], nv["minimas"]],
                )
                cuenta["niveles"] += r.rowcount or 0
            for ins in DATOS["insignias"]:
                r = await c.query(
                    "INSERT INTO insignias (nombre, descripcion, categoria_id, participaciones_requeridas) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    [ins["nombre"], ins["descripcion"], categoria[ins["categoria"]] if ins["categoria"] else None, ins["requeridas"]],
                )
                cuenta["insignias"] += r.rowcount or 0
    finally:
        await db.cerrar()
    n = cuenta
    print(
        f"Listo. Nuevos {n['asociaciones']} asociaciones, {n['actividades']} actividades, {n['proyectos']} proyectos, "
        f"{n['campanas']} campañas, {n['encuestas']} encuestas, {n['niveles']} niveles y {n['insignias']} insignias. "
        f"Actividades existentes actualizadas {n['actualizadas']}. Las actividades nuevas empiezan la semana del {lunes}"
    )


if __name__ == "__main__":
    correr(principal)
