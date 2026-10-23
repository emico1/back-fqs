# Decisiones técnicas principales

Cada decisión indica qué se eligió, por qué y qué costo tuvo. Están en el orden en que afectan más la estructura del sistema.

## DT-01. Backend en Python con FastAPI

**Decisión.** La API está escrita en FastAPI sobre uvicorn, con Pydantic para validar y slowapi para los límites de peticiones.

**Por qué.** Es el framework que pide el curso. Pydantic valida cada cuerpo con modelos estrictos y responde 400 ante cualquier campo de más o de otro tipo, FastAPI genera la descripción OpenAPI directamente de las rutas (la que se usa para el escaneo con ZAP) y las dependencias permiten declarar en cada ruta el nivel de acceso que exige.

**Costo.** La validación de Pydantic corre después de leer el cuerpo, así que los límites de slowapi solo cuentan las peticiones bien formadas. Las mal formadas se rechazan con 400 sin tocar la base, así que no representan un riesgo de abuso.

## DT-02. Límites de peticiones por ruta, sin límite global

**Decisión.** Cada ruta sensible declara su límite con un decorador de slowapi (inicio de sesión, segundo paso, renovación, registro, verificación, recuperación, escrituras y subidas). No hay límite global.

**Por qué.** Un límite global castiga igual a una lectura del catálogo que a un intento de contraseña, y cuando una familia comparte la IP de la escuela o del trabajo con otras, todas pierden el servicio. Con límites por ruta cada endpoint tiene el tope de su riesgo. Además hay límites por cuenta (5 contraseñas equivocadas bloquean la cuenta 15 minutos) que no dependen de la IP, así un ataque distribuido tampoco funciona.

**Costo.** Los contadores viven en memoria de un solo proceso. Si se corren varias instancias hay que pasarlos a Redis con `storage_uri`.

## DT-03. Tokens opacos con sesiones en la base, no JWT

**Decisión.** El access token (15 minutos) y el refresh token (30 días) son valores aleatorios de 256 bits. En la base solo se guarda su SHA-256. Cada renovación rota el refresh token y reusar uno viejo revoca toda la familia de sesiones.

**Por qué.** Suspender una cuenta, cerrar sesión o cerrar otro dispositivo tiene efecto inmediato, cosa que un JWT no permite sin una lista de revocación. Si alguien lee la tabla de sesiones no obtiene tokens utilizables.

**Costo.** Una consulta a la base por petición para validar el token, que con el índice es de menos de un milisegundo.

## DT-04. Reglas críticas dentro de PostgreSQL

**Decisión.** Cupos, edad mínima, dueño de los acompañantes, transiciones de estado, asistencia antes de evaluar y la bitácora de solo agregar están en funciones y triggers de la base.

**Por qué.** Ningún error del backend puede saltarse esas reglas, y la concurrencia se resuelve con bloqueos de fila en la misma transacción. La prueba de dos familias pidiendo el último lugar al mismo tiempo lo comprueba.

**Costo.** Parte de la lógica está en SQL, así que quien mantenga el sistema necesita leer `db/`.

## DT-05. Rol de mínimo privilegio para la API

**Decisión.** La API se conecta con un rol del grupo `fqs_backend`, que solo lee y escribe datos. En producción el servidor se niega a arrancar si el rol es superusuario o dueño del esquema.

**Por qué.** Aunque alguien lograra una inyección SQL, no podría borrar tablas, cambiar el esquema ni alterar la bitácora.

## DT-06. Cuenta individual con acompañantes

**Decisión.** Todas las cuentas son individuales. La familia se arma registrando acompañantes (menores o adultos) dentro de la cuenta, y los adultos con correo reciben la confirmación cuando los inscriben.

**Por qué.** Lo pidió el socio formador en las preguntas del avance del reto (solo cuentas individuales y avisos por correo a los acompañantes). Evita cuentas compartidas, que no permiten saber quién hizo qué.

## DT-07. Panel web servido por la misma API, con sesión en cookies

**Decisión.** El panel de administración es HTML, CSS y JavaScript sin compilar, servido por la API en `/panel/`. La sesión va en cookies HttpOnly, Secure y SameSite Strict, y toda escritura con cookie exige el encabezado `X-FQS-Panel` y el mismo origen.

**Por qué.** Un script inyectado no puede leer los tokens. Sin dependencias de frontend no hay cadena de suministro que revisar. La CSP no permite scripts en línea.

## DT-08. Cupos en tiempo real con Server-Sent Events

**Decisión.** La app recibe los cambios de lugares por un flujo SSE que alimenta `NOTIFY` de PostgreSQL.

