-- Familias que Suman | Migración fase 1 | PostgreSQL 16+
-- Ejecutar después de 04_backend.sql. Solo agrega o modifica, no borra datos.
--
-- Cambios
--   Tipo de actividad (voluntariado o visita) para el filtro inicial Participar, Visiteo
--   Cuentas solo individuales, por decisión del socio formador
--   Aviso en tiempo real cuando cambian los cupos de una actividad (RF-05)
--   Mensaje claro cuando ya no quedan lugares suficientes (RF-05)
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;

-- Visiteo son visitas a lugares (casas hogar, refugios) donde la familia asiste y convive.
-- Voluntariado es una actividad donde la familia trabaja o ayuda.
ALTER TABLE actividades
    ADD COLUMN tipo text NOT NULL DEFAULT 'voluntariado' CHECK (tipo IN ('voluntariado','visita'));
CREATE INDEX actividades_tipo_busqueda ON actividades(ciudad_id, tipo, estado, inicio);

-- Cuentas individuales. La columna se conserva para no romper datos existentes.
ALTER TABLE usuarios ALTER COLUMN tipo_cuenta SET DEFAULT 'individual';
UPDATE usuarios SET tipo_cuenta = 'individual' WHERE tipo_cuenta <> 'individual';
ALTER TABLE usuarios ADD CONSTRAINT usuarios_solo_individual CHECK (tipo_cuenta = 'individual');

-- Los proyectos se muestran por ciudad, igual que actividades y campañas (RF-02, RF-09).
-- Si ya hay proyectos, toman la ciudad de su asociación o de su primera campaña.
ALTER TABLE proyectos ADD COLUMN ciudad_id uuid REFERENCES ciudades(id) ON DELETE RESTRICT;
UPDATE proyectos p SET ciudad_id = a.ciudad_id FROM asociaciones a WHERE a.id = p.asociacion_id AND p.ciudad_id IS NULL;
UPDATE proyectos p SET ciudad_id = (SELECT c.ciudad_id FROM campanas c WHERE c.proyecto_id = p.id ORDER BY c.creado_en LIMIT 1)
WHERE p.ciudad_id IS NULL;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM fqs.proyectos WHERE ciudad_id IS NULL) THEN
  RAISE EXCEPTION 'Hay proyectos sin asociación ni campañas, asígnales ciudad_id antes de continuar';
 END IF;
END $$;
ALTER TABLE proyectos ALTER COLUMN ciudad_id SET NOT NULL;
CREATE INDEX proyectos_ciudad_estado ON proyectos(ciudad_id, estado);

-- Cada cambio de cupo avisa por el canal fqs_cupos. El backend escucha ese canal y lo
-- reenvía a la app por Server-Sent Events. El aviso se entrega al confirmar la
-- transacción, así nunca se anuncia un cupo que al final se revirtió.
CREATE FUNCTION avisar_cupos() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 -- Solo se anuncian actividades publicadas, los borradores no salen del panel de admin
 IF NEW.estado = 'publicada'
    AND (NEW.cupos_ocupados IS DISTINCT FROM OLD.cupos_ocupados OR NEW.cupo_total IS DISTINCT FROM OLD.cupo_total) THEN
  PERFORM pg_notify('fqs_cupos', json_build_object(
    'actividadId', NEW.id,
    'cupoTotal', NEW.cupo_total,
    'cuposOcupados', NEW.cupos_ocupados,
    'cuposDisponibles', NEW.cupo_total - NEW.cupos_ocupados)::text);
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER avisar_cupos AFTER UPDATE OF cupos_ocupados, cupo_total ON actividades
FOR EACH ROW EXECUTE FUNCTION avisar_cupos();

-- Misma lógica que en 01_esquema.sql más una revisión explícita de cupo con un mensaje
-- que la familia entiende. La fila de la actividad está bloqueada (FOR UPDATE), así que
-- la revisión es exacta aunque dos familias pidan el último lugar al mismo tiempo.
CREATE OR REPLACE FUNCTION inscribir_familia(p_usuario uuid, p_actividad uuid,
 p_titular_asiste boolean DEFAULT false, p_miembros uuid[] DEFAULT '{}')
RETURNS uuid LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE a actividades%ROWTYPE; reserva uuid; estado_previo text; n integer; libres integer;
BEGIN
 IF p_titular_asiste IS NULL OR p_miembros IS NULL OR array_position(p_miembros, NULL) IS NOT NULL THEN
  RAISE EXCEPTION 'Parámetros inválidos';
 END IF;
 IF cardinality(p_miembros) <> (SELECT count(DISTINCT x) FROM unnest(p_miembros) x) THEN
  RAISE EXCEPTION 'Acompañantes repetidos';
 END IF;
 PERFORM 1 FROM usuarios WHERE id = p_usuario AND estado = 'activo' AND rol = 'familia' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Usuario inexistente, inactivo o sin cuenta de familia'; END IF;
 SELECT * INTO a FROM actividades WHERE id = p_actividad FOR UPDATE;
 IF NOT FOUND OR a.estado <> 'publicada' OR a.inicio <= now() THEN
  RAISE EXCEPTION 'Actividad no disponible para inscripción';
 END IF;
 n = cardinality(p_miembros) + CASE WHEN p_titular_asiste THEN 1 ELSE 0 END;
 IF n = 0 THEN RAISE EXCEPTION 'Debe asistir al menos una persona'; END IF;
 SELECT id, estado INTO reserva, estado_previo FROM inscripciones
 WHERE usuario_id = p_usuario AND actividad_id = p_actividad FOR UPDATE;
 IF estado_previo = 'confirmada' THEN RAISE EXCEPTION 'Ya tienes una inscripción confirmada en esta actividad'; END IF;
 libres = a.cupo_total - a.cupos_ocupados;
 IF libres <= 0 THEN
  RAISE EXCEPTION 'Lo sentimos, esta actividad ya no tiene lugares disponibles';
 ELSIF libres < n THEN
  RAISE EXCEPTION 'Solo quedan % lugares y tu registro es para % personas', libres, n;
 END IF;
 IF reserva IS NULL THEN
  INSERT INTO inscripciones(usuario_id, actividad_id, cantidad_personas)
  VALUES (p_usuario, p_actividad, n) RETURNING id INTO reserva;
 ELSE
  DELETE FROM inscripcion_participantes WHERE inscripcion_id = reserva;
  UPDATE inscripciones
  SET cantidad_personas = n, estado = 'confirmada', cancelada_en = NULL,
      motivo_cancelacion = NULL, fecha_inscripcion = now()
  WHERE id = reserva;
 END IF;
 IF p_titular_asiste THEN
  INSERT INTO inscripcion_participantes(inscripcion_id, es_titular) VALUES (reserva, true);
 END IF;
 INSERT INTO inscripcion_participantes(inscripcion_id, miembro_comunidad_id)
 SELECT reserva, x FROM unnest(p_miembros) x;
 RETURN reserva;
END $$;

REVOKE EXECUTE ON FUNCTION avisar_cupos() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION inscribir_familia(uuid, uuid, boolean, uuid[]) FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT EXECUTE ON FUNCTION fqs.inscribir_familia(uuid, uuid, boolean, uuid[]) TO fqs_backend;
 END IF;
END $$;
COMMIT;
