# Manual de instalación

Este manual permite que una persona externa levante el sistema completo. Hay dos formas de correr el backend, con Docker (recomendada, igual a producción) o directo en la computadora (útil para desarrollar). Después se compila e instala la app.

## Lo que se necesita

| Pieza | Versión | Para qué |
|---|---|---|
| Docker Desktop o Docker Engine con Compose | reciente | Backend con Docker |
| Python | 3.12 o 3.13 | Backend sin Docker y scripts |
| PostgreSQL | 16 | Backend sin Docker |
| Android Studio | Otter 3 Feature Drop (2025.2.3) o más nuevo, con el JDK que trae | Compilar y firmar la app |
| Teléfono Android | 8.0 o más nuevo | Instalar el APK release |
| Cuenta de Firebase | gratuita | Notificaciones push (opcional) |
| Cuenta de Brevo | gratuita | Correos de verificación y recuperación (opcional en desarrollo) |
| Cuenta de Cloudflare con un dominio | gratuita | Túnel para la demostración por internet (opcional) |

## Opción A. Backend con Docker

1. Descomprime el proyecto `fqs-backend` y abre una terminal en esa carpeta.
2. Copia la plantilla de variables.

```bash
cp .env.docker.example .env.docker
```

3. Genera dos claves distintas, una para `CLAVE_CIFRADO_2FA` y otra para `RESPALDO_CLAVE`.

```bash
openssl rand -base64 32
openssl rand -base64 32
```

4. Abre `.env.docker` y llena `POSTGRES_PASSWORD`, `FQS_API_PASSWORD` (dos contraseñas largas y distintas), las dos claves, `GRAFANA_ADMIN_PASSWORD` (otra contraseña larga) y, si los tienes, `BREVO_API_KEY` y `CORREO_REMITENTE`. Para probar en tu computadora deja `FQS_DOMINIO=localhost`.
5. Si vas a usar notificaciones push, copia el archivo de la cuenta de servicio de Firebase como `docker/secretos/firebase-cuenta-servicio.json`. Si no, crea ese archivo con el contenido `{}` para que Compose arranque.
6. Levanta el sistema.

```bash
docker compose --env-file .env.docker up -d --build
```

7. Crea la cuenta de administración y carga los datos de ejemplo.

```bash
docker compose --env-file .env.docker exec api python -m fqs.scripts.crear_admin
docker compose --env-file .env.docker exec api python -m fqs.scripts.datos_prueba
```

8. Abre https://localhost/panel/ (el navegador avisará del certificado local de Caddy), entra con la cuenta de administración, activa el segundo factor con el QR y publica el aviso de privacidad en Ajustes.
9. Abre http://127.0.0.1:3001 y entra a Grafana con `admin` y `GRAFANA_ADMIN_PASSWORD`. En Dashboards, carpeta Familias que Suman, está el tablero de la API. Detalles en [../seguridad/monitoreo.md](../seguridad/monitoreo.md).

### Demostración por internet con el túnel

1. En Cloudflare, en Zero Trust, Networks, Tunnels, crea un túnel de tipo cloudflared, copia el token y agrega un nombre público (por ejemplo `api.tu-dominio.mx`) con el servicio `http://api:3000`.
2. Pon el token en `CLOUDFLARE_TUNNEL_TOKEN` dentro de `.env.docker`.
3. Arranca con el perfil del túnel.

```bash
docker compose --env-file .env.docker --profile tunel up -d --build
```

4. Comprueba desde el teléfono, con datos móviles, que `https://api.tu-dominio.mx/v1/salud` responde `{"ok":true}`.

## Opción B. Backend sin Docker (Windows o Mac)

1. Instala PostgreSQL 16 y Python 3.12 o más nuevo.
2. Crea la base y aplica los scripts en orden, con el usuario `postgres`.

```bash
createdb -U postgres familiasquesuman
psql -U postgres -d familiasquesuman -f db/01_esquema.sql
psql -U postgres -d familiasquesuman -f db/02_catalogos.sql
psql -U postgres -d familiasquesuman -f db/03_roles.sql
psql -U postgres -d familiasquesuman -f db/04_backend.sql
psql -U postgres -d familiasquesuman -f db/05_fase1.sql
psql -U postgres -d familiasquesuman -f db/06_fase2.sql
psql -U postgres -d familiasquesuman -f db/07_seguridad.sql
psql -U postgres -d familiasquesuman -f db/08_seguridad2.sql
psql -U postgres -d familiasquesuman -f db/09_telefono.sql
psql -U postgres -d familiasquesuman -f db/10_idempotencia.sql
psql -U postgres -d familiasquesuman -c "CREATE ROLE fqs_api LOGIN PASSWORD 'una-contraseña-larga' IN ROLE fqs_backend"
```

3. Crea el entorno virtual e instala las dependencias.

