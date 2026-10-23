# API de Familias que Suman

Backend en Python con FastAPI sobre PostgreSQL 16. Las dependencias de producción están fijadas a una versión exacta en `requirements.txt` (FastAPI, Pydantic, uvicorn, slowapi, psycopg, cryptography y prometheus-client). El hash de contraseñas y los tokens salen de la biblioteca estándar de Python (`hashlib.scrypt` y `secrets`).

## Puesta en marcha local

1. Instala PostgreSQL 16 y Python 3.12 o más nuevo.
2. Crea la base y ejecuta los scripts en orden con un usuario administrador de PostgreSQL.

```bash
createdb familiasquesuman
psql -d familiasquesuman -f db/01_esquema.sql
psql -d familiasquesuman -f db/02_catalogos.sql
psql -d familiasquesuman -f db/03_roles.sql
psql -d familiasquesuman -f db/04_backend.sql
psql -d familiasquesuman -f db/05_fase1.sql
psql -d familiasquesuman -f db/06_fase2.sql
psql -d familiasquesuman -f db/07_seguridad.sql
psql -d familiasquesuman -f db/08_seguridad2.sql
psql -d familiasquesuman -f db/09_telefono.sql
psql -d familiasquesuman -f db/10_idempotencia.sql
```

3. Crea el usuario con el que se conecta el backend. Pertenece al grupo `fqs_backend`, que solo puede leer y escribir datos (no puede borrar tablas ni cambiar el esquema).

```sql
CREATE ROLE fqs_api LOGIN PASSWORD 'una-contraseña-larga-y-aleatoria' IN ROLE fqs_backend;
```

4. Crea el entorno virtual e instala las dependencias.

```bash
python -m venv .venv
# Mac y Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
```

5. Copia `.env.example` como `.env` y llena `DATABASE_URL` con ese usuario. Genera la clave con la que se cifran los secretos del segundo factor y pégala en `CLAVE_CIFRADO_2FA`.

```bash
python -m fqs.scripts.generar_clave
```

6. Crea la primera cuenta de administración y arranca el servidor. La contraseña se escribe sin mostrarse y no queda en el historial.

```bash
python -m fqs.scripts.crear_admin
python -m fqs
```

7. Abre el panel web de administración en http://127.0.0.1:3000/panel/ y entra con esa cuenta. Si el segundo factor está en obligatorio, el panel te lleva a activarlo con un QR que escaneas con tu app de autenticación (también se puede desde la app, en Perfil, Seguridad de administración).
8. En el panel, en Ajustes, Aviso de privacidad, publica el aviso real de la organización. Sin él, el registro de familias responde 503 porque aceptarlo es obligatorio.

En desarrollo (`ENTORNO=development`) la documentación interactiva de FastAPI queda en http://127.0.0.1:3000/docs. En producción no se publica.

## Pruebas

Las pruebas corren contra una base PostgreSQL real que se borra y se vuelve a crear en cada ejecución, y levantan el servidor de verdad en un puerto libre. Nunca apuntes estas variables a la base de producción.

```bash
python -m pip install -r requirements-dev.txt
createdb fqs_test
export TEST_OWNER_DATABASE_URL=postgresql://postgres@localhost/fqs_test
export TEST_DATABASE_URL=postgresql://fqs_api_test:prueba-local-fqs@localhost/fqs_test
python -m pytest -q
```

En Windows (PowerShell) las variables se ponen con `$env:TEST_OWNER_DATABASE_URL="..."`.

La API se prueba conectada con un usuario de mínimo privilegio, así que también se comprueban los permisos de la base. Son 146 pruebas que cubren el flujo completo de familia y administración y estos casos de seguridad. La relación de cada prueba con el ataque que simula y su categoría OWASP está en [docs/seguridad/pruebas-automatizadas.md](docs/seguridad/pruebas-automatizadas.md), y los casos de rechazo que pide la rúbrica están juntos en `tests/test_08_rechazos.py`.

