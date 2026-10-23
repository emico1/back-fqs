-- Familias que Suman | Migración fase 2 | PostgreSQL 16+
-- Ejecutar después de 05_fase1.sql. Solo agrega o modifica, no borra datos.
--
-- Cambios
--   Avisos automáticos (RF16 y RF20). Cuando una asociación favorita publica algo, o
--   aparece una actividad de un tema que le interesa a la familia, se crea una
--   notificación. Los recordatorios previos y las invitaciones a encuestas también.
--   Envío push. Cada notificación nueva avisa por el canal fqs_notificaciones para que
--   el backend la mande por Firebase. push_enviada_en evita mandarla dos veces.
--   Nombres normalizados para detectar asociaciones repetidas al proponer (CP-01).
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;
-- Oculta los avisos de índices que ya existen al final del script
SET LOCAL client_min_messages = warning;

-- ============================================================
-- Envío push de notificaciones
-- ============================================================

ALTER TABLE notificaciones ADD COLUMN push_enviada_en timestamptz;
-- Las notificaciones viejas ya no se mandan por push al activar esta función
UPDATE notificaciones SET push_enviada_en = creado_en WHERE push_enviada_en IS NULL;
CREATE INDEX notificaciones_push_pendiente ON notificaciones(creado_en) WHERE push_enviada_en IS NULL;

CREATE FUNCTION avisar_notificacion() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 -- Solo viaja el id, el backend lee el contenido con sus propios permisos
 PERFORM pg_notify('fqs_notificaciones', NEW.id::text);
 RETURN NULL;
END $$;
CREATE TRIGGER avisar_notificacion AFTER INSERT ON notificaciones
FOR EACH ROW EXECUTE FUNCTION avisar_notificacion();

-- ============================================================
-- Avisos al publicar (RF20 favoritos y RF16 sugerencias)
-- ============================================================

-- Al publicar una actividad de una asociación verificada
--   1. Avisa a quien marcó la asociación como favorita con avisos activos.
--   2. Sugiere la actividad a quien tiene ese tema entre sus intereses, vive en esa
--      ciudad y acepta sugerencias. Máximo una sugerencia al día por persona.
-- Solo a cuentas activas de familia y de la misma ciudad (RF-02).
CREATE FUNCTION avisar_actividad_publicada() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE aso asociaciones%ROWTYPE;
BEGIN
 IF NEW.estado <> 'publicada' OR (TG_OP = 'UPDATE' AND OLD.estado = 'publicada') OR NEW.inicio <= now() THEN
  RETURN NULL;
 END IF;
 SELECT * INTO aso FROM asociaciones WHERE id = NEW.asociacion_id;
 IF NOT aso.verificada OR NOT aso.activa THEN RETURN NULL; END IF;

 INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, actividad_id)
 SELECT f.usuario_id, 'nueva_actividad',
        aso.nombre || ' publicó una actividad',
        NEW.titulo || '. ' || NEW.descripcion_corta,
        NEW.id
 FROM favoritos_asociaciones f
 JOIN usuarios u ON u.id = f.usuario_id
 WHERE f.asociacion_id = NEW.asociacion_id AND f.notificaciones_activas
   AND u.estado = 'activo' AND u.rol = 'familia' AND u.ciudad_id = NEW.ciudad_id;

 INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, actividad_id)
 SELECT u.id, 'sugerencia',
        CASE WHEN NEW.tipo = 'visita' THEN 'Una visita que te puede gustar' ELSE 'Una actividad que te puede gustar' END,
        NEW.titulo || ' con ' || aso.nombre || '. ' || NEW.descripcion_corta,
        NEW.id
 FROM usuarios u
 JOIN usuario_categorias uc ON uc.usuario_id = u.id AND uc.categoria_id = NEW.categoria_id
 LEFT JOIN usuario_preferencias p ON p.usuario_id = u.id
 WHERE u.estado = 'activo' AND u.rol = 'familia' AND u.ciudad_id = NEW.ciudad_id
   AND COALESCE(p.recibir_sugerencias, true)
   AND NOT EXISTS (SELECT 1 FROM favoritos_asociaciones f
                   WHERE f.usuario_id = u.id AND f.asociacion_id = NEW.asociacion_id AND f.notificaciones_activas)
   AND NOT EXISTS (SELECT 1 FROM notificaciones n
                   WHERE n.usuario_id = u.id AND n.tipo = 'sugerencia' AND n.creado_en > now() - interval '1 day');
 RETURN NULL;
