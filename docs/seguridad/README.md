# Seguridad de Familias que Suman

Este directorio reúne la evidencia de seguridad del proyecto para la materia Integración de seguridad informática en redes y sistemas de software. Todo lo que se describe aquí está implementado en el código de este repositorio y en la app Android, y la mayoría se comprueba con pruebas automáticas.

| Documento | Contenido |
|---|---|
| [modelo-amenazas-stride.md](modelo-amenazas-stride.md) | Activos, fronteras de confianza y amenazas por categoría STRIDE con su control |
| [matriz-riesgos.md](matriz-riesgos.md) | Probabilidad, impacto, riesgo inherente y residual de cada amenaza |
| [pruebas-automatizadas.md](pruebas-automatizadas.md) | Las 146 pruebas, qué ataque simula cada una y su categoría OWASP |
| [panel-web.md](panel-web.md) | Panel web de administración, sesión en cookies, defensa contra CSRF y XSS, y correo a acompañantes |
| [escaneos.md](escaneos.md) | Resultados de sqlmap y OWASP ZAP contra la API real, y guía de MobSF para el APK |
| [segundo-factor.md](segundo-factor.md) | Cómo funciona y cómo se activa la verificación en dos pasos de administración |
| [despliegue.md](despliegue.md) | Docker Compose con HTTPS automático, correo con Brevo y respaldos cifrados |
| [despliegue-azure.md](despliegue-azure.md) | Máquina virtual de Azure en Chile Central, solo SSH con llave Ed25519 y entrada por el túnel |
| [monitoreo.md](monitoreo.md) | Métricas de la API, Prometheus con reglas de alerta y Grafana con el tablero de tráfico y seguridad |
| [vigilancia-y-retencion.md](vigilancia-y-retencion.md) | Alertas por correo, ancla semanal de la bitácora y cuánto tiempo se guarda cada dato |
| [fijacion-certificado.md](fijacion-certificado.md) | Cómo activar la fijación de certificado en la app |
| [evidencia/](evidencia) | Salidas crudas de las herramientas |

## Resumen de controles

### Identidad y sesiones
- Contraseñas con scrypt N=2^17, r=8, p=1, los parámetros mínimos de la hoja de OWASP para almacenamiento de contraseñas. Se re-hashean solas si algún día se suben los parámetros.
- Mismo mensaje y mismo tiempo de respuesta exista o no la cuenta, así no se puede averiguar quién está registrado.
- Tokens opacos de 256 bits. En la base solo se guarda su SHA-256. El access dura 15 minutos y el refresh 30 días, con rotación en cada uso. Presentar un refresh ya usado revoca toda la familia de sesiones y queda en la bitácora.
- Límites declarados ruta por ruta con slowapi (inicio de sesión, segundo paso, renovación, registro, verificación, recuperación, escrituras y subidas), sin límite global. Bloqueo de 15 minutos tras 5 contraseñas o códigos equivocados por cuenta, aunque cambie la IP. Al pasarse, 429 con `Retry-After`.
- El registro con correo no crea la cuenta hasta que se escribe el código que llega a ese correo, y un cambio de correo no se aplica hasta verificar el nuevo. Así nadie puede apartar el correo de otra persona. Si el correo ya tiene cuenta, la respuesta es la misma y a ese correo le llega un aviso, así el registro tampoco revela quién está registrado.
- Lo mismo con el teléfono. El registro solo con teléfono, el cambio de teléfono y la recuperación por teléfono usan un código por SMS. Solo se mandan SMS a números de México, con tope por número y por día contra el fraude de bombeo de SMS, y del número solo se guarda su hash en el registro de envíos.
- Las contraseñas nuevas se comparan contra las filtraciones conocidas de Pwned Passwords con k-anonimato. Solo viajan 5 caracteres del SHA-1, nunca la contraseña.
- Cada persona ve sus sesiones por dispositivo y puede cerrar cualquiera desde la app.
- Recuperación de contraseña con código de 8 dígitos, de un solo uso, que vence en 30 minutos, se guarda como hash y cierra todas las sesiones al usarse. El correo sale por la API de Brevo sin esperar la respuesta, así el tiempo no revela si la cuenta existe.

