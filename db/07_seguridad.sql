-- Familias que Suman | Migración de seguridad | PostgreSQL 16+
-- Ejecutar después de 06_fase2.sql con el usuario postgres. Solo agrega, no borra datos.
--
-- Cambios
--   Segundo factor (TOTP, RFC 6238) para las cuentas de administración. El secreto se
--   guarda cifrado con AES-256-GCM por el backend, la base nunca lo ve en claro.
--   Los códigos de respaldo se guardan como hash y sirven una sola vez.
--   Cada sesión indica si se abrió con segundo factor. Las rutas de administración
--   exigen que sí.
--   Bitácora de seguridad de solo agregar. Cada fila guarda el hash de la anterior,
--   así borrar o editar una fila rompe la cadena y se detecta con verificar_bitacora().
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;
SET LOCAL client_min_messages = warning;

-- ============================================================
-- Segundo factor
-- ============================================================

CREATE TABLE usuarios_2fa (
    usuario_id uuid PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    -- iv (12 bytes) + etiqueta GCM (16 bytes) + secreto cifrado
    secreto_cifrado bytea NOT NULL CHECK (octet_length(secreto_cifrado) BETWEEN 40 AND 200),
    activo boolean NOT NULL DEFAULT false,
    -- Último paso de 30 segundos aceptado. Un código ya usado no se acepta otra vez
    ultimo_paso bigint NOT NULL DEFAULT 0,
    activado_en timestamptz,
    CHECK (activo = (activado_en IS NOT NULL)),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE codigos_respaldo_2fa (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    codigo_hash text NOT NULL CHECK (length(codigo_hash) = 64),
    usado_en timestamptz,
    creado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (codigo_hash)
);

-- Paso intermedio del inicio de sesión. La contraseña ya fue correcta y falta el código
CREATE TABLE desafios_2fa (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    desafio_hash text NOT NULL CHECK (length(desafio_hash) = 64),
    expira_en timestamptz NOT NULL,
    intentos smallint NOT NULL DEFAULT 0 CHECK (intentos BETWEEN 0 AND 10),
    usado_en timestamptz,
    agente text,
    UNIQUE (desafio_hash),
    creado_en timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE sesiones ADD COLUMN segundo_factor boolean NOT NULL DEFAULT false;

-- Solo una cuenta de administración puede tener segundo factor
CREATE FUNCTION exigir_admin_2fa() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM usuarios WHERE id = NEW.usuario_id AND rol = 'admin') THEN
  RAISE EXCEPTION 'El segundo factor solo aplica a cuentas de administración';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER solo_admin BEFORE INSERT OR UPDATE ON usuarios_2fa
FOR EACH ROW EXECUTE FUNCTION exigir_admin_2fa();

-- ============================================================
-- Bitácora de seguridad encadenada
-- ============================================================

CREATE TABLE bitacora_seguridad (
    id bigint PRIMARY KEY,
    -- Sin llave foránea, la bitácora debe sobrevivir aunque se borre la cuenta
    actor_id uuid,
    actor_rol text CHECK (actor_rol IN ('familia','admin')),
    accion text NOT NULL CHECK (length(accion) BETWEEN 3 AND 120),
    ruta text CHECK (length(ruta) <= 200),
    entidad_id uuid,
    detalles jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (octet_length(detalles::text) <= 4000),
    ip text CHECK (length(ip) <= 64),
    request_id uuid,
    creado_en timestamptz NOT NULL,
    hash_anterior text NOT NULL CHECK (length(hash_anterior) = 64),
    hash text NOT NULL CHECK (length(hash) = 64)
);
CREATE SEQUENCE bitacora_seguridad_id_seq OWNED BY bitacora_seguridad.id;
CREATE INDEX bitacora_seguridad_creado ON bitacora_seguridad(creado_en DESC);
CREATE INDEX bitacora_seguridad_actor ON bitacora_seguridad(actor_id, creado_en DESC);
CREATE INDEX bitacora_seguridad_accion ON bitacora_seguridad(accion, creado_en DESC);

-- Texto exacto que se firma. El instante se pasa a microsegundos desde 1970 para que no
-- dependa de la zona horaria de la sesión, y jsonb siempre se escribe igual.
CREATE FUNCTION bitacora_contenido(b bitacora_seguridad) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = fqs, pg_catalog AS $$
 SELECT concat_ws('|', b.id::text, b.hash_anterior, coalesce(b.actor_id::text, '-'), coalesce(b.actor_rol, '-'),
                  b.accion, coalesce(b.ruta, '-'), coalesce(b.entidad_id::text, '-'), b.detalles::text,
                  coalesce(b.ip, '-'), coalesce(b.request_id::text, '-'),
                  (extract(epoch FROM b.creado_en) * 1000000)::bigint::text)
$$;

CREATE FUNCTION bitacora_encadenar() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE previo text;
BEGIN
 -- Un solo escritor a la vez, así el orden del id es el orden de la cadena
 PERFORM pg_advisory_xact_lock(hashtext('fqs.bitacora_seguridad'));
 NEW.id = nextval('fqs.bitacora_seguridad_id_seq');
 NEW.creado_en = clock_timestamp();
 SELECT hash INTO previo FROM bitacora_seguridad ORDER BY id DESC LIMIT 1;
 NEW.hash_anterior = coalesce(previo, repeat('0', 64));
 NEW.hash = encode(sha256(convert_to(bitacora_contenido(NEW), 'UTF8')), 'hex');
 RETURN NEW;
END $$;
CREATE TRIGGER encadenar BEFORE INSERT ON bitacora_seguridad
FOR EACH ROW EXECUTE FUNCTION bitacora_encadenar();

CREATE FUNCTION bitacora_inmutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'La bitácora de seguridad es de solo agregar';
END $$;
CREATE TRIGGER inmutable BEFORE UPDATE OR DELETE ON bitacora_seguridad
FOR EACH ROW EXECUTE FUNCTION bitacora_inmutable();
CREATE TRIGGER inmutable_truncate BEFORE TRUNCATE ON bitacora_seguridad
FOR EACH STATEMENT EXECUTE FUNCTION bitacora_inmutable();

-- Recorre la cadena completa. Devuelve cuántas filas revisó, si todo cuadra, la primera
-- fila alterada y el último hash (conviene copiarlo fuera del servidor de vez en cuando,
-- así ni siquiera alguien con acceso total a la base puede rehacer la cadena sin que se note).
CREATE FUNCTION verificar_bitacora()
RETURNS TABLE (revisadas bigint, valida boolean, primer_error bigint, ultimo_hash text)
LANGUAGE plpgsql STABLE SET search_path = fqs, pg_catalog AS $$
DECLARE b bitacora_seguridad; esperado_anterior text = repeat('0', 64); n bigint = 0;
BEGIN
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

-- ============================================================
-- Permisos
-- ============================================================

REVOKE EXECUTE ON FUNCTION exigir_admin_2fa(), bitacora_encadenar(), bitacora_inmutable(),
  bitacora_contenido(bitacora_seguridad), verificar_bitacora() FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT SELECT, INSERT, UPDATE, DELETE ON fqs.usuarios_2fa, fqs.codigos_respaldo_2fa, fqs.desafios_2fa TO fqs_backend;
  -- La bitácora solo se lee y se agrega. Ni el backend puede editarla o vaciarla
  REVOKE ALL ON fqs.bitacora_seguridad FROM fqs_backend;
  GRANT SELECT, INSERT ON fqs.bitacora_seguridad TO fqs_backend;
  GRANT USAGE ON SEQUENCE fqs.bitacora_seguridad_id_seq TO fqs_backend;
  GRANT EXECUTE ON FUNCTION fqs.verificar_bitacora(), fqs.bitacora_contenido(fqs.bitacora_seguridad) TO fqs_backend;
 END IF;
END $$;

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;
COMMIT;