- Rutas sin sesión, con token inventado, manipulado o vencido, y rutas de administración usadas por una familia
- Asignación masiva (mandar `rol`, `estado` o campos no declarados)
- IDOR (editar, borrar o usar como acompañante el miembro de otra familia, leer la propuesta, la sesión o la inscripción de otra persona)
- Fuerza bruta en el inicio de sesión, límite por IP con 429 y Retry-After, bloqueo de cuenta aunque cambie la IP
- Límites por ruta en registro, recuperación, escrituras y subidas, y que no exista un límite global
- Reuso de un refresh token robado, que revoca toda la familia de sesiones
- Inyección SQL en el inicio de sesión, en búsquedas, filtros y parámetros de ruta, y comodines en la búsqueda
- Imágenes disfrazadas, tipo declarado falso, archivos de más de 5 MB y eliminación de metadatos EXIF y PNG
- Suspensión con efecto inmediato, recuperación de contraseña con código de un solo uso y eliminación de cuenta (derechos ARCO)
- Dos familias pidiendo el último lugar al mismo tiempo (solo una lo obtiene y la otra recibe un aviso claro)
- Una familia que pide otra ciudad en la URL, o que intenta ver o inscribirse a algo de una asociación sin verificar
- Flujo de cupos en tiempo real sin sesión y con más conexiones de las permitidas
- Entregas que mezclan el artículo de una campaña con el punto de entrega de otra
- Calificar o responder la encuesta posterior sin haber asistido (error diseñado de CU-02)
- Proponer una asociación que ya existe o repetir una propuesta abierta (error diseñado de CP-01)
- Envío push con un Firebase simulado, firma del JWT, token borrado cuando Firebase dice que ya no existe y sin envíos dobles
- Segundo factor de administración contra los vectores de los RFC 6238 y 4226, código repetido, desafío reusado o agotado y código de respaldo de un solo uso
- Administrar sin segundo factor, bitácora que el backend no puede editar ni borrar y alteración detectada por la cadena de hashes
- Correo y SMS por Brevo con una API simulada y configuración insegura rechazada al arrancar
- Registrar o poner en otra cuenta el correo o el teléfono de otra persona, códigos de verificación agotados o reusados
- Contraseñas que aparecen en filtraciones, sin mandar la contraseña ni el hash completo al servicio
- Cerrar sesiones de otro dispositivo, sesión de administración que pasa su tope, rotación de la clave del segundo factor
- Alertas por correo, ancla de la bitácora, poda que no rompe la cadena y cuentas inactivas
- Imágenes con un ZIP pegado, fragmentos privados, código en comentarios y bombas de descompresión
- Panel web con cookies HttpOnly, defensa contra CSRF, CSP estricta y archivos que no salen de su carpeta
- Métricas para Prometheus solo en su propio puerto, sin ids ni datos personales en las etiquetas

## Seguridad

La documentación completa (modelo de amenazas STRIDE, matriz de riesgos, resultados de sqlmap y OWASP ZAP, despliegue con HTTPS y túnel) está en [docs/seguridad](docs/seguridad/README.md).

**Sesiones.** El access token dura 15 minutos y el refresh token 30 días. Los dos son valores aleatorios de 256 bits y en la base solo se guarda su SHA-256. Cada renovación rota el refresh token. Si alguien presenta uno ya usado, se revoca toda la familia de sesiones, porque significa que el token se copió. Cerrar sesión, cambiar la contraseña o suspender una cuenta tiene efecto inmediato, cosa que un JWT no permite.

**Contraseñas.** Se guardan con scrypt (N=2^17, r=8, p=1, los mínimos de OWASP). Se exigen al menos 10 caracteres, se rechazan las más comunes y las que contienen el nombre, username o correo. El inicio de sesión tarda lo mismo exista o no la cuenta y responde el mismo mensaje, así no revela quién está registrado.

**Límites de peticiones.** Cada ruta sensible declara su propio límite con un decorador de slowapi. No hay un límite global para toda la API, así cada endpoint tiene el tope que corresponde a su riesgo.

