-- Familias que Suman | Verificación de teléfono | PostgreSQL 16+
-- Ejecutar después de 08_seguridad2.sql con el usuario postgres. No borra datos.
--
-- Cambios
--   Las verificaciones dejan de ser solo de correo, ahora también van por SMS.
--   Los teléfonos de las cuentas se guardan en un solo formato (+52 y 10 dígitos para
--   México), así 81 1234 5678 y +528112345678 ya no cuentan como números distintos.
--   Registro de cada SMS enviado (solo el hash del número) para limitar cuántos salen al
--   día y por número, la defensa contra el fraude de bombeo de SMS.
BEGIN;
SET LOCAL search_path = fqs, pg_catalog;
SET LOCAL client_min_messages = warning;

ALTER TABLE verificaciones_correo RENAME TO verificaciones_contacto;
ALTER TABLE verificaciones_contacto RENAME COLUMN correo TO destino;
ALTER TABLE verificaciones_contacto ADD COLUMN canal text NOT NULL DEFAULT 'correo' CHECK (canal IN ('correo','sms'));
ALTER INDEX verificaciones_correo_correo RENAME TO verificaciones_contacto_destino;
ALTER INDEX verificaciones_correo_pendientes RENAME TO verificaciones_contacto_pendientes;

ALTER TABLE usuarios ADD COLUMN telefono_verificado_en timestamptz;

-- Formato único. 10 dígitos son de México, 52 y 10 dígitos también.
-- Si al convertir dos cuentas quedaran con el mismo número, la segunda se deja como estaba.
UPDATE usuarios u SET telefono = n.canonico
FROM (
  SELECT id, CASE
           WHEN regexp_replace(telefono, '\D', '', 'g') ~ '^\d{10}$' THEN '+52' || regexp_replace(telefono, '\D', '', 'g')
           WHEN regexp_replace(telefono, '\D', '', 'g') ~ '^52\d{10}$' THEN '+' || regexp_replace(telefono, '\D', '', 'g')
           ELSE '+' || regexp_replace(telefono, '\D', '', 'g')
         END AS canonico
  FROM usuarios WHERE telefono IS NOT NULL
) n
WHERE u.id = n.id AND u.telefono <> n.canonico
  AND NOT EXISTS (SELECT 1 FROM usuarios o WHERE o.telefono = n.canonico AND o.id <> n.id);

-- Los teléfonos que ya existían se toman como verificados, ya se usaban para entrar
UPDATE usuarios SET telefono_verificado_en = creado_en WHERE telefono IS NOT NULL;

CREATE TABLE sms_enviados (
    id bigserial PRIMARY KEY,
    -- SHA-256 del número, para contar por número sin guardarlo
    destino_hash text NOT NULL CHECK (length(destino_hash) = 64),
    motivo text NOT NULL CHECK (motivo IN ('verificacion','recuperacion')),
    creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sms_enviados_destino ON sms_enviados (destino_hash, creado_en DESC);
CREATE INDEX sms_enviados_creado ON sms_enviados (creado_en DESC);

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  GRANT SELECT, INSERT, UPDATE, DELETE ON fqs.verificaciones_contacto TO fqs_backend;
  GRANT SELECT, INSERT, DELETE ON fqs.sms_enviados TO fqs_backend;
  GRANT USAGE ON SEQUENCE fqs.sms_enviados_id_seq TO fqs_backend;
 END IF;
END $$;

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;
COMMIT;