```bash
python -m venv .venv
# Mac
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

4. Copia `.env.example` como `.env`, pon en `DATABASE_URL` el usuario `fqs_api` con su contraseña y pega en `CLAVE_CIFRADO_2FA` la salida de `python -m fqs.scripts.generar_clave`.
5. Crea la cuenta de administración, carga los datos de ejemplo y arranca.

```bash
python -m fqs.scripts.crear_admin
python -m fqs.scripts.datos_prueba
python -m fqs
```

6. Abre http://127.0.0.1:3000/panel/ y sigue el paso 8 de la opción A. Con `ENTORNO=development` la documentación interactiva queda en http://127.0.0.1:3000/docs.

Para que un teléfono en la misma red llegue a la computadora, arranca con `HOST=0.0.0.0` en `.env` y usa la IP local de la computadora en la app de depuración.

## Pruebas del backend

```bash
python -m pip install -r requirements-dev.txt
createdb -U postgres fqs_test
```

En Mac

```bash
export TEST_OWNER_DATABASE_URL=postgresql://postgres@localhost/fqs_test
export TEST_DATABASE_URL=postgresql://fqs_api_test:prueba-local-fqs@localhost/fqs_test
python -m pytest -q
```

En Windows (PowerShell)

```powershell
$env:TEST_OWNER_DATABASE_URL="postgresql://postgres:TU_CONTRASEÑA@localhost/fqs_test"
$env:TEST_DATABASE_URL="postgresql://fqs_api_test:prueba-local-fqs@localhost/fqs_test"
python -m pytest -q
```

La base `fqs_test` se borra en cada ejecución, nunca uses la de producción.

## App Android

1. Descomprime la app en una ruta corta, sin espacios ni acentos (por ejemplo `C:\proyectos\fqs-app`), ábrela en Android Studio y deja que sincronice Gradle. La primera vez descarga Gradle 9.1.0 y las dependencias. El proyecto usa el plugin de Android 9.0.1, así que funciona con el JDK que trae Android Studio (cualquiera del 17 al 25), sin configurar nada.
2. Copia `google-services.json` del proyecto de Firebase en `app/`. No viene en el zip porque es propio de cada proyecto de Firebase.
3. En `gradle.properties` pon la dirección del backend.

```properties
# Emulador contra la computadora
fqs.api.debug=http://10.0.2.2:3000/
# Teléfono físico, la dirección pública del túnel o del servidor, siempre https
fqs.api.release=https://api.tu-dominio.mx/
```

4. Para depurar en el emulador, levanta el backend con el archivo de desarrollo, que publica la API solo en 127.0.0.1 puerto 3000 (el emulador la ve como `10.0.2.2:3000`) y la corre en modo desarrollo, así sin Brevo los códigos de verificación salen en `docker compose --env-file .env.docker logs api`. Luego dale Run.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.docker up -d
```

5. Para el teléfono físico se instala el release firmado.

### Build de release firmado

1. En Android Studio abre Build, Generate Signed Bundle or APK, elige APK.
2. Crea un keystore nuevo (Create new) y guárdalo fuera de la carpeta del proyecto. Anota sus contraseñas en un gestor de contraseñas. Sin ese archivo no se pueden publicar actualizaciones de la app.
3. Elige la variante release y termina el asistente. El APK queda en `app/release/app-release.apk`.
4. Comprueba la firma.

```bash
apksigner verify --print-certs app/release/app-release.apk
```

5. Instálalo en el teléfono con cable USB y la depuración USB activada.

```bash
adb install -r app/release/app-release.apk
```

El APK release solo permite HTTPS, así que tiene que apuntar al túnel o a un servidor con certificado válido.

## Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| El backend no arranca y dice que falta `CLAVE_CIFRADO_2FA` | Genera la clave con `python -m fqs.scripts.generar_clave` y pégala en `.env` |
| En producción se niega a arrancar por `DB_SSL` | La base no es local, usa `DB_SSL=require` o `verify-full` |
| El registro responde 503 | Falta publicar el aviso de privacidad en el panel |
| Android Studio dice que el plugin de Android 9.0.1 es demasiado nuevo | La versión de Android Studio es anterior a Otter 3 Feature Drop, actualízala desde Help, Check for Updates |
| Al compilar desde la terminal dice que la versión de Java no es compatible | La terminal usa otro Java. En PowerShell pon `$env:JAVA_HOME` en la carpeta `jbr` de Android Studio antes de `.\gradlew.bat assembleDebug` |
| El inicio de sesión responde 429 | Se pasó el límite de intentos, espera el tiempo que indica `Retry-After` |
| Brevo responde 401 | La IP del servidor no está autorizada en Brevo o la llave es otra |
| La app en el teléfono no conecta | Revisa que `fqs.api.release` use https y que el túnel esté activo |