| Límite | Rutas | Por |
|---|---|---|
| 20 cada 15 minutos | inicio de sesión y segundo paso con código (app y panel) | IP |
| 20 cada 15 minutos | renovación de sesión (app y panel) | IP |
| 10 por hora | registro | IP |
| 30 cada 15 minutos | verificar y reenviar códigos de registro, correo y teléfono | IP o cuenta |
| 5 por hora | recuperar y restablecer contraseña | IP |
| 30 por hora | propuestas, reportes, entregas, testimonios y respuestas de encuesta | cuenta |
| 30 por hora | subidas de imágenes | cuenta |

Además hay límites por cuenta que no dependen de la IP. Con 5 contraseñas o códigos equivocados la cuenta se bloquea 15 minutos aunque el atacante cambie de IP, y la recuperación acepta 5 solicitudes por cuenta cada hora. Al pasarse, la API responde 429 con el encabezado `Retry-After`. Los contadores viven en memoria, así que si algún día se corren varias instancias hay que moverlos a Redis (`storage_uri` de slowapi).

**Validación.** Cada cuerpo se valida con un modelo estricto de Pydantic, y un campo no declarado o de otro tipo responde 400. Los parámetros de ruta se validan como UUID antes de tocar la base. Todas las consultas usan parámetros de psycopg y nunca concatenan texto del cliente. Los errores de PostgreSQL se traducen a mensajes controlados, y un error inesperado responde 500 genérico con el detalle solo en la bitácora.

**Autorización.** Toda consulta de datos personales filtra por el usuario de la sesión. Las reglas críticas (cupos, edad mínima, dueño de los acompañantes, asistencia, transiciones de propuestas) viven en la base de datos, así que ni un error en el backend las puede saltar. Cada ruta declara su nivel de acceso con una dependencia de FastAPI (`Usuario` o `Admin`).

**Imágenes.** Se aceptan solo JPEG y PNG, el tipo se decide por los bytes del archivo y se reconstruyen solo con los segmentos necesarios. Se eliminan EXIF, XMP, IPTC, textos de PNG, segmentos desconocidos y cualquier dato después del final. Los PNG se descomprimen con tope (contra bombas) y se vuelven a comprimir. Se guardan con un nombre aleatorio fuera de cualquier carpeta pública. Una imagen solo la ve su dueño, un admin, o cualquiera con sesión si ya forma parte de contenido aprobado.

**Encabezados.** Se envían CSP restrictiva, `nosniff`, `no-store`, `X-Frame-Options`, `Referrer-Policy` y HSTS en producción. Uvicorn no manda el encabezado `Server`.

**Visibilidad.** Una familia solo ve contenido de la ciudad guardada en su perfil, aunque pida otra en la URL, y solo de asociaciones verificadas. Para cambiar de ciudad usa `PATCH /yo`. La persona administradora ve todo para poder revisarlo.

**Tiempo real.** `GET /v1/cupos/stream` es un flujo Server-Sent Events que exige sesión. Solo transmite números de lugares, nunca datos personales. Cada persona puede tener hasta 3 flujos abiertos y cada flujo se cierra a los 15 minutos para que la app se reconecte con un token vigente. PostgreSQL avisa el cambio con `NOTIFY` hasta que la transacción se confirma, así nunca se anuncia un lugar que al final se revirtió.

**Notificaciones push.** El backend firma un JWT con la llave de la cuenta de servicio de Firebase y lo cambia por un token OAuth de una hora con alcance solo de mensajería. La llave vive en un archivo fuera del repositorio (`FCM_CUENTA_SERVICIO`). El push solo lleva título, texto e identificadores, la app pide el detalle con su sesión. Cada notificación se reclama en la misma sentencia que la marca como enviada, así no sale dos veces. Los tokens que Firebase reporta como inexistentes se borran.

