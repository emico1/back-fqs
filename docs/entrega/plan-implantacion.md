# Plan de implantación con Familias que Suman

Describe cómo poner el sistema en operación con el socio formador, qué se entrega, qué tiene que configurar la organización y cómo regresar a la versión anterior si algo falla.

## Versión entregada

| Componente | Versión | Identificador |
|---|---|---|
| API | 2.0.0 (FastAPI) | `fqs/__init__.py` |
| Esquema de base de datos | migraciones 01 a 10 | carpeta `db/` |
| App Android | 0.3.1, versionCode 4 | `app/build.gradle.kts`, paquete `mx.familiasquesuman.app` |
| Panel web | el que trae la API 2.0.0 | carpeta `panel/` |

## Canal de distribución

**App.** Para la etapa piloto el APK release firmado se instala directamente en los teléfonos de las familias participantes (archivo compartido por la organización o por cable). La siguiente etapa es publicarla en Google Play en una prueba cerrada (Closed testing), que permite actualizar a todos los teléfonos sin reinstalar y exige el mismo keystore de firma. La cuenta de desarrollador de Google Play debe estar a nombre de la organización, no de un integrante del equipo.

**Panel.** No se distribuye, el equipo lo abre en el navegador en la dirección del servidor seguida de `/panel/`.

**API.** Corre en un servidor con Docker, del que la organización es dueña o que contrata. Para el piloto corre en una máquina virtual de Azure en Chile Central (2 vCPU y 4 GiB) con entrada solo por el túnel de Cloudflare, la única región con máquinas económicas que permite la suscripción de estudiante. Con la suscripción de la organización conviene recrearla en Mexico Central para que los datos queden en México, ver [../seguridad/despliegue-azure.md](../seguridad/despliegue-azure.md). La suscripción de Azure debe quedar a nombre de la organización al terminar el piloto.

## Configuración necesaria

| Qué | Quién lo hace | Dónde |
|---|---|---|
| Dominio para la API (por ejemplo `api.familiasquesuman.mx`) apuntando al servidor | Organización | DNS del dominio |
| Contraseñas de la base y claves de cifrado | Responsable técnico | `.env.docker`, con copia de las claves fuera del servidor |
| Cuenta de Brevo con el remitente verificado y SPF y DKIM del dominio | Organización | Brevo y DNS |
| Créditos de SMS (solo si se quiere registro por teléfono) | Organización | Brevo |
| Proyecto de Firebase y su cuenta de servicio | Organización | Consola de Firebase, archivo en `docker/secretos/` |
| Contraseña de Grafana y acceso por SSH para ver el tablero | Responsable técnico | `.env.docker` (`GRAFANA_ADMIN_PASSWORD`) |
| Correo para alertas de seguridad de alguien que no administre el servidor | Dirección de la organización | `ALERTAS_CORREO` |
| Cuentas de administración con segundo factor, una por persona | Cada integrante del equipo | Script `crear_admin` y panel |
| Aviso de privacidad aprobado por la organización | Organización | Panel, Ajustes |
| Keystore de firma de la app | Responsable técnico | Fuera del repositorio, con respaldo |

## Procedimiento de despliegue

1. Preparar el servidor. En Azure con `bash despliegue/azure/crear-vm.sh`, que deja solo SSH abierto y la entrada por el túnel. En otro servidor, instalar Docker, abrir solo 80 y 443 y apuntar el dominio.
2. Copiar el proyecto, llenar `.env.docker` y colocar el archivo de Firebase (ver [manual-instalacion.md](manual-instalacion.md)).
3. Levantar con `docker compose --env-file .env.docker up -d --build`. La primera vez se crea el esquema y el usuario de mínimo privilegio.
4. Comprobar `https://api.familiasquesuman.mx/v1/salud` y los encabezados con `curl -I`, y que en Grafana el panel API arriba marque Arriba.
5. Crear las cuentas de administración y activar el segundo factor de cada una.
6. Publicar el aviso de privacidad y cargar ciudades, categorías, asociaciones y las primeras actividades (ver carga inicial).
7. Programar en el crontab el respaldo diario y la poda mensual de la bitácora.
8. Compilar la app con `fqs.api.release` apuntando al dominio, firmarla y distribuirla.
9. Hacer una prueba de humo completa con una familia de prueba (registro, inscripción, cancelación, entrega, notificación) antes de invitar a las familias reales.
10. Correr un respaldo y verificarlo con `restaurar --solo-verificar`.

## Datos existentes y carga inicial

El socio formador no entregó una base de datos previa para migrar. Su información actual (asociaciones aliadas, actividades y campañas) está en su página web y en documentos internos, no en un sistema con datos estructurados de familias. Por eso no hay migración de datos de familias. Cada familia crea su cuenta desde la app y acepta el aviso de privacidad, lo que además cumple con el consentimiento que pide la LFPDPPP.

La carga inicial se hace así.

1. Catálogos. Ciudades y categorías vienen en `db/02_catalogos.sql`. Si la organización opera en otra ciudad se agrega desde el panel.
2. Asociaciones. El equipo de la organización las captura en el panel con sus datos de contacto, foto y la marca de verificada.
3. Actividades, campañas y proyectos. Se capturan en el panel y se publican cuando están listos.
4. Para la demostración se usa `python -m fqs.scripts.datos_prueba`, que crea asociaciones ficticias con teléfonos y correos de rangos reservados. Esos datos no se cargan en producción.

Si en el futuro la organización entrega un archivo con asociaciones, se puede cargar con un script que lea el archivo y use las mismas inserciones del panel, así se aplican las mismas validaciones.

## Procedimiento de rollback

Antes de cada actualización se hace un respaldo cifrado y se anota la versión que está corriendo.

```bash
docker compose --env-file .env.docker --profile respaldo run --rm respaldo
git rev-parse HEAD > version-anterior.txt
```

Si la nueva versión falla en la prueba de humo, se regresa así.

1. Volver al código anterior con `git checkout $(cat version-anterior.txt)` y reconstruir con `docker compose --env-file .env.docker up -d --build api`.
2. Si la actualización incluía una migración de base que no es compatible hacia atrás, restaurar el respaldo con `python -m fqs.scripts.restaurar respaldos/respaldo-AAAAMMDD-HHMMSS.json` (pide escribir el nombre de la base para confirmar y trabaja en una sola transacción).
3. Comprobar `/v1/salud`, revisar en Grafana que no haya errores 5xx ni alertas activas y repetir la prueba de humo.
4. Si la falla está en la app, se vuelve a instalar el APK anterior firmado con el mismo keystore (en Google Play, se detiene el lanzamiento y se publica de nuevo la versión anterior con un versionCode mayor).

## Operación después de la implantación

| Tarea | Frecuencia | Cómo |
|---|---|---|
| Respaldo cifrado | Diario | crontab con el perfil `respaldo` |
| Verificar que un respaldo se puede abrir | Semanal | `restaurar --solo-verificar` |
| Revisar alertas de seguridad | Al recibirlas | Correo y panel, Seguridad |
| Revisar el tablero y las alertas de Grafana | Diario en el piloto, semanal después | Túnel SSH a Grafana |
| Revisar que la bitácora no se alteró | Mensual | Panel, Seguridad, Verificar |
| Actualizar dependencias | Cuando Dependabot abre un pull request | Correr las pruebas y desplegar |
| Poda de la bitácora | Mensual | crontab con `podar_bitacora` |
