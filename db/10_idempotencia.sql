-- Familias que Suman | Reintentos seguros de escrituras | PostgreSQL 16+
-- Ejecutar después de 09_telefono.sql con el usuario postgres. No borra datos.
--
-- La app guarda sin conexión algunas escrituras (propuestas, reportes y testimonios) y las
-- manda cuando vuelve la red, con el encabezado Idempotency-Key. Esta tabla guarda la
-- respuesta de cada clave durante 48 horas. Si la misma petición llega otra vez (porque la
-- respuesta se perdió en el camino), la API devuelve la respuesta guardada y no crea un
-- duplicado.
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;
SET LOCAL client_min_messages = warning;

CREATE TABLE idempotencia (
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    clave text NOT NULL CHECK (clave ~ '^[A-Za-z0-9_-]{16,64}$'),
    -- Ruta exacta y SHA-256 del cuerpo, la misma clave con otra petición se rechaza
    ruta text NOT NULL CHECK (length(ruta) <= 200),
    huella text NOT NULL CHECK (huella ~ '^[0-9a-f]{64}$'),
    -- Vacíos mientras la petición se procesa
    status smallint CHECK (status BETWEEN 200 AND 299),
    respuesta jsonb,
    creado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usuario_id, clave),
    CHECK ((status IS NULL) = (respuesta IS NULL))
);
CREATE INDEX idempotencia_creado ON idempotencia (creado_en);

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT SELECT, INSERT, UPDATE, DELETE ON fqs.idempotencia TO fqs_backend;
 END IF;
END $$;

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;
COMMIT;