**Segundo factor.** Las cuentas de administración necesitan contraseña y un código TOTP de una app de autenticación. El secreto se guarda cifrado con AES-256-GCM, un código no se acepta dos veces y hay 10 códigos de respaldo de un solo uso. Sin segundo factor, una sesión de administración solo puede activarlo.

**Bitácora de seguridad.** Tabla de solo agregar donde cada fila lleva el hash de la anterior. Guarda cada acción de administración, cada acceso denegado, los inicios de sesión y códigos fallidos de administración y el reuso de tokens, sin cuerpos ni datos personales. El backend no puede editarla ni borrarla y `GET /v1/admin/bitacora/verificar` recalcula la cadena completa.

**Correo y SMS.** Los códigos y avisos salen por la API de Brevo (`BREVO_API_KEY` y `CORREO_REMITENTE`). El envío corre aparte de la petición, así el tiempo de respuesta no revela si la cuenta existe. Los SMS solo se mandan a México, máximo 5 por número y 200 en total al día, contra el fraude de bombeo de SMS.

**Verificación de contacto.** El registro responde 202 con un `registroId` y la cuenta se crea con `POST /v1/auth/registro/verificar` y el código de 8 dígitos que llega por correo o SMS. Cambiar el correo o el teléfono en `PATCH /yo` tampoco lo aplica hasta confirmarlo. Si el dato ya tiene cuenta, la respuesta es igual. El código de recuperación solo se manda a datos verificados.

**Contraseñas filtradas.** Al crear o cambiar una contraseña se consulta Pwned Passwords con k-anonimato (solo viajan 5 caracteres del SHA-1). Si el servicio no responde se acepta y queda un aviso en el log.

**Sesiones por dispositivo.** `GET /v1/yo/sesiones` lista los dispositivos con sesión abierta y cualquiera se cierra con `DELETE /v1/yo/sesiones/{id}`. Las de administración se cierran tras 30 minutos sin uso y nunca duran más de 12 horas.

**Alertas y retención.** Avisos por correo de eventos de seguridad, ancla semanal de la bitácora y política de retención. Ver [docs/seguridad/vigilancia-y-retencion.md](docs/seguridad/vigilancia-y-retencion.md).

**Log del servidor.** Es JSON por línea y nunca incluye cuerpos, contraseñas, tokens ni el encabezado Authorization.

**Reintentos sin duplicados.** `POST /v1/propuestas`, `/v1/reportes` y `/v1/yo/inscripciones/{id}/testimonio` aceptan el encabezado `Idempotency-Key` (de 16 a 64 letras, números, guiones o guiones bajos). La app lo manda en lo que se guardó sin conexión. Con la misma clave y el mismo cuerpo la API devuelve la respuesta original con `Idempotent-Replayed`, con otro cuerpo responde 422 y mientras la primera sigue en proceso responde 409. Las claves duran 48 horas.

**Monitoreo.** Con `METRICAS_PUERTO` la API publica métricas para Prometheus en un puerto aparte (tráfico y tiempos por plantilla de ruta, respuestas 429, inicios de sesión por resultado, eventos de la bitácora de seguridad y conexiones en tiempo real). Docker Compose trae Prometheus con reglas de alerta y Grafana con un tablero ya cargado. Ver [docs/seguridad/monitoreo.md](docs/seguridad/monitoreo.md).

## Producción

La forma recomendada es Docker Compose con Caddy, que obtiene y renueva solo el certificado HTTPS, respaldos cifrados y monitoreo con Prometheus y Grafana. Para la demostración por internet hay un perfil con un túnel de Cloudflare que no necesita abrir puertos. Está todo en [docs/seguridad/despliegue.md](docs/seguridad/despliegue.md), y para una máquina virtual de Azure en [docs/seguridad/despliegue-azure.md](docs/seguridad/despliegue-azure.md).

Sin Docker

