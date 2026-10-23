# Cumplimiento de la rúbrica de la tercera entrega

Cada punto de la rúbrica con la evidencia que lo demuestra y su estado. Lo que depende de grabar o instalar en un teléfono físico queda como pendiente del equipo.

## Parte 1. Sistema completo funcionando

| Elemento | Qué se espera | Evidencia | Estado |
|---|---|---|---|
| App Android | Build de release firmado, instalado en un dispositivo físico | Procedimiento de firma en [manual-instalacion.md](manual-instalacion.md) | Pendiente del equipo (firmar e instalar) |
| Backend propio | Funcionando y reproducible por una persona externa | [manual-instalacion.md](manual-instalacion.md) con Docker y sin Docker, `requirements.txt` con versiones exactas, scripts de base en `db/` | Cumplido |
| Integración completa | La app consume los servicios reales y completa los flujos | Pruebas de integración por HTTP con las mismas rutas y JSON que usa la app, recorrido del panel en el navegador | Cumplido, falta grabarlo en el teléfono |
| Persistencia | Los datos se conservan | PostgreSQL 16 con volumen, respaldos cifrados probados | Cumplido |
| Capacidades del dispositivo | Cámara, multimedia u otras | Cámara y galería para fotos de experiencias y perfil, notificaciones push, llamada, WhatsApp, correo y mapas con intents | Cumplido en código, falta grabarlo |
| Operación sin conexión | Solo si forma parte de los requerimientos | Room guarda cifradas las últimas consultas y la app las muestra sin red con un aviso de su hora, ver DT-11 y [arquitectura.md](arquitectura.md) | Cumplido en código, falta grabarlo en modo avión |
| Sincronización posterior | Solo si hay operación sin conexión | WorkManager manda la cola al volver la red y la API evita duplicados con `Idempotency-Key` | `tests/test_10_idempotencia.py`, falta grabarlo en el teléfono |
| Datos realistas | Información representativa del socio | `python -m fqs.scripts.datos_prueba` con asociaciones, actividades, campañas y proyectos en lugares reales de Monterrey | Cumplido |

## Parte 2.1. Controles en la API

| Lo que pide | Cómo se cumple | Evidencia | Estado |
|---|---|---|---|
| Sesiones e identidad robustas | Tokens opacos de 256 bits con rotación del refresh y revocación de toda la familia al reusar uno, sesión corta para administración, segundo factor obligatorio para administración | `test_01_base::test_rotacion_invalida_el_access_anterior_y_el_reuso_revoca_la_familia`, `test_05_seguridad` | Cumplido |
| Contraseñas, tokens y llaves sin texto plano | scrypt para contraseñas, SHA-256 para tokens y códigos, AES-256-GCM para secretos del segundo factor, llaves en variables de entorno, tokens cifrados con el Keystore en la app | `test_la_contrasena_se_guarda_con_scrypt`, `test_en_la_base_solo_hay_hashes_de_tokens`, `test_un_admin_sin_segundo_factor_solo_puede_activarlo` | Cumplido |
| Nada se transmite de forma insegura | HTTPS obligatorio en la app release, HSTS, cookies Secure en el panel, Pwned Passwords con k-anonimato | `test_contrasenas_filtradas_sin_mandar_la_contrasena_ni_el_hash_completo`, [../seguridad/evidencia/https-caddy.txt](../seguridad/evidencia/https-caddy.txt) | Cumplido |
| Cada rol solo ve lo suyo (IDOR) | Toda consulta filtra por el usuario de la sesión, lo ajeno responde 404 | `test_08_rechazos::test_no_se_puede_ver_ni_cambiar_datos_de_otra_familia`, `test_02_flujo::test_comunidad_con_proteccion_contra_idor` | Cumplido |
| Validaciones y privilegios antes de modificar o eliminar información crítica | Ver la tabla de operaciones críticas abajo | Pruebas indicadas en esa tabla | Cumplido |
| Consultas parametrizadas y validación estricta | psycopg con parámetros en todas las consultas, modelos estrictos de Pydantic, parámetros de ruta solo UUID, carácter nulo rechazado | `test_08_rechazos::test_inyeccion_sql_*`, sqlmap sin parámetros inyectables | Cumplido |
| Límites de tasa en endpoints críticos | slowapi en cada ruta sensible, sin límite global, bloqueo por cuenta | `test_08_rechazos::test_bloqueo_*`, `test_no_hay_limite_global` | Cumplido |
| Controles de concurrencia | El último lugar se asigna con bloqueo de fila en la base, máximo 3 flujos en vivo por persona, uvicorn con tope de conexiones | `test_03_fase1::test_el_ultimo_lugar_es_para_una_sola_familia`, `test_maximo_tres_flujos_abiertos_por_persona` | Cumplido |
| Bloqueos temporales | 5 contraseñas o códigos equivocados bloquean la cuenta 15 minutos | `test_08_rechazos::test_bloqueo_de_la_cuenta_aunque_cambie_la_ip` | Cumplido |
| Tráfico cifrado | Caddy con TLS 1.2 y 1.3 y redirección de HTTP, túnel con HTTPS de Cloudflare | [../seguridad/evidencia/https-caddy.txt](../seguridad/evidencia/https-caddy.txt) | Cumplido |
| `Strict-Transport-Security` | En producción, un año con subdominios | Misma evidencia | Cumplido |
| `X-Content-Type-Options` | `nosniff` en todas las respuestas | `test_01_base::test_encabezados_de_seguridad` | Cumplido |
| `Content-Security-Policy` | `default-src 'none'` en la API y política estricta sin scripts en línea en el panel | `test_encabezados_de_seguridad`, `test_07_sms_panel::test_el_panel_se_sirve_con_csp_estricta_y_sin_salir_de_su_carpeta` | Cumplido |

