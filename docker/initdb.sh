#!/bin/sh
# Se ejecuta una sola vez, cuando el volumen de PostgreSQL está vacío. Corre los scripts
# del esquema en orden y crea el usuario de mínimo privilegio con el que se conecta la API.
set -eu
for f in /fqs-db/[0-9][0-9]_*.sql; do
  echo "Aplicando $f"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -q -f "$f"
done
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -q \
  -v pass="$FQS_API_PASSWORD" <<'SQL'
CREATE ROLE fqs_api LOGIN PASSWORD :'pass' IN ROLE fqs_backend;
SQL
echo "Esquema listo y usuario fqs_api creado"
