-- Familias que Suman | Catálogos v2 | PostgreSQL 16+
-- Ejecutar después de 01_esquema.sql. Puede repetirse sin duplicar catálogos.
-- La clave de cada categoría coincide con el enum Categoria de la app Android.
BEGIN;
INSERT INTO fqs.ciudades(nombre, estado, pais, zona_horaria)
VALUES ('Monterrey', 'Nuevo León', 'México', 'America/Monterrey')
ON CONFLICT (nombre, estado, pais) DO NOTHING;

INSERT INTO fqs.categorias(clave, nombre) VALUES
('MEDIO_AMBIENTE', 'Medio Ambiente'),
('ADULTOS_MAYORES', 'Adultos Mayores'),
('NINOS', 'Niños'),
('MASCOTAS', 'Mascotas'),
('ARTE_CULTURA', 'Arte y Cultura'),
('COMUNIDAD', 'Comunidad')
ON CONFLICT (clave) DO NOTHING;

-- No se inventan insignias, niveles, avisos de privacidad, asociaciones ni cuentas.
-- Antes de abrir el registro hay que cargar el aviso de privacidad real de la
-- organización, porque aceptarlo es obligatorio en el onboarding.
COMMIT;