### Operaciones críticas y sus controles

| Operación | Controles antes de ejecutarla | Prueba |
|---|---|---|
| Cambiar contraseña | Contraseña actual, reglas de fuerza, no filtrada, cierra las demás sesiones | `test_06_cuenta::test_contrasenas_filtradas_sin_mandar_la_contrasena_ni_el_hash_completo` |
| Cambiar correo o teléfono | Contraseña actual, código al dato nuevo, aviso al correo anterior, no se puede apartar el dato de otra cuenta | `test_02_flujo::test_cambiar_correo_exige_contrasena_actual`, `test_06_cuenta::test_nadie_puede_apartar_el_correo_de_otra_persona` |
| Eliminar la cuenta | Contraseña actual, desactiva y cierra sesiones de inmediato | `test_02_flujo::test_eliminacion_de_cuenta_anonimiza_y_borra_fotos` |
| Restablecer contraseña | Código de un solo uso que vence en 30 minutos, 5 intentos por cuenta, cierra todas las sesiones | `test_02_flujo::test_recuperacion_con_codigo_de_un_solo_uso_que_revoca_sesiones` |
| Borrar un acompañante | Solo el dueño, y no si está inscrito en una actividad próxima (si tiene historial se desactiva en lugar de borrarse) | `test_02_flujo::test_comunidad_con_proteccion_contra_idor` |
| Cancelar una entrega o una inscripción | Solo el dueño y solo en estados que lo permiten | Reglas en la base y en la ruta |
| Activar el segundo factor | Contraseña otra vez y primer código correcto, cierra las demás sesiones | `test_05_seguridad::test_un_admin_sin_segundo_factor_solo_puede_activarlo` |
| Regenerar códigos de respaldo | Sesión iniciada con segundo factor y un código válido | `test_05_seguridad::test_codigo_de_respaldo_de_un_solo_uso_y_desafio_que_se_agota` |
| Cualquier acción de administración | Rol de administración, sesión con segundo factor, queda en la bitácora encadenada | `test_05_seguridad::test_cada_accion_de_administracion_queda_en_la_bitacora_sin_el_cuerpo` |
| Suspender una cuenta | Lo anterior, no se puede suspender la cuenta propia, cierra sus sesiones y flujos en vivo | `test_02_flujo::test_suspender_una_cuenta_corta_su_sesion_al_instante` |
| Resolver una eliminación (anonimizar) | Lo anterior, la función de la base solo acepta solicitudes abiertas y trabaja en una transacción | `test_02_flujo::test_eliminacion_de_cuenta_anonimiza_y_borra_fotos` |
| Cancelar una actividad | Lo anterior, motivo obligatorio, avisa a las familias y acompañantes | `test_02_flujo::test_cancelar_actividad_avisa_a_las_familias` |
| Borrar o editar la bitácora | Imposible, el rol de la API no tiene permiso y un trigger lo impide incluso al dueño | `test_05_seguridad::test_la_bitacora_no_se_puede_editar_ni_borrar_y_una_alteracion_se_detecta` |

## Parte 2.2. Infraestructura y despliegue seguro