### Administración
- Verificación en dos pasos obligatoria con TOTP (RFC 6238). El secreto se guarda cifrado con AES-256-GCM usando el id de la cuenta como dato asociado. Un código no se acepta dos veces. Hay 10 códigos de respaldo de un solo uso guardados como hash. Ver [segundo-factor.md](segundo-factor.md).
- Las sesiones de administración se cierran tras 30 minutos sin uso y nunca duran más de 12 horas.
- La clave que cifra los secretos se puede rotar sin que nadie reactive su app (`python -m fqs.scripts.rotar_clave_2fa`).
- Sin el segundo factor, una sesión de administración no puede usar ninguna ruta de administración salvo las que sirven para activarlo. Activarlo pide la contraseña otra vez.
- Bitácora de seguridad de solo agregar. Cada acción de administración que cambia algo, cada acceso denegado, los inicios de sesión de administración, los códigos fallidos y el reuso de tokens quedan registrados con quién, qué, sobre qué id, desde qué IP y cuándo. Nunca se guarda el cuerpo de la petición.
- Avisos por correo de inicios de sesión de administración, códigos de respaldo usados, segundo factor reiniciado, sesiones copiadas y ráfagas de intentos fallidos. Ancla semanal con el último hash enviada fuera del servidor. Ver [vigilancia-y-retencion.md](vigilancia-y-retencion.md).
- Panel web en `/panel/` con la sesión en cookies HttpOnly, `Secure`, `SameSite=Strict` y prefijo `__Host-`, que el JavaScript nunca ve. Toda acción con cookie exige el encabezado `X-FQS-Panel` y el mismo origen (defensa contra CSRF). CSP sin scripts en línea y todo el texto colocado con `textContent` (defensa contra XSS). Ver [panel-web.md](panel-web.md).
- La bitácora es una cadena de hashes SHA-256. El rol del backend no tiene permiso de UPDATE, DELETE ni TRUNCATE, un trigger lo impide incluso al dueño de la base, y si alguien con acceso total lo desactiva y altera una fila, `GET /v1/admin/bitacora/verificar` señala la fila exacta.

### Autorización y datos
- Cada ruta declara si es pública, de usuario o de administración y el enrutador lo aplica antes de llegar al código de la ruta.
- Los parámetros de ruta solo aceptan UUID. Cualquier otra cosa responde 404 sin tocar la base.
- Modelos estrictos de Pydantic en todas las entradas, un campo no declarado (por ejemplo `rol`) responde 400.
- Toda consulta usa parámetros de PostgreSQL. sqlmap no encontró ningún parámetro inyectable (ver [escaneos.md](escaneos.md)).
- Cada consulta de datos de una familia filtra por su id (protección contra IDOR) y por su ciudad.
- El backend se conecta con un rol de mínimo privilegio que no puede cambiar el esquema. En producción se niega a arrancar con un superusuario.
- Las imágenes se validan por su contenido real y se reconstruyen solo con lo necesario para mostrarlas. Se quitan los metadatos EXIF y PNG (que pueden traer la ubicación GPS), los segmentos desconocidos y cualquier dato pegado después del final (archivos políglota). Los PNG se descomprimen con tope de tamaño (contra bombas de descompresión) y se vuelven a comprimir. Solo las ve su dueño o el equipo.
- Retención definida para cada dato, poda de la bitácora que no rompe la cadena y aviso a cuentas sin uso. Ver [vigilancia-y-retencion.md](vigilancia-y-retencion.md).

### Transporte e infraestructura
- HTTPS con Caddy, certificado automático y renovación sin intervención. Redirección de HTTP a HTTPS, TLS 1.2 y 1.3, HSTS de un año. Ver [despliegue.md](despliegue.md) y la [evidencia](evidencia/https-caddy.txt).
- La API toma la IP real del encabezado que agrega el proxy y no del que manda el cliente, así los límites por IP no se pueden evadir falsificando `X-Forwarded-For`.
- En Docker la base vive en una red sin salida a internet y sin puertos publicados. La API corre sin root, con el sistema de archivos de solo lectura, sin capacidades de Linux y sin poder escalar privilegios.
- Respaldos cifrados con AES-256-GCM, con manifiesto SHA-256 y verificación periódica de que se pueden abrir.
- Dependabot y `pip-audit` en cada cambio y cada lunes. CodeQL para Python, JavaScript del panel y Kotlin, Android Lint y gitleaks sobre todo el historial del repositorio. La app trae el wrapper de Gradle con la suma SHA-256 de la distribución y CI valida que el jar del wrapper sea uno oficial. El escaneo de gitleaks de lo entregado está en [evidencia/gitleaks.txt](evidencia/gitleaks.txt).
- Logs de Docker con rotación para no guardar IPs de forma indefinida.
- Monitoreo con Prometheus y Grafana. Las métricas salen en un puerto que solo escucha en una red interna de monitoreo, sin datos personales en las etiquetas. Prometheus no publica puertos y Grafana solo escucha en 127.0.0.1 con contraseña del entorno. Hay alertas de API caída, errores 5xx, ráfagas de 429, inicios de sesión fallidos, fallos de administración, accesos denegados y reuso de refresh tokens. Ver [monitoreo.md](monitoreo.md).

