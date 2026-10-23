# Pruebas automatizadas de seguridad

Las 146 pruebas de la carpeta `tests/` (pytest) levantan la API real con uvicorn contra una base PostgreSQL 16 real, conectada con el mismo rol de mínimo privilegio que se usa en producción. Así no solo se prueba el código sino también los permisos de la base, los triggers y las funciones. Cada ejecución borra y vuelve a crear el schema desde los scripts de `db/`, del 01 al 10. Las pruebas le hablan a la API por HTTP, igual que la app.

```bash
python -m pytest -v
```

Resultado de la última ejecución, 146 pruebas, 146 correctas, 0 fallidas (ver [evidencia/pruebas.txt](evidencia/pruebas.txt)).

| Archivo | Secciones |
|---|---|
| `tests/test_01_base.py` | Seguridad HTTP general, registro e inicio de sesión, límites de peticiones, sesiones con refresh rotativo |
| `tests/test_02_flujo.py` | Flujo completo de familia y administración, subida de imágenes, cuenta, suspensión, recuperación y eliminación |
| `tests/test_03_fase1.py` | Ciudad, verificación de asociaciones, tipos, cupos en vivo, proyectos y privacidad |
| `tests/test_04_fase2.py` | Avisos, favoritos, encuestas, calidad, propuestas, testimonios, límite de escrituras y push |
| `tests/test_05_seguridad.py` | Segundo factor, bitácora encadenada, correo y configuración |
| `tests/test_06_cuenta.py` | Verificación de correo, contraseñas filtradas, sesiones, alertas, retención e imágenes |
| `tests/test_07_sms_panel.py` | SMS, panel web y correo a acompañantes |
| `tests/test_08_rechazos.py` | Casos de rechazo de la rúbrica (inyección SQL, tokens, IDOR, exceso de peticiones) |
| `tests/test_09_metricas.py` | Métricas para Prometheus |
| `tests/test_10_idempotencia.py` | Reintentos de envíos hechos sin conexión con Idempotency-Key |

La tabla indica qué ataque o error simula cada prueba y a qué categoría de OWASP API Security Top 10 2023 corresponde. Las pruebas de funcionalidad sin un ataque asociado se marcan como Negocio.

## Seguridad HTTP general

| Prueba | Qué simula | OWASP |
|---|---|---|
| encabezados de seguridad y sin X-Powered-By | Recolección de información del servidor, falta de encabezados | API8 |
| rutas protegidas exigen sesión y los admin exigen rol | Acceso sin token o con token inventado | API2, API5 |
| parámetro que no es UUID responde 404 sin tocar la base | Inyección SQL en el id de la URL (`1' OR 1=1`) | API8 |
| cuerpo que no es JSON o demasiado grande | Tipo de contenido inesperado, cuerpo de 70 KB, JSON malformado | API4 |
| método no permitido | Métodos HTTP no declarados | API8 |
| ruta inexistente | Respuesta de error uniforme con id de petición | API8 |

## Registro e inicio de sesión

| Prueba | Qué simula | OWASP |
|---|---|---|
| sin aviso de privacidad publicado el registro no está disponible | Registro sin consentimiento informado | Negocio, LFPDPPP |
| admin publica el aviso de privacidad | Flujo de administración | Negocio |
| rechaza campos no declarados (asignación masiva) | Registrarse mandando `rol admin` | API3 |
| contraseña débil, menor de edad y aviso desactualizado | Contraseñas cortas o con datos personales, cuenta de menor, aviso viejo | API2 |
| registro correcto devuelve tokens y perfil sin hash | Fuga del hash de contraseña en la respuesta, registrar un correo que ya existe sin que la respuesta lo revele | API3, API2 |
| registro con teléfono e inicio de sesión con teléfono | Normalización del identificador | Negocio |
| la contraseña se guarda con scrypt y nunca en claro | Lectura directa de la tabla de usuarios | API2 |
| correo y teléfono a la vez o ninguno | Registro con dos datos de contacto sin verificar uno | API3 |
| mismo mensaje para usuario inexistente y contraseña incorrecta, bloqueo tras 5 fallos | Enumeración de cuentas y fuerza bruta | API2 |
| límite por IP del inicio de sesión | 21 intentos seguidos desde la misma IP, el último recibe 429 con `Retry-After` y las demás rutas siguen respondiendo | API4, API2 |
| límite por IP del registro | 11 registros seguidos desde la misma IP | API4, API6 |

