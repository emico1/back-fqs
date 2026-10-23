# Escaneos con herramientas de seguridad

Los escaneos se corrieron el 20 de octubre de 2026 contra la versión final de la API (con `Idempotency-Key` en las escrituras que la app manda después de estar sin conexión y con el servidor de métricas encendido en su propio puerto), en modo producción (`ENTORNO=production`), detrás de Caddy 2.10.2 con HTTPS, conectada a PostgreSQL 16 con el rol de mínimo privilegio y con los datos de `python -m fqs.scripts.datos_prueba`. Se usaron dos sesiones reales, una de familia y una de administración con segundo factor activo.

## OWASP ZAP, escaneo activo de la API

[OWASP ZAP](https://www.zaproxy.org) 2.16.1 importó la descripción [docs/openapi.json](../openapi.json) que FastAPI genera desde las rutas (`python -m fqs.scripts.openapi`, las 126 operaciones con sus modelos), y corrió el escaneo pasivo y el activo completos con la sesión de administración, que también puede usar todas las rutas de familia. El plan de automatización está en [evidencia/zap-plan.yaml](evidencia/zap-plan.yaml). El escaneo activo terminó todas sus reglas en 9 minutos 34 segundos, sin tope de tiempo y sin retraso entre peticiones (la API no tiene límite global, los límites están en las rutas sensibles).

| Riesgo | Alertas |
|---|---|
| Alto | 0 |
| Medio | 0 |
| Bajo | 0 |
| Informativo | 3 |

| Alerta informativa | Qué dice | Justificación |
|---|---|---|
| Re-examine Cache-control Directives (10015) | Sugiere revisar el encabezado `Cache-Control` | La API manda `Cache-Control no-store`, la directiva que impide guardar la respuesta en cualquier caché. ZAP la marca para que alguien confirme que es intencional, y lo es porque las respuestas llevan datos personales y tokens |
| User Agent Fuzzer (10104) | Registra que la API responde igual con distintos `User-Agent` | Es solo un registro. La API no cambia su comportamiento según el navegador |
| Authentication Request Identified (10111) | Detectó que `POST /v1/auth/login` recibe credenciales | Es la ruta de inicio de sesión, tiene límite por IP, bloqueo por cuenta y el mismo mensaje para cuenta inexistente y contraseña equivocada |

### Hallazgo corregido durante el escaneo

En una primera corrida la API respondió 500 dos veces. El registro del servidor mostró la causa, un texto con el carácter nulo (`\u0000`) en el cuerpo de `POST /v1/admin/ciudades` y de `DELETE /v1/yo/dispositivos`. PostgreSQL no acepta ese carácter y el error llegaba sin traducir. No filtraba información (la respuesta era el 500 genérico), pero es un error no controlado.

Se corrigió en tres capas. Los modelos de entrada rechazan el carácter nulo en cualquier campo con un 400 que dice qué campo está mal, el middleware rechaza `%00` en la ruta y en la búsqueda, y si algún día llegara a la base se traduce a 400. Se agregó la prueba `test_08_rechazos::test_caracter_nulo_en_cuerpo_y_consulta`. En esa corrida también se vio que FastAPI redirigía con 307 las rutas con diagonal al final, se desactivó para que respondan 404 (`test_diagonal_final_no_redirige`).

### Respuestas de la API durante el escaneo final

| Estado | Peticiones | Qué significa |
|---|---|---|
| 400 | 37,862 | La validación rechazó la carga antes de llegar a la base (incluye las claves de `Idempotency-Key` con formato inválido) |
| 404 | 17,215 | Parámetros de ruta que no son UUID o recursos que no existen |
| 403 | 1,497 | Rutas de administración o CSRF del panel |
| 429 | 1,276 | Límites por ruta (inicio de sesión, recuperación, escrituras, subidas) |
| 200, 202, 204 | 1,772 | Peticiones válidas |
| 415, 422, 409, 405, 401 | 1,272 | Tipo de contenido, reglas de negocio, misma clave de idempotencia con otro cuerpo, método y sesión |
| 500 | 0 | Ningún error no controlado |

En total 60,894 peticiones. Durante el escaneo `https://api.fqs.localhost/metrics` respondió 404 a través de Caddy, las métricas solo salen en su propio puerto. Los reportes completos están en [evidencia/zap-reporte.html](evidencia/zap-reporte.html) y [evidencia/zap-reporte.json](evidencia/zap-reporte.json).

Para repetirlo con Docker

```bash
python -m fqs.scripts.openapi https://api.tu-dominio.mx
docker run --rm -v "$PWD/docs:/zap/wrk" ghcr.io/zaproxy/zaproxy:stable zap-api-scan.py \
  -t /zap/wrk/openapi.json -f openapi -r reporte.html \
  -z "-config replacer.full_list(0).description=sesion -config replacer.full_list(0).enabled=true -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Authorization -config replacer.full_list(0).replacement='Bearer fqs_at_...'"
```

## sqlmap, inyección SQL

[sqlmap](https://sqlmap.org) prueba de forma automática decenas de técnicas de inyección (booleana a ciegas, por errores, por tiempo, consultas apiladas y UNION) sobre cada parámetro.

| Objetivo | Parámetros | Resultado |
|---|---|---|
| `GET /v1/actividades` | `q`, `categoria`, `tipo`, `orden`, `limite` | Ninguno inyectable |
| `GET /v1/asociaciones` | `q` | Ninguno inyectable |
| `PUT /v1/yo/comunidad/{id}` con cuerpo JSON | `nombre`, `relacion`, `fechaNacimiento`, `User-Agent`, `Referer` | Ninguno inyectable |
| `GET /v1/admin/bitacora` | `accion`, `limite` | Ninguno inyectable, sqlmap además detectó la validación como si fuera un WAF |
| `POST /v1/auth/login` con cuerpo JSON | `identificador`, `password` | sqlmap se detuvo, el límite de la ruta respondió 429 desde el primer intento |
| `POST /v1/reportes` con cuerpo JSON y `Idempotency-Key` | `tipo`, `descripcion` | `tipo` no inyectable. En `descripcion` sqlmap tuvo que frenar porque el límite de escrituras respondió 429 y la misma clave de idempotencia con otro cuerpo respondió 422, y se detuvo cuando venció la sesión (401). Ninguna respuesta fue 500 |

Opciones usadas `--level=3 --risk=1 --dbms=PostgreSQL`, sin retraso. En las rutas de consulta la validación rechazó con 400 la mayoría de las cargas (1,573, 105, 637 y 733 veces), y ninguna respuesta fue 500. En el inicio de sesión sqlmap no pudo avanzar porque el límite de 20 intentos por IP cada 15 minutos ya estaba agotado, que es justo el control que se quería demostrar. La inyección en el inicio de sesión se prueba directamente con `test_08_rechazos::test_inyeccion_sql_en_el_inicio_de_sesion`. El encabezado `Idempotency-Key` solo acepta de 16 a 64 letras, números, guiones o guiones bajos, así que una carga con comillas o espacios se rechaza con 400 antes de llegar a la ruta, lo prueba `test_10_idempotencia::test_clave_con_formato_invalido` con una carga de SQL. Salida en [evidencia/sqlmap.txt](evidencia/sqlmap.txt).

Para repetirlo

```bash
git clone --depth 1 https://github.com/sqlmapproject/sqlmap.git
python3 sqlmap/sqlmap.py --batch --level=3 --risk=1 --dbms=PostgreSQL \
  -u "https://api.tu-dominio.mx/v1/actividades?q=arbol&categoria=MEDIO_AMBIENTE&orden=fecha" \
  -p "q,categoria,orden" -H "Authorization: Bearer fqs_at_..."
```

Solo contra un servidor propio o con permiso por escrito.

## MobSF, análisis del APK

[Mobile Security Framework](https://github.com/MobSF/Mobile-Security-Framework-MobSF) revisa el APK sin ejecutarlo (manifiesto, permisos, código descompilado, configuración de red, secretos en el código) y le da una calificación. Necesita el APK compilado, por eso se corre en la computadora donde se compila la app.

```bash
# En la carpeta de la app
./gradlew assembleRelease
# MobSF con Docker
docker run -it --rm -p 8000:8000 opensecurity/mobile-security-framework-mobsf:latest
```

Abre `http://localhost:8000`, sube `app/build/outputs/apk/release/app-release-unsigned.apk` (o el firmado) y descarga el reporte en PDF.

Lo que el reporte debería mostrar, y por qué, según la configuración actual de la app.

| Revisión de MobSF | Esperado | Dónde está |
|---|---|---|
| `android:allowBackup` | false | AndroidManifest.xml |
| Tráfico en texto claro | No permitido | `usesCleartextTraffic false` y network_security_config.xml |
| Confianza en certificados del usuario | No, solo del sistema | network_security_config.xml |
| Componentes exportados | Solo la actividad principal, el servicio de push no se exporta | AndroidManifest.xml |
| Permisos peligrosos | Ninguno, solo INTERNET y POST_NOTIFICATIONS, sin cámara ni ubicación | AndroidManifest.xml |
| Llaves o contraseñas en el código | Ninguna. `google-services.json` trae identificadores públicos del proyecto, que Firebase documenta como no secretos | app/ |
| Almacenamiento de la sesión | Cifrado con AES-GCM y Android Keystore | AlmacenSesion.kt |
| Base de datos local (Room) | Las copias para usar sin conexión y los envíos pendientes van cifrados con otra llave del Keystore, sin respaldo en la nube | data/local |
| Ofuscación | R8 activo en release | build.gradle.kts |
| minSdk | 26, Android 8 | build.gradle.kts |

MobSF suele marcar como advertencia la clave de API de Firebase dentro de `google-services.json`. Esa clave identifica el proyecto y está pensada para ir en la app. Lo que la protege son las reglas del proyecto en Firebase y que la app no usa Firestore ni Realtime Database, solo mensajería.

## Cómo repetir todo en otra computadora

1. Levanta la API con Docker Compose (ver [despliegue.md](despliegue.md)) o con `python -m fqs`.
2. Corre `python -m fqs.scripts.datos_prueba` y crea una familia desde la app.
3. Activa el segundo factor de la cuenta de administración y saca su token.
4. Corre `python -m fqs.scripts.openapi https://tu-servidor` para tener la lista de rutas.
5. Corre sqlmap, ZAP y MobSF como se describe arriba.