- Pon el backend detrás de Nginx o Caddy con HTTPS y configura `TRUST_PROXY=1`. Deja `HOST=127.0.0.1` para que solo el proxy llegue al puerto. El backend ya envía `X-Accel-Buffering no` en el flujo de cupos para que Nginx no lo retenga.
- Usa `ENTORNO=production`. En ese modo el servidor se niega a arrancar si la conexión a una base remota no va cifrada, si el segundo factor de administración no es obligatorio o si el usuario de la base es superusuario o dueño del esquema.
- Respalda la base y la carpeta `UPLOAD_DIR` con `python -m fqs.scripts.respaldo` (cifrado) y comprueba de vez en cuando que se pueden abrir con `python -m fqs.scripts.restaurar archivo.json --solo-verificar`.
- Arranca con `python -m fqs` como servicio de systemd o con `uvicorn fqs.main:app`.

## Scripts

Todos se corren desde la carpeta del proyecto con el entorno virtual activo y leen `.env`.

| Comando | Para qué |
|---|---|
| `python -m fqs` | Arranca la API en `HOST` y `PORT` |
| `python -m pytest -q` | Las 146 pruebas contra PostgreSQL |
| `python -m fqs.scripts.crear_admin` | Crea la cuenta de administración o le restablece la contraseña |
| `python -m fqs.scripts.admin_2fa` | Borra el segundo factor de una cuenta de administración que perdió el teléfono y los códigos de respaldo |
| `python -m fqs.scripts.generar_clave` | Clave aleatoria de 32 bytes para `CLAVE_CIFRADO_2FA` o `RESPALDO_CLAVE` |
| `python -m fqs.scripts.rotar_clave_2fa` | Vuelve a cifrar los secretos del segundo factor con una clave nueva |
| `python -m fqs.scripts.podar_bitacora` | Archiva cifrados y borra los eventos de la bitácora más viejos que la retención |
| `python -m fqs.scripts.respaldo` | Respaldo cifrado de la base y las fotos |
| `python -m fqs.scripts.restaurar` | Verifica o restaura un respaldo |
| `python -m fqs.scripts.openapi` | Genera `docs/openapi.json` desde las rutas de FastAPI, para OWASP ZAP o Postman |
| `python -m pip_audit -r requirements.txt` | Revisa las dependencias contra la base de vulnerabilidades de PyPI |
| `python -m fqs.scripts.datos_prueba` | Datos de ejemplo para desarrollo y demostraciones |

## Estructura del código

| Carpeta | Contenido |
|---|---|
| `fqs/app.py` | Arma la aplicación FastAPI, los servicios y las tareas periódicas |
| `fqs/rutas/` | Un módulo por área (auth, perfil, participación, administración, panel) |
| `fqs/http/` | Middleware de encabezados y tamaños, dependencias de sesión, cookies del panel, manejo de errores |
| `fqs/seguridad/` | Contraseñas, sesiones, segundo factor, bitácora, imágenes, QR |
| `fqs/limites.py` | Límites de peticiones por ruta |
| `fqs/metricas.py` | Métricas para Prometheus y su servidor en un puerto aparte |
| `despliegue/azure/` | Script de Azure CLI y cloud-init para la máquina virtual |
| `docker/prometheus/`, `docker/grafana/` | Configuración de Prometheus, reglas de alerta, origen de datos y tablero de Grafana |
| `fqs/scripts/` | Scripts de operación |
| `db/` | Esquema, roles y reglas en SQL |
| `panel/` | Panel web de administración (HTML, CSS y JavaScript sin compilar) |
| `tests/` | Pruebas con pytest |

## Panel web de administración

El equipo administra todo desde el navegador en `/panel/` (asociaciones, actividades con participantes y asistencia, encuestas, proyectos, campañas, moderación, entregas, cuentas, catálogos, aviso de privacidad y seguridad). Lo sirve el mismo backend, sin dependencias ni compilación, con la sesión en cookies HttpOnly, defensa contra CSRF y una CSP que no permite scripts en línea. Detalles en [docs/seguridad/panel-web.md](docs/seguridad/panel-web.md).