## Sesiones con refresh rotativo

| Prueba | Qué simula | OWASP |
|---|---|---|
| rotación invalida el access anterior y el reuso revoca la familia | Robo y reuso de un refresh token | API2 |
| token manipulado o expirado | Token con un carácter cambiado y token vencido | API2 |
| logout revoca la sesión | Token usado después de cerrar sesión | API2 |
| en la base solo hay hashes de tokens | Lectura de la tabla de sesiones | API2 |

## Flujo completo de familia y administración

| Prueba | Qué simula | OWASP |
|---|---|---|
| la cuenta de administración no se inscribe y recibe un mensaje claro | Uso de una cuenta para algo que no le corresponde | API5 |
| una familia no puede usar rutas de administración | Elevación de privilegios | API5 |
| admin crea asociación y actividad publicada | Flujo de administración | Negocio |
| listados con filtros y búsqueda segura | Comodines `%` y `_` e inyección en la búsqueda | API8 |
| comunidad con protección contra IDOR | Editar, borrar o inscribir al acompañante de otra familia | API1 |
| inscripción respeta dueño de acompañantes y cupo | Inscribir personas ajenas o pasar el cupo | API1, API6 |
| testimonio exige asistencia registrada por admin y la otra familia no puede usar la inscripción | Contenido falso y uso de la inscripción de otra persona | API1, API6 |
| campaña, entrega registrada y confirmada por admin | Confirmar una donación propia sin la asociación | API6 |
| propuesta con historial, revisión y notificación | Leer la propuesta de otra persona | API1 |
| reportes validan el objetivo según el tipo | Reportes con objetivos inconsistentes | API3 |
| cancelar actividad avisa a las familias | Flujo de negocio | Negocio |

## Subida de imágenes

| Prueba | Qué simula | OWASP |
|---|---|---|
| PNG válido se guarda sin metadatos de texto y solo lo ve su dueño | Fuga de ubicación GPS y acceso a la foto de otra persona | API1, API3 |
| JPEG pierde el EXIF | Fuga de ubicación GPS | API3 |
| rechaza contenido disfrazado, tipo que no coincide y archivos grandes | Script disfrazado de imagen, tipo falso, archivo de más de 5 MB | API4, API8 |
| no se puede enlazar la imagen de otra persona | Usar la foto ajena en el perfil propio | API1 |

## Cuenta, suspensión, recuperación y eliminación

| Prueba | Qué simula | OWASP |
|---|---|---|
| cambiar correo exige contraseña actual | Secuestro de cuenta desde un teléfono desbloqueado, correo nuevo sin verificar, código equivocado | API2 |
| suspender una cuenta corta su sesión al instante | Cuenta suspendida que sigue usando su token | API2 |
| recuperación con código de un solo uso que revoca sesiones | Reuso del código y sesiones del atacante que sobreviven al cambio | API2 |
| eliminación de cuenta (derechos ARCO) anonimiza y borra fotos | Datos que quedan después de pedir la eliminación | LFPDPPP |

## Fase 1

| Prueba | Qué simula | OWASP |
|---|---|---|
| la cuenta es individual y ya no acepta tipoCuenta | Campo obsoleto enviado por un cliente viejo | API3 |
| la familia solo ve su ciudad aunque pida otra en la URL | Manipular el filtro para ver otra ciudad | API1 |
| solo asociaciones verificadas para las familias, el admin ve todas | Ver contenido sin verificar | API1 |
| filtro por tipo, visita es Visiteo y voluntariado es Participar | Flujo de negocio | Negocio |
| el último lugar es para una sola familia y la otra recibe un aviso claro | Condición de carrera con dos inscripciones simultáneas | API6 |
| si el grupo no cabe se dice cuántos lugares quedan | Sobrecupo | API6 |
| cupos en tiempo real por Server-Sent Events | Flujo sin sesión | API2 |
| máximo tres flujos abiertos por persona | Agotar conexiones del servidor | API4 |
| proyectos con sus campañas, el borrador no se ve | Ver contenido no publicado | API1 |
| entregas solo con artículo y punto de la misma campaña | Mezclar datos de dos campañas | API3 |
| aviso de privacidad, consulta, nueva versión y aceptación | Uso sin aceptar el aviso vigente | LFPDPPP |

