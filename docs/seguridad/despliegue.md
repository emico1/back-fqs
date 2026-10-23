# Despliegue seguro con HTTPS

El repositorio trae todo para levantar el sistema completo con Docker Compose en un servidor con Linux, o en una computadora con Docker Desktop (Windows o Mac). Son siete servicios, dos de ellos opcionales. Para correrlo en una máquina virtual de Azure con solo SSH abierto está [despliegue-azure.md](despliegue-azure.md).

| Servicio | Imagen | Red | Puertos publicados |
|---|---|---|---|
| `db` | `postgres:16-alpine` | interna, sin internet | ninguno |
| `api` | construida con el `Dockerfile` | interna, salida y monitoreo | ninguno |
| `caddy` | `caddy:2-alpine` | salida | 80 y 443 |
| `prometheus` | `prom/prometheus:v3.15.0` | monitoreo, sin internet | ninguno |
| `grafana` | `grafana/grafana:12.4.11` | monitoreo y grafana_local | 3001 solo en 127.0.0.1 |
| `tunel` | `cloudflare/cloudflared` | salida | ninguno, solo con el perfil `tunel` |
| `respaldo` | `Dockerfile`, etapa `respaldo` | interna | ninguno, se corre bajo demanda |

Solo Caddy recibe conexiones de internet. La base no tiene puerto publicado y su red está marcada como `internal`, así que tampoco puede salir a internet. La API está en las dos redes porque necesita la base y también salir hacia Firebase y Brevo. Además está en la red `monitoreo`, también sin internet, donde Prometheus lee sus métricas por un puerto que solo escucha en esa red.

## Requisitos

- Un servidor con Docker y Docker Compose.
- Un dominio que apunte a la IP del servidor (por ejemplo `api.familiasquesuman.mx`) y los puertos 80 y 443 abiertos. Caddy los necesita para obtener el certificado.
- Para probar en una computadora sin dominio se usa `FQS_DOMINIO=localhost` y Caddy emite un certificado con su propia autoridad local.

## Pasos

```bash
cp .env.docker.example .env.docker
# una clave para CLAVE_CIFRADO_2FA y otra distinta para RESPALDO_CLAVE
python -m fqs.scripts.generar_clave
python -m fqs.scripts.generar_clave
# o sin Python
openssl rand -base64 32
# llena .env.docker con el dominio, dos contraseñas largas distintas, las dos claves
# y la contraseña de Grafana (GRAFANA_ADMIN_PASSWORD)
mkdir -p docker/secretos
cp ruta/a/firebase-cuenta-servicio.json docker/secretos/
docker compose --env-file .env.docker up -d --build
```

La primera vez, `docker/initdb.sh` corre los scripts de `db/` en orden y crea el usuario `fqs_api` dentro del grupo `fqs_backend`. Después se crea la cuenta de administración.

```bash
docker compose --env-file .env.docker exec api python -m fqs.scripts.crear_admin
```

Y se sigue [segundo-factor.md](segundo-factor.md) para activar la verificación en dos pasos.

## Qué hace Caddy

El archivo `docker/Caddyfile` configura lo siguiente.