| Lo que pide | Cómo se cumple | Evidencia | Estado |
|---|---|---|---|
| API y servicios en contenedores | Docker Compose con PostgreSQL, API, Caddy, Prometheus, Grafana, túnel opcional y respaldos | `Dockerfile`, `docker-compose.yml` validado con `docker compose config` | Cumplido, falta que el equipo lo levante en su computadora |
| Buenas prácticas de aislamiento | API sin root, sistema de archivos de solo lectura, sin capacidades, base en red interna sin salida a internet, sin puertos publicados salvo Caddy | [../seguridad/despliegue.md](../seguridad/despliegue.md) | Cumplido |
| Secretos en variables de entorno | Contraseñas y claves en `.env.docker`, archivo de Firebase como secreto de Docker, nada en la imagen | `docker-compose.yml`, `.dockerignore`, gitleaks sin hallazgos | Cumplido |
| Monitoreo con Prometheus y Grafana | Métricas de la API en un puerto aparte que solo escucha en la red de monitoreo, Prometheus sin puertos publicados con 9 reglas de alerta, Grafana solo en 127.0.0.1 con contraseña del entorno y un tablero de tráfico y seguridad | [../seguridad/monitoreo.md](../seguridad/monitoreo.md), [../seguridad/evidencia/monitoreo.txt](../seguridad/evidencia/monitoreo.txt), `tests/test_09_metricas.py` | Cumplido, falta capturar el tablero de Grafana en la computadora del equipo |
| Servidor en la nube | Máquina virtual de Azure en Chile Central con Trusted Launch, solo SSH abierto y entrada por el túnel, consumida por el APK release firmado | [../seguridad/despliegue-azure.md](../seguridad/despliegue-azure.md), `despliegue/azure/`, [arquitectura-despliegue.png](arquitectura-despliegue.png) | Cumplido, máquina creada y en uso |
| Exposición por túnel consumida desde la app | Perfil `tunel` con cloudflared, la app release apunta al nombre público con HTTPS | [../seguridad/despliegue.md](../seguridad/despliegue.md), sección del túnel | Configurado, falta la demostración |

## Parte 2.3. Validación de seguridad

| Lo que pide | Evidencia | Estado |
|---|---|---|
| Rechazo de inyección SQL | `test_08_rechazos::test_inyeccion_sql_en_el_inicio_de_sesion`, `test_inyeccion_sql_en_busquedas_y_filtros`, `test_inyeccion_sql_en_la_ruta`, sqlmap | Cumplido |
| Rechazo de tokens expirados o manipulados | `test_08_rechazos::test_token_inventado_manipulado_o_con_inyeccion`, `test_token_expirado`, `test_refresh_reutilizado_cierra_toda_la_sesion` | Cumplido |
| Rechazo de consulta de datos de otro usuario | `test_08_rechazos::test_no_se_puede_ver_ni_cambiar_datos_de_otra_familia` | Cumplido |
| Bloqueo por exceso de peticiones | `test_08_rechazos::test_bloqueo_por_exceso_en_el_inicio_de_sesion`, `test_bloqueo_por_exceso_en_el_registro`, `test_bloqueo_de_la_cuenta_aunque_cambie_la_ip` | Cumplido |
| Escaneo DAST con OWASP ZAP, reporte y justificación | [../seguridad/escaneos.md](../seguridad/escaneos.md), [../seguridad/evidencia/zap-reporte.html](../seguridad/evidencia/zap-reporte.html) | Cumplido |

## Partes 3 a 6

| Parte | Evidencia | Estado |
|---|---|---|
| 3. Matriz de trazabilidad con id, descripción, criterio, prueba, resultado y estado | [matriz-trazabilidad.md](matriz-trazabilidad.md) | Cumplido, faltan las filas de RF-03, RF-04, RF-06, RF-08, RF-10 y RF-14 que solo están en el Planner |
| 3. Niveles de prueba | [matriz-trazabilidad.md](matriz-trazabilidad.md), sección Niveles de prueba | Cumplido en unitario, integración y seguridad, pendiente sistema y aceptación en el teléfono |
| 4. Manual de usuario | [manual-usuario.md](manual-usuario.md) | Cumplido |
| 4. Manual de instalación | [manual-instalacion.md](manual-instalacion.md) | Cumplido |
| 4. Arquitectura | [arquitectura.md](arquitectura.md) | Cumplido |
| 4. Decisiones técnicas | [decisiones-tecnicas.md](decisiones-tecnicas.md) | Cumplido |
| 4. Plan de implantación con canal, versión, configuración, despliegue, carga de datos y rollback | [plan-implantacion.md](plan-implantacion.md) | Cumplido, confirmar con el socio que no hay datos previos |
| 5. Administración final | [administracion-proyecto.md](administracion-proyecto.md) | Faltan fechas de hitos y distribución del trabajo, que solo tiene el equipo |
| 6. Presentación de 15 minutos | [README.md](README.md), guion por bloques de tiempo | Cumplido |