## Fase 2

| Prueba | Qué simula | OWASP |
|---|---|---|
| publicar avisa a favoritos y sugiere a interesados, una vez al día y solo en su ciudad | Spam de notificaciones y fuga entre ciudades | API4, API1 |
| sin aceptar sugerencias no llegan | Notificaciones sin consentimiento | LFPDPPP |
| favoritos de actividades y lista de favoritos | Flujo de negocio | Negocio |
| recordatorio un día antes, una sola vez y respetando la preferencia | Avisos repetidos | API4 |
| encuesta posterior, valoración sin asistir rechazada (CU-02) y resultados para el admin | Valoraciones falsas | API6 |
| proponer una asociación que ya existe da un aviso claro (CP-01) | Duplicados | Negocio |
| historias de la comunidad, solo aprobadas y de la misma ciudad | Ver contenido sin moderar | API1 |
| push con Firebase, JWT firmado, token borrado si ya no existe y sin envíos dobles | Firma del JWT y respuestas de un tercero | API10 |
| cada notificación nueva avisa por el canal fqs_notificaciones | Flujo de negocio | Negocio |

## Segundo factor, bitácora y correo

| Prueba | Qué simula | OWASP |
|---|---|---|
| TOTP coincide con los vectores del RFC 6238 y del RFC 4226 | Implementación criptográfica incorrecta | API2 |
| un admin sin segundo factor no puede usar la administración, solo activarlo | Contraseña de administración robada, secreto en claro en la base | API2, API5 |
| con segundo factor la contraseña sola no da sesión, el código no se puede repetir | Reuso de código, desafío canjeado dos veces | API2 |
| código de respaldo de un solo uso y desafío que se agota | Reuso del código de respaldo, fuerza bruta del código | API2, API4 |
| cada acción de administración y cada acceso denegado queda en la bitácora sin datos del cuerpo | Repudio, intento de inyección en el filtro de la bitácora | API5, API8 |
| la bitácora no se puede editar ni borrar y una alteración se detecta | Borrar huellas con el rol de la API, con el dueño y con acceso total | API8 |
| reusar un refresh token queda en la bitácora | Detección de robo de sesión | API2 |
| correo de recuperación por Brevo con la llave en el encabezado y sin filtrar el código | Llamada correcta a un tercero y manejo de su error | API10 |
| la configuración exige la clave de cifrado y no acepta 2FA opcional en producción | Desplegar con una configuración insegura | API8 |

## Verificación de correo, contraseñas filtradas, sesiones, alertas, retención e imágenes

| Prueba | Qué simula | OWASP |
|---|---|---|
| con correo la cuenta no existe hasta verificar, el código se agota y se puede reenviar | Cuenta sin verificar, contraseña en claro en datos pendientes, fuerza bruta del código, código reusado | API2 |
| nadie puede apartar el correo de otra persona | Registrar o poner en otra cuenta el correo de la víctima | API2, API6 |
| el código de recuperación solo va a correos verificados | Recuperación hacia un correo que no se comprobó | API2 |
| contraseñas filtradas se rechazan sin mandar la contraseña ni el hash completo | Contraseñas de filtraciones, fuga de la contraseña a un tercero, servicio caído | API2, API10 |
| cada quien ve y cierra sus sesiones por dispositivo | Teléfono perdido, cerrar las sesiones de otra persona | API1, API2 |
| la sesión de administración es corta y tiene un tope absoluto | Sesión de administración robada que se renueva para siempre | API2 |
| rotación de la clave del segundo factor sin que nadie reactive su app | Clave filtrada, formato anterior, secreto copiado a otra cuenta | API2 |
| alertas por correo de la bitácora, sin repetirse | Ataques que nadie nota, alertas duplicadas | API8 |
| ancla externa de la bitácora y verificación contra el ancla | Reescritura completa de la bitácora | API8 |
| poda de la bitácora con corte, la cadena sigue verificable y el ancla anterior coincide | Retención que rompe la evidencia, borrado fuera de la poda, poda por el rol de la API | API8, LFPDPPP |
| cuentas inactivas reciben aviso, luego solicitud de eliminación, y entrar lo cancela | Datos conservados de más | LFPDPPP |
| las imágenes se reconstruyen sin datos escondidos ni bombas de descompresión | ZIP pegado a un PNG, fragmento privado, PHP en un comentario JPEG, IHDR gigante, datos que descomprimen 300 MB | API4, API8 |