**Por qué.** SSE funciona sobre HTTP normal, pasa por Caddy y por el túnel sin configuración extra, y solo se necesita en una dirección. El aviso sale cuando la transacción se confirma, así nunca se anuncia un lugar que se revirtió.

## DT-09. Segundo factor obligatorio para administración

**Decisión.** Las cuentas de administración necesitan un código TOTP de una app de autenticación, con códigos de respaldo de un solo uso. En producción no se puede desactivar.

**Por qué.** Una cuenta de administración puede ver datos personales de todas las familias. Una contraseña filtrada sola no debe bastar.

## DT-10. Contenedores con Caddy y túnel opcional

**Decisión.** Docker Compose con PostgreSQL en una red interna sin salida, la API sin puertos publicados y Caddy como única entrada con HTTPS automático. Para la demostración por internet hay un perfil con cloudflared.

**Por qué.** Los secretos van en variables de entorno y en un secreto de Docker, nunca en la imagen. El túnel permite que la app en un teléfono físico use el backend desde cualquier red sin abrir puertos en la computadora.

## DT-11. Sin conexión con copias cifradas y una cola de envíos idempotente

**Decisión.** La app guarda en Room la última respuesta de cada consulta y una cola de escrituras pendientes, las dos cifradas con AES-256-GCM y una llave del Android Keystore. WorkManager manda la cola cuando vuelve la red. Solo entran a la cola las escrituras que no compiten por un recurso limitado (favoritos, calificaciones, propuestas, reportes y testimonios). Cada una lleva un `Idempotency-Key` y la API guarda 48 horas la respuesta de cada clave.

**Por qué.** Muchas familias usan datos móviles limitados o tienen mala señal en los lugares de las actividades. Con las copias pueden revisar actividades, campañas, su historial y sus notificaciones sin red, y con la cola no pierden un reporte o una experiencia escrita en el lugar. Una inscripción hecha sin conexión podría tomar un lugar que ya no existe, por eso inscribirse, cancelar y registrar entregas siguen siendo solo en línea. La clave de idempotencia evita duplicados cuando el teléfono envía, pierde la red antes de recibir la respuesta y vuelve a intentar.

**Costo.** Lo que se ve sin conexión puede no estar al día, por eso el aviso al pie dice desde qué hora es la copia. Lo que quede en la cola al cerrar sesión sin red se pierde, porque los datos de una cuenta no deben quedarse en el teléfono para la siguiente persona.

## DT-12. Monitoreo con Prometheus y Grafana en un puerto aparte

**Decisión.** La API publica sus métricas con `prometheus-client` en un servidor propio dentro del mismo proceso, en `METRICAS_PUERTO`, y no como una ruta de FastAPI. Prometheus y Grafana corren en el mismo Docker Compose, en una red interna sin internet.

**Por qué.** Las métricas dicen cuántos ataques se están rechazando y qué rutas reciben más tráfico, así que no deben estar en el puerto que Caddy y el túnel publican. Con un puerto que solo escucha en la red de monitoreo no hace falta autenticación ni excepciones en el proxy. Las etiquetas usan la plantilla de la ruta para que nadie pueda llenar Prometheus de series mandando direcciones inventadas, y nunca llevan ids, correos ni IPs.

**Costo.** Las alertas se ven en Grafana y en Prometheus pero no salen por correo (no se agregó Alertmanager), porque los eventos de seguridad ya se mandan por correo desde la API. Con varias instancias de la API, cada una tendría sus propias métricas y Prometheus tendría que leerlas todas.

## DT-13. Máquina virtual de Azure con entrada solo por el túnel

**Decisión.** El despliegue preparado es una máquina virtual Ubuntu 24.04 (`Standard_B2als_v2`, Trusted Launch) en Azure Chile Central, creada con `despliegue/azure/crear-vm.ps1` (o `crear-vm.sh`) y configurada con cloud-init. El grupo de seguridad de red solo abre SSH para la IP de quien administra, con llave Ed25519. La app llega por el túnel de Cloudflare, que sale desde la máquina.

**Por qué.** Se buscó Mexico Central para que los datos quedaran en México, pero la suscripción Azure for Students solo permite cinco regiones y de ellas Chile Central era la única con máquinas x86 económicas. Sin puertos web abiertos no hay nada que escanear desde internet salvo Cloudflare, y el mismo `docker-compose.yml` que se usa en una computadora corre igual en la máquina, así lo que se probó es lo que se despliega.

**Costo.** Los datos personales quedan fuera de México, por eso el aviso de privacidad debe informar la transferencia internacional, y en producción conviene una suscripción de la organización en `mexicocentral`. La máquina cobra mientras está encendida, por eso el procedimiento incluye apagarla con `az vm deallocate` cuando no se usa. Quien opera necesita una llave SSH y actualizar la regla si cambia su IP.
