# Matriz de riesgos

Cada amenaza del [modelo STRIDE](modelo-amenazas-stride.md) se califica con probabilidad (P) e impacto (I) del 1 al 5. El riesgo es P por I. El riesgo inherente supone el sistema sin el control, el residual con los controles ya implementados.

| Nivel | Rango |
|---|---|
| Crítico | 15 a 25 |
| Alto | 10 a 14 |
| Medio | 5 a 9 |
| Bajo | 1 a 4 |

Criterios de impacto. 5 exposición masiva de datos de familias o menores, o control total de la administración. 4 datos o acciones de varias cuentas. 3 una cuenta o un dato de negocio alterado. 2 molestia o servicio degradado. 1 sin efecto real.

| Id | Amenaza | P | I | Inherente | Control principal | P | I | Residual |
|---|---|---|---|---|---|---|---|---|
| T-01 | Fuerza bruta de contraseñas | 4 | 3 | 12 Alto | Bloqueo por cuenta e IP, scrypt | 1 | 3 | 3 Bajo |
| T-02 | Credenciales filtradas contra administración | 3 | 5 | 15 Crítico | Segundo factor obligatorio | 1 | 5 | 5 Medio |
| T-03 | Robo de refresh token | 2 | 4 | 8 Medio | Rotación con detección de reuso, Keystore | 1 | 3 | 3 Bajo |
| T-04 | Reuso de código TOTP | 2 | 5 | 10 Alto | Último paso guardado | 1 | 5 | 5 Medio |
| T-05 | Adivinar código de recuperación | 3 | 4 | 12 Alto | Un solo uso, 30 minutos, 5 intentos | 1 | 4 | 4 Bajo |
| T-06 | IP falsa para evadir límites | 4 | 2 | 8 Medio | Proxies de confianza | 1 | 2 | 2 Bajo |
| T-07 | Servidor falso en Wi-Fi pública | 2 | 4 | 8 Medio | HTTPS, CA del sistema | 1 | 4 | 4 Bajo |
| T-08 | Inyección SQL | 4 | 5 | 20 Crítico | Consultas parametrizadas | 1 | 5 | 5 Medio |
| T-09 | Asignación masiva | 3 | 5 | 15 Crítico | Esquemas estrictos | 1 | 5 | 5 Medio |
| T-10 | Carrera por el último lugar | 4 | 2 | 8 Medio | Bloqueo de fila | 1 | 2 | 2 Bajo |
| T-11 | Valoraciones falsas | 3 | 3 | 9 Medio | Asistencia obligatoria | 1 | 3 | 3 Bajo |
| T-12 | Alterar la bitácora | 2 | 4 | 8 Medio | Permisos, trigger y cadena de hashes | 1 | 4 | 4 Bajo |
| T-13 | Archivo malicioso como imagen | 3 | 4 | 12 Alto | Validación por contenido | 1 | 3 | 3 Bajo |
| T-14 | Respaldo alterado | 1 | 5 | 5 Medio | GCM y manifiesto | 1 | 2 | 2 Bajo |
| T-15 | Negar una acción de administración | 3 | 3 | 9 Medio | Bitácora encadenada | 1 | 2 | 2 Bajo |
| T-16 | Intentos de acceso sin rastro | 3 | 3 | 9 Medio | Eventos de seguridad | 1 | 2 | 2 Bajo |
| T-17 | IDOR | 4 | 4 | 16 Crítico | Filtro por dueño | 1 | 4 | 4 Bajo |
| T-18 | Saber quién está registrado | 4 | 2 | 8 Medio | Respuestas iguales | 2 | 2 | 4 Bajo |
| T-19 | Base de datos filtrada | 2 | 5 | 10 Alto | Hashes, cifrado, red interna | 1 | 3 | 3 Bajo |
| T-20 | Ubicación en fotos | 4 | 4 | 16 Crítico | Eliminación de metadatos | 1 | 4 | 4 Bajo |
| T-21 | Captura de pantalla sensible | 2 | 3 | 6 Medio | Contraseñas ocultas por omisión, riesgo aceptado para poder grabar y proyectar la app | 2 | 2 | 4 Bajo |
| T-22 | Errores con detalles internos | 3 | 2 | 6 Medio | Errores genéricos | 1 | 2 | 2 Bajo |
| T-23 | Llaves en el repositorio | 3 | 5 | 15 Crítico | gitignore y secretos | 1 | 5 | 5 Medio |
| T-24 | Respaldos robados | 2 | 5 | 10 Alto | Cifrado AES-256-GCM | 1 | 5 | 5 Medio |
| T-25 | Inundación de peticiones | 4 | 2 | 8 Medio | Límites por ruta | 2 | 2 | 4 Bajo |
| T-26 | Cuerpos enormes o conexiones lentas | 3 | 2 | 6 Medio | Tamaños y tiempos máximos | 1 | 2 | 2 Bajo |
| T-27 | Muchos flujos en vivo | 3 | 2 | 6 Medio | 3 por persona | 1 | 2 | 2 Bajo |
| T-28 | Pérdida de la base | 2 | 5 | 10 Alto | Respaldos verificados | 1 | 3 | 3 Bajo |
| T-29 | Familia en rutas de administración | 4 | 5 | 20 Crítico | Verificación de rol | 1 | 5 | 5 Medio |
| T-30 | Sesión de administración sin segundo factor | 3 | 5 | 15 Crítico | Segundo factor exigido por ruta | 1 | 5 | 5 Medio |
| T-31 | Inyección con privilegios altos | 2 | 5 | 10 Alto | Rol mínimo | 1 | 3 | 3 Bajo |
| T-32 | Escape del contenedor | 1 | 5 | 5 Medio | Contenedor endurecido | 1 | 4 | 4 Bajo |
| T-33 | Dependencia vulnerable | 3 | 4 | 12 Alto | Pocas dependencias y Dependabot | 2 | 3 | 6 Medio |