## Verificación de teléfono por SMS

| Prueba | Qué simula | OWASP |
|---|---|---|
| registro solo con teléfono se verifica por SMS y el número queda en formato único | Cuenta con teléfono sin comprobar, el mismo número escrito de otra forma | API2 |
| solo números de México, un solo dato de contacto y sin SMS no hay registro por teléfono | SMS a números extranjeros, registrar dos contactos sin verificar uno | API6 |
| topes de SMS por número y por día contra el bombeo de SMS | Fraude de bombeo de SMS, guardar números en claro | API4, API6 |
| recuperación de contraseña por SMS a un teléfono verificado | Recuperación por teléfono | API2 |
| agregar un teléfono al perfil exige verificarlo por SMS | Apartar el teléfono de otra persona desde el perfil | API2 |
| SMS por Brevo con la llave en el encabezado y el número sin signo + | Llamada correcta al proveedor | API10 |


## Panel web de administración y correo a acompañantes

| Prueba | Qué simula | OWASP |
|---|---|---|
| el panel se sirve con CSP estricta y sin salir de su carpeta | Recorrido de rutas con `../` y codificaciones, método no permitido, CSP débil | API8 |
| el código del panel nunca arma HTML con texto ni ejecuta cadenas | XSS almacenado por usar `innerHTML` o `eval`, token guardado en `localStorage`, scripts en línea | API8 |
| una familia no puede abrir el panel y el inicio de sesión exige venir del panel | Cuenta de familia en el panel, inicio de sesión forzado desde otro sitio | API5, API2 |
| sesión del panel en cookies HttpOnly con segundo factor, CSRF, renovación y salida | CSRF sin encabezado, con otro origen y con origen `null`, reuso del token de renovación, cookie usada después de salir | API2, API5 |
| en producción las cookies llevan los prefijos __Host- y __Secure- | Cookie plantada desde un subdominio | API2 |
| el QR del segundo factor se dibuja en el servidor | Clave del segundo factor enviada a un servicio externo de QR, SVG con script | API2, API10 |
| listados del panel solo para administración y sin datos de acceso | Familia leyendo listados de administración, fuga de hashes, comodines en la búsqueda, filtros inválidos | API5, API3, API8 |
| acompañantes adultos con correo reciben la confirmación y el aviso de cancelación | Correo a menores, fuga del contacto de quien inscribe, uso de inscripciones para mandar correo masivo | API6, LFPDPPP |
| las fotos oficiales pueden ser de cualquier cuenta de administración, nunca de una familia | Usar la foto de una familia como foto oficial | API1 |

## Límites y rechazos de la rúbrica

