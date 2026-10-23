# syntax=docker/dockerfile:1
# API de Familias que Suman (FastAPI). Imagen de producción sin herramientas de compilación,
# corre con un usuario sin privilegios y con el sistema de archivos de solo lectura (ver
# docker-compose.yml).

FROM python:3.13-alpine AS dependencias
WORKDIR /app
COPY requirements.txt ./
# Entorno virtual aparte, en la imagen final solo se copia esta carpeta
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-virtualenv -r requirements.txt

FROM python:3.13-alpine AS api
ENV ENTORNO=production \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup -S fqs && adduser -S -G fqs -H -D fqs
# Los archivos del programa son de root y el proceso solo puede leerlos
COPY --from=dependencias /opt/venv /opt/venv
COPY fqs ./fqs
# Panel web de administración (HTML, CSS y JavaScript sin compilar, se sirve en /panel/)
COPY panel ./panel
# Única carpeta donde el proceso escribe, se monta como volumen
RUN mkdir -p /app/uploads && chown fqs:fqs /app/uploads && chmod 700 /app/uploads
USER fqs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3000/v1/salud', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "fqs"]

# Herramienta de respaldos, misma imagen más el cliente de PostgreSQL 16
FROM api AS respaldo
USER root
RUN apk add --no-cache postgresql16-client
USER fqs
CMD ["python", "-m", "fqs.scripts.respaldo"]