Riesgos agregados en la segunda ronda de controles.

| Id | Amenaza | P | I | Inherente | Control principal | P | I | Residual |
|---|---|---|---|---|---|---|---|---|
| T-34 | Apartar el correo de otra persona | 3 | 4 | 12 Alto | Verificación por código | 1 | 3 | 3 Bajo |
| T-35 | Contraseña de una filtración | 4 | 3 | 12 Alto | Pwned Passwords | 2 | 3 | 6 Medio |
| T-36 | Sesión en un teléfono perdido | 3 | 3 | 9 Medio | Mis dispositivos, sesión corta de admin | 1 | 3 | 3 Bajo |
| T-37 | Imagen políglota o bomba | 2 | 3 | 6 Medio | Reconstrucción con topes | 1 | 2 | 2 Bajo |
| T-38 | Reescribir la bitácora completa | 1 | 4 | 4 Bajo | Ancla externa | 1 | 2 | 2 Bajo |
| T-39 | Clave del segundo factor filtrada | 1 | 5 | 5 Medio | Rotación versionada | 1 | 3 | 3 Bajo |
| T-40 | Retener datos de más | 4 | 2 | 8 Medio | Política de retención | 1 | 2 | 2 Bajo |
| T-41 | Ataque sin que nadie se entere | 3 | 4 | 12 Alto | Alertas por correo | 1 | 4 | 4 Bajo |
| T-42 | Registrar el teléfono de otra persona | 3 | 3 | 9 Medio | Código por SMS | 1 | 3 | 3 Bajo |
| T-43 | Bombeo de SMS | 3 | 3 | 9 Medio | Solo México y topes diarios | 1 | 2 | 2 Bajo |
| T-44 | Wrapper de Gradle alterado | 2 | 4 | 8 Medio | Validación en CI y SHA-256 | 1 | 4 | 4 Bajo |
| T-45 | Correos a direcciones ajenas por inscripciones | 3 | 2 | 6 Medio | Solo adultos y tope diario | 1 | 2 | 2 Bajo |
| T-46 | Robo de la sesión del panel por script | 3 | 5 | 15 Crítico | Cookies HttpOnly y CSP | 1 | 5 | 5 Medio |
| T-47 | Lectura de archivos por la ruta del panel | 3 | 5 | 15 Crítico | Archivos en memoria | 1 | 5 | 5 Medio |
| T-48 | Correo a menores o con datos de quien inscribe | 2 | 3 | 6 Medio | Edad al evento y minimización | 1 | 3 | 3 Bajo |
| T-49 | CSRF contra el panel | 3 | 4 | 12 Alto | SameSite, encabezado propio y Origin | 1 | 4 | 4 Bajo |
| T-50 | XSS almacenado en el panel | 3 | 5 | 15 Crítico | textContent y CSP | 1 | 5 | 5 Medio |
| T-51 | Familia en el panel | 3 | 4 | 12 Alto | Rol revisado al iniciar sesión | 1 | 4 | 4 Bajo |

El riesgo residual de T-35 queda en medio porque, si el servicio de Pwned Passwords no responde, la contraseña se acepta para no impedir el registro. Lo mismo pasa si la contraseña se filtra después de crearla.

## Riesgos que se aceptan o quedan pendientes

| Riesgo | Situación | Qué haría falta |
|---|---|---|
| Límites en memoria | Si se corren varias instancias de la API, cada una lleva su cuenta | Mover los contadores a PostgreSQL o Redis |
| Persona de administración con malware en su computadora | El segundo factor no protege una sesión ya abierta en un equipo comprometido. Las cookies HttpOnly evitan que un script de una página las lea, pero no protegen de un programa instalado en la computadora | Usar el panel solo desde equipos de la organización con el sistema actualizado |
| Hora local del navegador en el panel | Las fechas de actividades se capturan en la hora de la computadora de quien las escribe | Que el equipo trabaje con la hora de México de su ciudad, o capturar con la zona horaria de la ciudad si se abren ciudades en otra zona |
| SMS sin créditos o desactivado | Con `SMS=desactivado` el registro solo con teléfono no está disponible en producción | Comprar créditos de SMS en Brevo y poner `SMS=brevo` |
| Alertas que dependen del correo | Si Brevo falla o el correo cae en spam nadie se entera | Revisar `GET /v1/admin/alertas` de vez en cuando y configurar SPF, DKIM y DMARC |
| Teléfono con root | Con root se puede leer la memoria de la app | Detección de root o Play Integrity, fuera del alcance de una organización pequeña |
| Fijación de certificado desactivada por omisión | Mal configurada puede dejar la app sin servicio | Activarla con las huellas de las raíces de Let's Encrypt, ver [fijacion-certificado.md](fijacion-certificado.md) |
| Clave de cifrado de 2FA y de respaldos en el mismo servidor | Quien tenga el servidor completo tiene ambas. Ya se pueden rotar, pero rotar no ayuda si nadie se entera de la filtración | Guardar `RESPALDO_CLAVE` solo donde corre el respaldo y una copia impresa en resguardo |
| Imágenes sin re-codificar | Se reconstruyen por estructura, no píxel por píxel | Re-codificar con una biblioteca de imágenes (por ejemplo sharp) si algún día se acepta una dependencia nativa |