| Prueba | Qué simula | OWASP |
|---|---|---|
| límite de escrituras por cuenta | 31 reportes seguidos de la misma cuenta, el último recibe 429 y otra cuenta de la misma IP no se ve afectada | API4, API6 |
| límite de recuperación por IP | 6 solicitudes de código desde la misma IP | API4, API2 |
| inyección SQL en el inicio de sesión | `' OR '1'='1`, comentarios, consultas apiladas y UNION en usuario y contraseña | API8 |
| inyección SQL en búsquedas y filtros | Las mismas cargas en la búsqueda, en un filtro de valores fijos y en un UUID de consulta | API8 |
| inyección SQL en la ruta | Cargas en los parámetros de ruta | API8 |
| la base sigue intacta después de los intentos | Que alguna carga haya borrado datos | API8 |
| tipos equivocados no se convierten | Texto donde va un booleano, campos de más con inyección | API3, API8 |
| token inventado, manipulado o con inyección | Tokens falsos, recortados, alargados o con SQL | API2 |
| token expirado | Token vencido | API2 |
| refresh reutilizado cierra toda la sesión | Robo y reuso de un refresh token | API2 |
| no se puede ver ni cambiar datos de otra familia | IDOR sobre acompañantes, propuestas y sesiones de otra cuenta | API1 |
| campos privilegiados no se pueden mandar | Asignación masiva de `rol`, `estado` o `id` | API3 |
| una familia no usa la administración | Elevación de privilegios a rutas de administración | API5 |
| bloqueo por exceso en el inicio de sesión | Fuerza bruta desde una IP | API4, API2 |
| bloqueo de la cuenta aunque cambie la IP | Fuerza bruta distribuida contra una cuenta | API2 |
| bloqueo por exceso en el registro | Creación masiva de cuentas | API4, API6 |
| no hay límite global | 120 lecturas seguidas sin bloqueo, los límites solo están en rutas sensibles | API4 |
| carácter nulo en cuerpo y consulta | Textos con el carácter nulo en el cuerpo JSON y en la búsqueda (hallazgo del escaneo con ZAP, corregido) | API8 |
| diagonal final no redirige | Ruta con diagonal al final, responde 404 sin redirección | API8 |

## Métricas para Prometheus

| Prueba | Qué simula | OWASP |
|---|---|---|
| el puerto de la API no publica métricas | Pedir `/metrics` y variantes en el puerto público de la API | API8, API9 |
| el servidor de métricas solo responde GET /metrics | Otras rutas y otros métodos en el puerto de métricas | API8 |
| peticiones por plantilla de ruta sin ids | Direcciones con UUID y rutas inventadas, que no deben crear series nuevas ni dejar el id en las métricas | API4, API3 |
| métricas sin datos personales | Que aparezca un correo, un token, un UUID o una IP en la salida | API3 |
| inicios de sesión por resultado | Contraseña equivocada y correcta, contadas por resultado | API2 |
| eventos de seguridad por acción | Contraseña equivocada en la cuenta de administración, contada igual que en la bitácora | API2 |
| respuestas 429 por ruta | Fuerza bruta en el inicio de sesión hasta recibir 429, contada en su ruta | API4 |
| conexiones en tiempo real y proceso | Conexiones abiertas de cupos, memoria del proceso y versión | Negocio |
| el puerto de métricas no puede ser el de la API | Configuración que publicaría las métricas en el puerto público | API8 |
| series de las alertas existen desde el arranque | Que la primera ocurrencia de un evento se pierda para las alertas | Negocio |

## Reintentos con Idempotency-Key

| Prueba | Qué simula | OWASP |
|---|---|---|
| misma clave devuelve la misma respuesta sin duplicar | La app reenvía un reporte porque perdió la respuesta, se crea uno solo | API6 |
| sin clave cada petición crea un registro | Que la clave cambie el comportamiento normal de la ruta | Negocio |
| misma clave con otro cuerpo u otra ruta se rechaza | Reusar una clave para colar otra petición o leer la respuesta de otra ruta | API6, API3 |
| la clave es de cada cuenta | Otra cuenta que adivina o copia una clave no recibe la respuesta ajena | API1 |
| clave con formato inválido | Claves cortas, largas, con espacios o con SQL | API8 |
| una propuesta reintentada no choca con la regla de duplicados | Reintento de una propuesta, que sin la clave respondería 409 | Negocio |
| si la petición falla la clave se libera | Envío rechazado (foto ajena) que después se corrige con la misma clave | API6 |
| petición en proceso y clave vencida | Dos envíos simultáneos con la misma clave y una clave de más de 48 horas | API6 |
| la limpieza borra las claves vencidas | Que la tabla crezca sin límite | API4 |