END $$;
CREATE TRIGGER avisar_actividad_publicada AFTER INSERT OR UPDATE OF estado ON actividades
FOR EACH ROW EXECUTE FUNCTION avisar_actividad_publicada();

-- Lo mismo para campañas, solo para favoritos
CREATE FUNCTION avisar_campana_publicada() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE aso asociaciones%ROWTYPE;
BEGIN
 IF NEW.estado <> 'publicada' OR (TG_OP = 'UPDATE' AND OLD.estado = 'publicada')
    OR NEW.fin <= now() OR NEW.asociacion_id IS NULL THEN
  RETURN NULL;
 END IF;
 SELECT * INTO aso FROM asociaciones WHERE id = NEW.asociacion_id;
 IF NOT aso.verificada OR NOT aso.activa THEN RETURN NULL; END IF;
 INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, campana_id)
 SELECT f.usuario_id, 'nueva_campana',
        aso.nombre || ' abrió una campaña',
        NEW.titulo,
        NEW.id
 FROM favoritos_asociaciones f
 JOIN usuarios u ON u.id = f.usuario_id
 WHERE f.asociacion_id = NEW.asociacion_id AND f.notificaciones_activas
   AND u.estado = 'activo' AND u.rol = 'familia' AND u.ciudad_id = NEW.ciudad_id;
 RETURN NULL;
END $$;
CREATE TRIGGER avisar_campana_publicada AFTER INSERT OR UPDATE OF estado ON campanas
FOR EACH ROW EXECUTE FUNCTION avisar_campana_publicada();

-- ============================================================
-- Recordatorios e invitaciones a encuestas (RF16, RF-07, RF-13)
-- ============================================================

-- Registro de los avisos automáticos ya generados, para no repetirlos
CREATE TABLE avisos_enviados (
    inscripcion_id uuid NOT NULL REFERENCES inscripciones(id) ON DELETE CASCADE,
    tipo text NOT NULL CHECK (tipo IN ('recordatorio','encuesta_antes','encuesta_despues')),
    creado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (inscripcion_id, tipo)
);