### App Android
- Sesión guardada con AES-GCM y una llave del Android Keystore, nunca en texto plano.
- Lo que se guarda para usar sin conexión (copias de consultas, envíos pendientes y sus fotos) va cifrado con AES-GCM y otra llave del Keystore, con la clave de cada registro como dato asociado. La base de Room y las fotos no se respaldan en la nube ni pasan a otro teléfono, y se borran al cerrar sesión, al expirar la sesión o al pedir la eliminación de la cuenta.
- Los envíos hechos sin conexión llevan `Idempotency-Key`, así un reintento nunca crea duplicados en el servidor.
- Sin tráfico HTTP en la versión release y solo certificados del sistema, no los que instale el usuario.
- Las contraseñas se muestran ocultas por omisión. Las pantallas se pueden capturar y grabar para las demostraciones y los videos de evidencia, riesgo aceptado en T-21.
- Fijación de certificado opcional por configuración de Gradle.
- El token solo se envía al host del backend. Los enlaces de notificaciones push se validan antes de navegar.
- Código ofuscado y recursos sin uso eliminados en release.

## Correspondencia con OWASP API Security Top 10 2023

| Riesgo | Cómo se atiende |
|---|---|
| API1 Autorización a nivel de objeto | Filtro por dueño en cada consulta, pruebas de IDOR en comunidad, inscripciones, propuestas, imágenes y testimonios |
| API2 Autenticación rota | scrypt, contraseñas filtradas rechazadas, correo verificado, tokens opacos con rotación y detección de reuso, bloqueo por cuenta, segundo factor y sesión corta para administración, sesiones por dispositivo |
| API3 Autorización a nivel de propiedad | Esquemas estrictos que rechazan campos no declarados, respuestas con columnas explícitas sin hashes |
| API4 Consumo de recursos sin límite | Límites por ruta (por IP o por cuenta según el riesgo), cuerpo máximo de 64 KB en JSON y 5 MB en imágenes, tiempos máximos por consulta y por conexión, máximo 3 flujos en vivo por persona |
| API5 Autorización a nivel de función | Rutas de administración separadas, verificadas por rol y segundo factor antes del manejador, intentos registrados en la bitácora |
| API6 Flujos de negocio sensibles | Cupos con bloqueo de fila para que el último lugar sea de una sola familia, valoraciones solo con asistencia registrada, una sugerencia diaria por persona |
| API7 SSRF | La API no descarga nada de URLs que mande el cliente |
| API8 Configuración insegura | Encabezados de seguridad, sin `X-Powered-By`, errores genéricos sin pila, configuración validada al arrancar que se niega a correr insegura en producción |
| API9 Inventario | `python -m fqs.scripts.openapi` genera la lista completa de rutas desde el código, versión `v1` en todas |
| API10 Consumo inseguro de APIs | Respuestas de Firebase y Brevo validadas por código de estado, tiempos máximos, credenciales fuera del repositorio |

## Correspondencia con OWASP MASVS v2

| Categoría | Control en la app |
|---|---|
| MASVS-STORAGE | Tokens cifrados con Keystore, `allowBackup` limitado por reglas de extracción, archivos temporales de fotos en caché privada |
| MASVS-CRYPTO | AES-GCM del sistema, sin criptografía propia |
| MASVS-AUTH | La autenticación vive en el servidor, renovación automática, cierre de sesión que revoca en el servidor, segundo factor para administración |
| MASVS-NETWORK | HTTPS obligatorio en release, solo CA del sistema, fijación opcional |
| MASVS-PLATFORM | FileProvider en lugar de rutas de archivo, enlaces de push validados, portapapeles marcado como sensible |
| MASVS-CODE | Dependencias con versión fija y Dependabot, minSdk 26 |
| MASVS-RESILIENCE | R8 con ofuscación en release |
| MASVS-PRIVACY | Aviso de privacidad versionado con aceptación registrada, eliminación de cuenta desde la app, metadatos de fotos eliminados |

## Fuentes
- [OWASP API Security Top 10 2023](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
- [OWASP MASVS](https://mas.owasp.org/MASVS/)
- [Pwned Passwords y su relleno de respuestas, Troy Hunt](https://troyhunt.com/enhancing-pwned-passwords-privacy-with-padding)
- [CodeQL para lenguajes compilados, GitHub Docs](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/manage-your-configuration/codeql-for-compiled-languages)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [RFC 6238, TOTP](https://www.rfc-editor.org/rfc/rfc6238) y [RFC 4226, HOTP](https://www.rfc-editor.org/rfc/rfc4226)
- [NIST SP 800-63B, Authentication and Lifecycle Management](https://pages.nist.gov/800-63-4/sp800-63b.html)
- [Ley Federal de Protección de Datos Personales en Posesión de los Particulares, DOF 20 de marzo de 2025](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf)
- [API de correo transaccional de Brevo](https://developers.brevo.com/docs/send-a-transactional-email)
- [API de SMS transaccional de Brevo](https://developers.brevo.com/docs/transactional-sms-endpoints)
- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Set-Cookie y prefijos de cookies, MDN](https://developer.mozilla.org/pt-BR/docs/Web/HTTP/Reference/Headers/Set-Cookie)