Cuando una familia inscribe a un acompañante adulto con correo, esa persona recibe la confirmación por correo, y también el aviso si la actividad se cancela.

## Notificaciones push

1. En la consola de Firebase, en Configuración del proyecto y Cuentas de servicio, genera una clave privada y guárdala en la carpeta del backend como `firebase-cuenta-servicio.json`. Ya está en `.gitignore`, nunca la subas.
2. En `.env` agrega `FCM_CUENTA_SERVICIO=./firebase-cuenta-servicio.json`.
3. Cada `AVISOS_CADA_MINUTOS` (5 por defecto) el backend genera recordatorios de actividades del día siguiente e invitaciones a encuestas. Los avisos por favoritos y sugerencias se crean en la base al publicar una actividad o campaña.

Sin la variable el backend arranca igual, las notificaciones se ven dentro de la app pero no llegan como push.

## Endpoints

Todas las rutas están bajo `/v1`. Las públicas no requieren token, las demás requieren `Authorization` con `Bearer`. La lista completa con los modelos de cada cuerpo está en `docs/openapi.json`.

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/salud`, `/catalogos` | pública |
| POST | `/auth/registro`, `/auth/registro/verificar`, `/auth/registro/reenviar`, `/auth/login`, `/auth/2fa`, `/auth/refresh`, `/auth/logout`, `/auth/recuperar`, `/auth/restablecer` | pública |
| POST | `/yo/correo/verificar`, `/yo/telefono/verificar` | familia |
| GET | `/yo/sesiones` | familia |
| DELETE | `/yo/sesiones/{id}` | familia |
| POST | `/yo/sesiones/cerrar-otras` | familia |
| GET, PATCH | `/yo` | familia |
| GET | `/yo/privacidad` | familia |
| POST | `/yo/privacidad/aceptar` | familia |
| GET | `/cupos/stream` (Server-Sent Events) | familia |
| PUT | `/yo/preferencias` | familia |
| POST | `/yo/contrasena`, `/yo/eliminacion` | familia |
| GET | `/yo/inscripciones?momento=proximas\|pasadas\|todas`, `/yo/entregas` | familia |
| PUT, DELETE | `/yo/dispositivos` | familia |
| GET, POST | `/yo/comunidad` | familia |
| PUT, DELETE | `/yo/comunidad/{id}` | familia |
| GET | `/asociaciones` (ordenadas por calidad), `/asociaciones/{id}` | familia |
| PUT, DELETE | `/asociaciones/{id}/favorito` | familia |
| GET | `/actividades?tipo=voluntariado\|visita&orden=fecha\|calidad`, `/actividades/{id}`, `/actividades/{id}/testimonios`, `/actividades/{id}/encuestas` | familia |
| POST, DELETE | `/actividades/{id}/inscripcion` | familia |
| POST | `/yo/inscripciones/{id}/testimonio`, `/yo/inscripciones/{id}/respuestas` | familia |
| PUT, DELETE | `/yo/inscripciones/{id}/valoracion` | familia |
| GET | `/campanas?proyectoId=`, `/campanas/{id}` | familia |
| GET | `/proyectos`, `/proyectos/{id}` | familia |
| PUT, DELETE | `/actividades/{id}/favorito` | familia |
| GET | `/yo/favoritos`, `/testimonios` | familia |
| POST | `/campanas/{id}/entregas` | familia |
| DELETE | `/yo/entregas/{id}` | familia |
| GET, POST | `/propuestas` | familia |
| GET, PUT | `/propuestas/{id}` | familia |
| POST | `/reportes` | familia |
| GET | `/notificaciones` | familia |
| POST | `/notificaciones/{id}/leida`, `/notificaciones/leer-todas` | familia |
| DELETE | `/notificaciones/{id}` | familia |
| POST | `/archivos` (cuerpo binario image/jpeg o image/png) | familia |
| GET | `/archivos/{id}` | familia |
| POST | `/admin/ciudades`, `/admin/categorias`, `/admin/avisos-privacidad`, `/admin/niveles`, `/admin/insignias`, `/admin/encuestas` | admin |
| POST, PUT | `/admin/asociaciones`, `/admin/asociaciones/{id}` | admin |
| POST, PUT | `/admin/actividades`, `/admin/actividades/{id}` | admin |
| POST | `/admin/actividades/{id}/estado`, `/admin/actividades/{id}/cancelar` | admin |
| GET | `/admin/actividades/{id}/participantes` | admin |
| PUT | `/admin/participantes/{id}/asistencia` | admin |
| POST, PUT | `/admin/proyectos`, `/admin/proyectos/{id}` | admin |
| POST | `/admin/proyectos/{id}/estado` | admin |
| POST | `/admin/campanas`, `/admin/campanas/{id}/estado` | admin |
| GET, PUT | `/admin/entregas`, `/admin/entregas/{id}` | admin |
| GET, PUT | `/admin/propuestas`, `/admin/propuestas/{id}/revision` | admin |
| GET, PUT | `/admin/testimonios`, `/admin/testimonios/{id}` | admin |
| GET, PUT | `/admin/reportes`, `/admin/reportes/{id}` | admin |
| GET | `/admin/actividades/{id}/encuestas`, `/admin/encuestas/{id}/resultados` | admin |
| POST | `/admin/encuestas/{id}/estado` | admin |
| GET | `/admin/calidad` | admin |
| PUT | `/admin/usuarios/{id}/estado` | admin |
| GET, POST | `/admin/solicitudes-eliminacion`, `/admin/solicitudes-eliminacion/{id}/resolver` | admin |
| GET | `/admin/2fa` | admin sin segundo factor |
| POST | `/admin/2fa/iniciar`, `/admin/2fa/confirmar` | admin sin segundo factor |
| POST | `/admin/2fa/codigos-respaldo` | admin |
| GET | `/admin/bitacora?accion=&actorId=&antesDe=&limite=`, `/admin/bitacora/verificar?hastaId=&hash=`, `/admin/alertas` | admin |
| POST | `/admin/bitacora/anclar` | admin |
| GET | `/admin/resumen`, `/admin/asociaciones?q=&ciudadId=`, `/admin/asociaciones/{id}`, `/admin/actividades?q=&estado=&asociacionId=`, `/admin/actividades/{id}`, `/admin/proyectos`, `/admin/proyectos/{id}`, `/admin/campanas?estado=`, `/admin/usuarios?q=&rol=&estado=`, `/admin/niveles`, `/admin/insignias`, `/admin/avisos-privacidad` | admin |
| POST | `/panel/sesion`, `/panel/sesion/2fa`, `/panel/sesion/renovar`, `/panel/sesion/salir` | pública, solo para el panel (cookies) |
| GET | `/panel/sesion` | admin sin segundo factor |

Todas las rutas marcadas admin exigen, además del rol, una sesión abierta con segundo factor.

El panel usa estas mismas rutas con la cookie de sesión en lugar de `Authorization`. Con cookie, toda petición que no sea GET necesita el encabezado `X-FQS-Panel` con valor 1 y, si trae `Origin`, que sea el mismo host.

## Conectar la app Android

La dirección del backend se define en `gradle.properties` de la app, sin tocar código.

```properties
fqs.api.debug=http://10.0.2.2:3000/
fqs.api.release=https://api.tu-dominio.mx/
```

En el emulador, `10.0.2.2` es tu computadora. Para la versión release se puede activar la fijación de certificado con `fqs.api.pins`, ver [docs/seguridad/fijacion-certificado.md](docs/seguridad/fijacion-certificado.md). Para probar en un teléfono físico usa la IP local de tu computadora, arranca el backend con `HOST=0.0.0.0` y agrega esa IP en `app/src/debug/res/xml/network_security_config.xml`. El APK release solo permite HTTPS. Para la demostración por internet, `fqs.api.release` lleva la dirección pública del túnel.