-- La llama el backend cada pocos minutos. Devuelve cuántas notificaciones creó.
--   recordatorio       la actividad empieza en menos de 24 horas
--   encuesta_antes     hay encuesta previa sin responder y faltan menos de 3 días
--   encuesta_despues   se registró la asistencia y hay encuesta posterior sin responder
-- El recordatorio respeta la preferencia recibir_recordatorios. Las encuestas siempre
-- se avisan porque son parte de la participación.
CREATE FUNCTION generar_avisos() RETURNS integer
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE f record; total integer = 0;
BEGIN
 FOR f IN
  SELECT i.id, i.usuario_id, a.id AS actividad, a.titulo, a.inicio, ci.zona_horaria,
         COALESCE(p.recibir_recordatorios, true) AS quiere
  FROM inscripciones i
  JOIN actividades a ON a.id = i.actividad_id
  JOIN ciudades ci ON ci.id = a.ciudad_id
  JOIN usuarios u ON u.id = i.usuario_id
  LEFT JOIN usuario_preferencias p ON p.usuario_id = u.id
  WHERE i.estado = 'confirmada' AND a.estado = 'publicada' AND u.estado = 'activo'
    AND a.inicio > now() AND a.inicio <= now() + interval '24 hours'
    AND NOT EXISTS (SELECT 1 FROM avisos_enviados x WHERE x.inscripcion_id = i.id AND x.tipo = 'recordatorio')
 LOOP
  INSERT INTO avisos_enviados (inscripcion_id, tipo) VALUES (f.id, 'recordatorio') ON CONFLICT DO NOTHING;
  IF FOUND AND f.quiere THEN
   INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, actividad_id)
   VALUES (f.usuario_id, 'recordatorio', 'Tu actividad es pronto',
           f.titulo || ' empieza el ' || to_char(f.inicio AT TIME ZONE f.zona_horaria, 'DD/MM') ||
           ' a las ' || to_char(f.inicio AT TIME ZONE f.zona_horaria, 'HH24:MI') || ' h. ¡Te esperamos!',
           f.actividad);
   total = total + 1;
  END IF;
 END LOOP;

 FOR f IN
  SELECT DISTINCT i.id, i.usuario_id, a.id AS actividad, a.titulo
  FROM inscripciones i
  JOIN actividades a ON a.id = i.actividad_id
  JOIN encuestas e ON e.actividad_id = a.id AND e.momento = 'antes' AND e.activa
  JOIN usuarios u ON u.id = i.usuario_id
  WHERE i.estado = 'confirmada' AND u.estado = 'activo'
    AND a.fin > now() AND a.inicio <= now() + interval '3 days'
    AND NOT EXISTS (SELECT 1 FROM respuestas_encuesta r JOIN preguntas_encuesta q ON q.id = r.pregunta_id
                    WHERE r.inscripcion_id = i.id AND q.encuesta_id = e.id)
    AND NOT EXISTS (SELECT 1 FROM avisos_enviados x WHERE x.inscripcion_id = i.id AND x.tipo = 'encuesta_antes')
 LOOP
  INSERT INTO avisos_enviados (inscripcion_id, tipo) VALUES (f.id, 'encuesta_antes') ON CONFLICT DO NOTHING;
  IF FOUND THEN
   INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, actividad_id)
   VALUES (f.usuario_id, 'encuesta', 'Cuéntanos antes de ir',
           'Responde una encuesta corta sobre ' || f.titulo || '. Nos ayuda a preparar la actividad.', f.actividad);
   total = total + 1;
  END IF;
 END LOOP;

 FOR f IN
  SELECT DISTINCT i.id, i.usuario_id, a.id AS actividad, a.titulo
  FROM inscripciones i
  JOIN actividades a ON a.id = i.actividad_id
  JOIN encuestas e ON e.actividad_id = a.id AND e.momento = 'despues' AND e.activa
  JOIN usuarios u ON u.id = i.usuario_id
  WHERE i.estado = 'confirmada' AND u.estado = 'activo'
    AND EXISTS (SELECT 1 FROM inscripcion_participantes ip WHERE ip.inscripcion_id = i.id AND ip.estado_asistencia = 'asistio')
    AND NOT EXISTS (SELECT 1 FROM respuestas_encuesta r JOIN preguntas_encuesta q ON q.id = r.pregunta_id
                    WHERE r.inscripcion_id = i.id AND q.encuesta_id = e.id)
    AND NOT EXISTS (SELECT 1 FROM avisos_enviados x WHERE x.inscripcion_id = i.id AND x.tipo = 'encuesta_despues')
 LOOP
  INSERT INTO avisos_enviados (inscripcion_id, tipo) VALUES (f.id, 'encuesta_despues') ON CONFLICT DO NOTHING;
  IF FOUND THEN
   INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, actividad_id)
   VALUES (f.usuario_id, 'encuesta', '¿Cómo te fue?',
           'Gracias por participar en ' || f.titulo || '. Responde la encuesta y califica la actividad.', f.actividad);
   total = total + 1;
  END IF;
 END LOOP;
 RETURN total;
END $$;

-- ============================================================
-- Propuestas, asociaciones repetidas (CP-01)
-- ============================================================

-- Minúsculas, sin acentos, sin signos y sin la terminación A.C., así "Raíces Vivas A.C."
-- y "raices vivas" se reconocen como la misma asociación.
CREATE FUNCTION normalizar_nombre(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
 SELECT btrim(regexp_replace(regexp_replace(regexp_replace(
          translate(lower(coalesce(t, '')), 'áéíóúüñàèìòùäëïö', 'aeiouunaeiouaeio'),
          '\m(a\s*\.?\s*c\s*\.?|i\s*\.?\s*a\s*\.?\s*p\s*\.?|asociacion civil)\s*$', ''),
        '[^a-z0-9 ]', ' ', 'g'),
        '\s+', ' ', 'g'))
$$;

CREATE INDEX asociaciones_nombre_normal ON asociaciones (ciudad_id, normalizar_nombre(nombre));

-- Funciones nuevas, solo el backend puede ejecutarlas
REVOKE EXECUTE ON FUNCTION avisar_notificacion(), avisar_actividad_publicada(), avisar_campana_publicada(),
  generar_avisos(), normalizar_nombre(text) FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT EXECUTE ON FUNCTION fqs.generar_avisos(), fqs.normalizar_nombre(text) TO fqs_backend;
  GRANT SELECT, INSERT, UPDATE, DELETE ON fqs.avisos_enviados TO fqs_backend;
 END IF;
END $$;

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;
COMMIT;