- Obtiene y renueva solo el certificado TLS (Let's Encrypt o ZeroSSL).
- Redirige HTTP a HTTPS con código 308.
- Acepta TLS 1.2 y 1.3 y anuncia HTTP/3.
- Agrega HSTS de un año.
- Quita los encabezados `Server` y `Via` para no anunciar qué software se usa.
- Rechaza cuerpos de más de 6 MB antes de que lleguen a la API.
- Reemplaza `X-Forwarded-For` con la IP real, por eso la API corre con `TRUST_PROXY=1`.
- Deja pasar al instante los eventos de cupos en vivo (`flush_interval -1`).
- No comprime respuestas a propósito. Las respuestas llevan tokens y comprimirlas sobre TLS abre la puerta a ataques tipo BREACH.

La configuración se probó con Caddy 2.10.2 delante de la API en modo producción. La salida completa está en [evidencia/https-caddy.txt](evidencia/https-caddy.txt). Ahí se ve la redirección, TLS 1.3 y 1.2, los encabezados, y que la API registró la IP real aunque el cliente mandó `X-Forwarded-For: 6.6.6.6`.

## Demostración por internet con un túnel

Para que la app en un teléfono físico consuma el backend desde cualquier red, sin abrir puertos ni tener una IP pública, se usa un túnel de Cloudflare. El contenedor `tunel` abre una conexión de salida cifrada hacia Cloudflare y entrega el tráfico a la API por la red interna de Docker. Nadie puede conectarse directo a la computadora donde corre.

1. En Cloudflare, en Zero Trust, Networks, Tunnels, crea un túnel de tipo cloudflared y copia su token.
2. En la configuración del túnel agrega un nombre público (por ejemplo `api.tu-dominio.mx`) con servicio `http://api:3000`.
3. Pon el token en `CLOUDFLARE_TUNNEL_TOKEN` dentro de `.env.docker`.
4. Levanta el sistema con el perfil del túnel.

```bash
docker compose --env-file .env.docker --profile tunel up -d --build
```

5. En la app, en `gradle.properties`, pon esa dirección en `fqs.api.release` y compila el APK release firmado.

Con el túnel, Cloudflare termina el HTTPS con un certificado público válido y lo que viaja entre Cloudflare y el contenedor va dentro de la conexión cifrada del túnel. La API sigue mandando HSTS, CSP y `nosniff`, y los límites por IP funcionan con la IP real porque cloudflared la entrega en `X-Forwarded-For` (con `TRUST_PROXY=1`). El token del túnel es un secreto, vive solo en `.env.docker`, que no se sube al repositorio. Al terminar la demostración se detiene con `docker compose --profile tunel stop tunel` y el backend deja de ser alcanzable desde internet.

### Sin dominio, túnel rápido

Si no hay un dominio en Cloudflare, el perfil `tunel-rapido` abre un túnel temporal sin cuenta (TryCloudflare).

```bash
docker compose --env-file .env.docker --profile tunel-rapido up -d --build
docker compose --env-file .env.docker logs tunel-rapido
```

En el log aparece una dirección `https://algo.trycloudflare.com`, que es la que va en `fqs.api.release`. Tiene tres límites que documenta Cloudflare. La dirección cambia cada vez que se reinicia el servicio, y entonces hay que volver a compilar el APK. No transmite Server-Sent Events, así que los cupos en vivo no se actualizan solos y se ven al recargar la pantalla. Y no tiene garantía de disponibilidad, por eso es solo para pruebas y demostraciones. Con un dominio en Cloudflare (perfil `tunel`) no hay ninguno de esos límites.

El túnel sirve para la demostración. Las pruebas de seguridad (ZAP y sqlmap) se corren contra el despliegue local con Caddy, como pide la rúbrica.

## Monitoreo

Prometheus guarda las métricas de la API 15 días y evalúa las reglas de alerta. Grafana muestra el tablero en http://127.0.0.1:3001 del servidor, y desde otra computadora se entra con `ssh -L 3001:127.0.0.1:3001 usuario@servidor`. Las métricas no pasan por Caddy ni por el túnel. Todo el detalle está en [monitoreo.md](monitoreo.md).

## Endurecimiento del contenedor de la API

| Medida | Para qué |
|---|---|
| `USER fqs` | El proceso no corre como root |
| `read_only: true` | No puede modificar sus propios archivos, solo escribe en `/tmp` (en memoria) y en el volumen de fotos |
| `cap_drop: [ALL]` | Sin capacidades especiales de Linux |
| `no-new-privileges` | No puede ganar privilegios con programas setuid |
| Imagen sin herramientas de compilación | La etapa final solo tiene Python, el código y el entorno virtual con las dependencias de producción |
| `HEALTHCHECK` | Docker reinicia la API si deja de responder |
| Secreto de Firebase como `secret` | No queda en variables de entorno ni en la imagen |

## Base de datos

`DB_SSL=disable` normalmente está prohibido en producción. Dentro de Compose se permite con `DB_RED_AISLADA=1` porque la base solo es alcanzable en una red interna de Docker sin puertos publicados. Si algún día la base se mueve a otro servidor o a un servicio administrado, hay que quitar esa variable y usar `DB_SSL=verify-full` con el certificado del proveedor.

PostgreSQL se inicializa con `scram-sha-256` para las contraseñas de los roles.

## Correo de recuperación con Brevo

1. Crea una cuenta en Brevo y verifica el remitente (por ejemplo `no-responder@tu-dominio.mx`). Conviene configurar SPF y DKIM del dominio como indica Brevo para que los correos no caigan en spam.
2. Genera una llave de API en Brevo, sección SMTP y API.
3. Llena `BREVO_API_KEY` y `CORREO_REMITENTE`.
4. Brevo solo acepta la llave desde las IP autorizadas. La primera vez que el servidor manda un correo, Brevo responde 401 con el mensaje "unrecognised IP address" y la IP pública del servidor. Esa IP se autoriza en Brevo, en Security, Authorised IPs (https://app.brevo.com/security/authorised_ips). Conviene dejar el bloqueo activo, así una llave filtrada no sirve desde otra red. Si la IP del servidor cambia (por ejemplo en una conexión de casa), hay que autorizar la nueva.

La API llama a `POST https://api.brevo.com/v3/smtp/email` con la llave en el encabezado `api-key`. La llave nunca se escribe en la bitácora. Si Brevo falla, la persona ve la misma respuesta de siempre y el error queda en el log del servidor. El envío no se espera, así el tiempo de respuesta no revela si la cuenta existe.

Sin `BREVO_API_KEY` el servidor arranca igual, avisa en el log y en desarrollo escribe el código en la consola.

## SMS con Brevo

Los SMS salen por la misma cuenta de Brevo (`POST https://api.brevo.com/v3/transactionalSMS/send`, misma llave).

1. En Brevo compra créditos de SMS para México.
2. Pon `SMS=brevo` y, si quieres, `SMS_REMITENTE` (de 3 a 11 letras o números, por omisión FamSuman).
3. Ajusta `SMS_MAX_DIA` al presupuesto. Al llegar al tope ya no salen SMS ese día y queda un error en el log.

Sin SMS, el registro solo con teléfono responde 503 y pide registrarse con correo. Las cuentas que ya tienen teléfono siguen entrando normalmente.

## Alertas y retención

Llena `ALERTAS_CORREO` con al menos un correo de alguien que no administre el servidor. Ahí llegan las alertas de seguridad y el ancla semanal de la bitácora. La poda mensual de la bitácora se programa junto con el respaldo. Todo está en [vigilancia-y-retencion.md](vigilancia-y-retencion.md).

```bash
# crontab del servidor, respaldo diario a las 3 y poda el día 1 de cada mes
0 3 * * * cd /ruta/fqs-backend && docker compose --env-file .env.docker --profile respaldo run --rm respaldo
30 3 1 * * cd /ruta/fqs-backend && docker compose --env-file .env.docker --profile respaldo run --rm respaldo python -m fqs.scripts.podar_bitacora
```

## Respaldos cifrados

```bash
docker compose --env-file .env.docker --profile respaldo run --rm respaldo
```

Fuera de Docker se usa `python -m fqs.scripts.respaldo` con `RESPALDO_DATABASE_URL` y `RESPALDO_CLAVE` en `.env`.

Cada respaldo genera tres archivos en `respaldos/`.

| Archivo | Contenido |
|---|---|
| `respaldo-AAAAMMDD-HHMMSS-db.fqsr` | `pg_dump` del schema `fqs` en formato custom, cifrado |
| `respaldo-AAAAMMDD-HHMMSS-archivos.fqsr` | tar de las fotos, cifrado |
| `respaldo-AAAAMMDD-HHMMSS.json` | Manifiesto con tamaño y SHA-256 de cada archivo |

El cifrado es AES-256-GCM con un vector inicial aleatorio por archivo. El tipo (`db` o `archivos`) va como dato asociado, así no se puede hacer pasar un archivo por el otro. Se conservan los últimos 14 respaldos (`RESPALDO_CONSERVAR`).

Para comprobar que un respaldo se puede abrir sin tocar la base

```bash
python -m fqs.scripts.restaurar respaldos/respaldo-20261017-030000.json --solo-verificar
```

Para restaurar (pide escribir el nombre de la base)

```bash
python -m fqs.scripts.restaurar respaldos/respaldo-20261017-030000.json --fotos-en ./uploads
```

La restauración corre en una sola transacción. Los triggers se crean después de cargar los datos, así la bitácora conserva sus fechas y hashes originales.

Se probó en este orden, contra una base real.

| Prueba | Resultado |
|---|---|
| Respaldo de la base y de las fotos | 2 archivos cifrados y manifiesto |
| `--solo-verificar` con la clave correcta | Íntegro, descifrado y reconocido por `pg_restore` |
| `--solo-verificar` con otra clave | Error, la etiqueta GCM no coincide |
| Un byte cambiado en el archivo de la base | Error, el SHA-256 no coincide con el manifiesto |
| Restauración completa | Base y fotos restauradas, la bitácora conserva sus hashes |

Recomendaciones de operación.

- Programar el respaldo diario con cron o un timer de systemd.
- Copiar la carpeta `respaldos/` a otro lugar (otro servidor o almacenamiento en la nube). Como van cifrados, el proveedor no puede leerlos.
- Guardar `RESPALDO_CLAVE` fuera del servidor, por ejemplo en el gestor de contraseñas de la organización y una copia impresa en resguardo. Sin ella los respaldos no se pueden abrir.
- Correr `--solo-verificar` cada semana.

## Escaneo de dependencias

| Herramienta | Qué revisa | Dónde |
|---|---|---|
| Dependabot | Versiones nuevas y avisos de seguridad de pip, Docker, Docker Compose y GitHub Actions del backend, y de Gradle en la app | `.github/dependabot.yml` en cada repositorio |
| `pip-audit` | Vulnerabilidades conocidas en las dependencias de producción de `requirements.txt` | Local y en `.github/workflows/seguridad.yml` |
| Flujo de GitHub Actions | Las 146 pruebas contra PostgreSQL 16, la auditoría y las pruebas de las reglas de alerta con promtool, en cada cambio y cada lunes | `.github/workflows/seguridad.yml` |
| CodeQL | Análisis estático de seguridad del Python y del JavaScript del panel con las consultas `security-extended` | `.github/workflows/codeql.yml` |
| gitleaks | Llaves, contraseñas y tokens en todo el historial del repositorio | `.github/workflows/secretos.yml` y `.gitleaks.toml` |
| En la app | Compilación, CodeQL para Kotlin, Android Lint y gitleaks | `.github/workflows/seguridad.yml` del repositorio de la app |

Si gitleaks encuentra algo en el historial, borrar el archivo no basta. Hay que revocar la credencial en su servicio (generar otra cuenta de servicio en Firebase, otra llave en Brevo) porque el historial ya se pudo haber copiado. Para revisar el historial a mano

```bash
git log --all --full-history -- firebase-cuenta-servicio.json
docker run --rm -v "$PWD:/repo" ghcr.io/gitleaks/gitleaks:v8.28.0 git /repo --redact -v
```

Las dependencias de producción están en `requirements.txt` con versión exacta, así cada instalación usa lo mismo que se probó. Dependabot abre un pull request cuando sale una versión nueva o un parche de seguridad.
