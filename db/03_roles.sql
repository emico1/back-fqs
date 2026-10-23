-- Familias que Suman | Roles y permisos | PostgreSQL 16+
-- Ejecutar después de 02_catalogos.sql con un rol que tenga CREATEROLE.
-- Puede repetirse sin efectos duplicados.
--
-- fqs_backend es un rol de grupo SIN login. La cuenta con la que se conecta el
-- servidor Node se crea aparte con su propia contraseña (que nunca se guarda en
-- el repositorio) y se le asigna este grupo, por ejemplo
--   CREATE ROLE fqs_api LOGIN PASSWORD '...' IN ROLE fqs_backend;
BEGIN;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqs_backend') THEN
  CREATE ROLE fqs_backend NOLOGIN;
 END IF;
END $$;

GRANT USAGE ON SCHEMA fqs TO fqs_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fqs TO fqs_backend;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA fqs TO fqs_backend;

-- instalar_auditoria es solo para migraciones, el backend no la necesita.
REVOKE EXECUTE ON FUNCTION fqs.instalar_auditoria() FROM fqs_backend;

-- Tablas y funciones que se creen después con el mismo dueño reciben los mismos permisos.
ALTER DEFAULT PRIVILEGES IN SCHEMA fqs GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fqs_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA fqs GRANT EXECUTE ON FUNCTIONS TO fqs_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA fqs REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
COMMIT;
