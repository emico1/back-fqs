-- Familias que Suman | Segunda migración de seguridad | PostgreSQL 16+
-- Ejecutar después de 07_seguridad.sql con el usuario postgres. Solo agrega, no borra datos.
--
-- Cambios
--   Verificación de correo. El registro con correo queda pendiente hasta que la persona
--   escribe el código que le llega, así nadie puede apartar el correo de otra persona.
--   Un cambio de correo tampoco se aplica hasta verificar el nuevo.
--   Último acceso por cuenta, para la política de cuentas inactivas.
--   Inicio de cada familia de sesiones, para el tope absoluto de las sesiones de administración.
--   Alertas de seguridad y anclas de la bitácora.
--   Poda de la bitácora. Las filas viejas se archivan cifradas y se registra un corte con
--   el hash de la última fila borrada, así la cadena se sigue pudiendo verificar.
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;
SET LOCAL client_min_messages = warning;

-- ============================================================
-- Verificación de correo
-- ============================================================

ALTER TABLE usuarios ADD COLUMN correo_verificado_en timestamptz;
-- Las cuentas que ya existían se consideran verificadas, ya recibían correos
UPDATE usuarios SET correo_verificado_en = creado_en WHERE correo IS NOT NULL;

CREATE TABLE verificaciones_correo (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo text NOT NULL CHECK (tipo IN ('registro','cambio')),
    -- En un registro la cuenta todavía no existe
    usuario_id uuid REFERENCES usuarios(id) ON DELETE CASCADE,
    correo text NOT NULL CHECK (length(correo) <= 254),
    -- Datos del registro ya validados, con la contraseña como hash scrypt
    datos jsonb NOT NULL DEFAULT '{}'::jsonb,
    codigo_hash text NOT NULL CHECK (length(codigo_hash) = 64),
    expira_en timestamptz NOT NULL,
    intentos smallint NOT NULL DEFAULT 0 CHECK (intentos BETWEEN 0 AND 10),
    reenvios smallint NOT NULL DEFAULT 0 CHECK (reenvios BETWEEN 0 AND 10),
    usado_en timestamptz,
    CHECK ((tipo = 'registro') = (usuario_id IS NULL)),
    creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verificaciones_correo_correo ON verificaciones_correo (lower(correo));
CREATE INDEX verificaciones_correo_pendientes ON verificaciones_correo (usuario_id) WHERE usado_en IS NULL;

-- ============================================================
-- Actividad y sesiones
-- ============================================================

ALTER TABLE usuarios ADD COLUMN ultimo_acceso_en timestamptz NOT NULL DEFAULT now();

ALTER TABLE sesiones ADD COLUMN familia_inicio timestamptz NOT NULL DEFAULT now();
UPDATE sesiones s SET familia_inicio = f.inicio
FROM (SELECT familia_id, min(creado_en) AS inicio FROM sesiones GROUP BY familia_id) f
WHERE f.familia_id = s.familia_id;

-- Las cuentas que no se usan en mucho tiempo reciben un aviso y, si no vuelven,
-- se genera una solicitud de eliminación que atiende el equipo
ALTER TABLE solicitudes_eliminacion ADD COLUMN origen text NOT NULL DEFAULT 'titular'
    CHECK (origen IN ('titular','inactividad'));

CREATE TABLE avisos_inactividad (
    usuario_id uuid PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    enviado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Alertas y anclas
-- ============================================================

-- Estado de tareas periódicas (cursor de la bitácora, última ancla)
CREATE TABLE tareas_estado (
    clave text PRIMARY KEY CHECK (length(clave) <= 60),
    valor text NOT NULL CHECK (length(valor) <= 200),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE alertas_seguridad (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    regla text NOT NULL CHECK (length(regla) <= 60),
    -- Sobre quién o qué es la alerta, sirve para no repetirla dentro de una hora
    clave text NOT NULL CHECK (length(clave) <= 120),
    detalle jsonb NOT NULL DEFAULT '{}'::jsonb,
    destinatarios smallint NOT NULL DEFAULT 0,
    creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX alertas_seguridad_regla ON alertas_seguridad (regla, clave, creado_en DESC);

-- Copia local de cada ancla enviada por correo. La que vale es la copia externa
CREATE TABLE anclas_bitacora (
    id bigserial PRIMARY KEY,
    hasta_id bigint,
    hash text CHECK (hash IS NULL OR length(hash) = 64),
    revisadas bigint NOT NULL,
    valida boolean NOT NULL,
    destinatarios smallint NOT NULL DEFAULT 0,
    creado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Poda de la bitácora
-- ============================================================

CREATE TABLE bitacora_cortes (
    id bigserial PRIMARY KEY,
    -- Última fila borrada y su hash. La primera fila que queda debe apuntar a este hash
    hasta_id bigint NOT NULL UNIQUE,
    hash text NOT NULL CHECK (length(hash) = 64),
    filas bigint NOT NULL,
    archivo text NOT NULL CHECK (length(archivo) <= 200),
    creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER inmutable BEFORE UPDATE OR DELETE ON bitacora_cortes
FOR EACH ROW EXECUTE FUNCTION bitacora_inmutable();
CREATE TRIGGER inmutable_truncate BEFORE TRUNCATE ON bitacora_cortes
FOR EACH STATEMENT EXECUTE FUNCTION bitacora_inmutable();

-- Solo se pueden borrar filas de la bitácora dentro de podar_bitacora y únicamente las
-- que ya quedaron cubiertas por un corte. Editar y vaciar sigue prohibido siempre.
CREATE OR REPLACE FUNCTION bitacora_inmutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'bitacora_seguridad'
    AND current_setting('fqs.poda_bitacora', true) = 'on'
    AND OLD.id <= (SELECT max(hasta_id) FROM bitacora_cortes) THEN
  RETURN OLD;
 END IF;
 RAISE EXCEPTION 'La bitácora de seguridad es de solo agregar';
END $$;

-- La corre el usuario dueño (script npm run podar-bitacora), nunca el backend.
-- Antes de llamarla el script ya guardó las filas en un archivo cifrado.
CREATE FUNCTION podar_bitacora(p_hasta bigint, p_archivo text) RETURNS bigint
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE h text; n bigint;
BEGIN
 SELECT hash INTO h FROM bitacora_seguridad WHERE id = p_hasta;
 IF h IS NULL THEN RAISE EXCEPTION 'No existe la fila % de la bitácora', p_hasta; END IF;
 IF EXISTS (SELECT 1 FROM bitacora_seguridad WHERE id > p_hasta) IS NOT TRUE THEN
  RAISE EXCEPTION 'Siempre debe quedar al menos una fila después del corte';
 END IF;
 SELECT count(*) INTO n FROM bitacora_seguridad WHERE id <= p_hasta;
 INSERT INTO bitacora_cortes (hasta_id, hash, filas, archivo) VALUES (p_hasta, h, n, p_archivo);
 PERFORM set_config('fqs.poda_bitacora', 'on', true);
 DELETE FROM bitacora_seguridad WHERE id <= p_hasta;
 PERFORM set_config('fqs.poda_bitacora', 'off', true);
 RETURN n;
END $$;

-- Igual que antes, pero si hubo cortes la cadena empieza en el hash del último corte
CREATE OR REPLACE FUNCTION verificar_bitacora()
RETURNS TABLE (revisadas bigint, valida boolean, primer_error bigint, ultimo_hash text)
LANGUAGE plpgsql STABLE SET search_path = fqs, pg_catalog AS $$
DECLARE b bitacora_seguridad; esperado_anterior text; n bigint = 0;
BEGIN
 SELECT c.hash INTO esperado_anterior FROM bitacora_cortes c ORDER BY c.hasta_id DESC LIMIT 1;
 esperado_anterior = coalesce(esperado_anterior, repeat('0', 64));
 FOR b IN SELECT * FROM bitacora_seguridad ORDER BY id LOOP
  n = n + 1;
  IF b.hash_anterior <> esperado_anterior
     OR b.hash <> encode(sha256(convert_to(bitacora_contenido(b), 'UTF8')), 'hex') THEN
   RETURN QUERY SELECT n, false, b.id, b.hash;
   RETURN;
  END IF;
  esperado_anterior = b.hash;
 END LOOP;
 RETURN QUERY SELECT n, true, NULL::bigint, CASE WHEN n = 0 THEN NULL ELSE esperado_anterior END;
END $$;

-- ¿El hash que se guardó fuera del servidor sigue siendo el de esa fila (o de ese corte)?
CREATE FUNCTION coincide_ancla(p_id bigint, p_hash text) RETURNS boolean
LANGUAGE sql STABLE SET search_path = fqs, pg_catalog AS $$
 SELECT EXISTS (SELECT 1 FROM bitacora_seguridad WHERE id = p_id AND hash = p_hash)
     OR EXISTS (SELECT 1 FROM bitacora_cortes WHERE hasta_id = p_id AND hash = p_hash)
$$;

-- ============================================================
-- Permisos
-- ============================================================

REVOKE EXECUTE ON FUNCTION podar_bitacora(bigint, text), coincide_ancla(bigint, text) FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT SELECT, INSERT, UPDATE, DELETE ON fqs.verificaciones_correo, fqs.avisos_inactividad, fqs.tareas_estado TO fqs_backend;
  REVOKE ALL ON fqs.alertas_seguridad, fqs.anclas_bitacora, fqs.bitacora_cortes FROM fqs_backend;
  GRANT SELECT, INSERT ON fqs.alertas_seguridad, fqs.anclas_bitacora TO fqs_backend;
  GRANT USAGE ON SEQUENCE fqs.anclas_bitacora_id_seq TO fqs_backend;
  -- Los cortes solo se leen, los escribe el dueño al podar
  GRANT SELECT ON fqs.bitacora_cortes TO fqs_backend;
  GRANT EXECUTE ON FUNCTION fqs.verificar_bitacora(), fqs.coincide_ancla(bigint, text) TO fqs_backend;
  REVOKE EXECUTE ON FUNCTION fqs.podar_bitacora(bigint, text) FROM fqs_backend;
 END IF;
END $$;

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;
COMMIT;
