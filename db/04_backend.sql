-- Familias que Suman | Tablas del backend | PostgreSQL 16+
-- Ejecutar después de 03_roles.sql. Solo crea tablas nuevas, no toca las existentes.
--
-- sesiones guarda únicamente hashes SHA-256 de los tokens. Un token robado de la
-- base no sirve para iniciar sesión. Cada refresh crea una fila nueva de la misma
-- familia y marca la anterior como rotada. Si alguien presenta un refresh ya rotado
-- (señal de robo) el backend revoca la familia completa.
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;

CREATE TABLE sesiones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    familia_id uuid NOT NULL,
    access_hash text NOT NULL CHECK (length(access_hash) = 64),
    access_expira_en timestamptz NOT NULL,
    refresh_hash text NOT NULL CHECK (length(refresh_hash) = 64),
    refresh_expira_en timestamptz NOT NULL,
    rotada_en timestamptz,
    revocada_en timestamptz,
    agente text,
    UNIQUE (access_hash),
    UNIQUE (refresh_hash),
    CHECK (refresh_expira_en > access_expira_en),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX sesiones_familia_idx ON sesiones(familia_id);
CREATE INDEX sesiones_vigentes_idx ON sesiones(usuario_id) WHERE revocada_en IS NULL AND rotada_en IS NULL;

-- Registro de cada archivo subido. foto_clave en las demás tablas guarda el id de
-- esta tabla, así el backend puede verificar que quien lo usa es su dueño.
CREATE TABLE archivos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid REFERENCES usuarios(id) ON DELETE SET NULL,
    tipo_mime text NOT NULL CHECK (tipo_mime IN ('image/jpeg','image/png')),
    tamano integer NOT NULL CHECK (tamano > 0 AND tamano <= 5242880),
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    creado_en timestamptz NOT NULL DEFAULT now()
);

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;

-- El rol del backend necesita estas tablas aunque se hayan creado después de 03_roles.sql
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT SELECT, INSERT, UPDATE, DELETE ON fqs.sesiones, fqs.archivos TO fqs_backend;
 END IF;
END $$;

REVOKE ALL ON fqs.sesiones, fqs.archivos FROM PUBLIC;
COMMIT;
