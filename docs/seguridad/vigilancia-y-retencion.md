# Alertas, ancla de la bitácora y retención de datos

## Alertas por correo

Cada minuto la API lee los eventos nuevos de la bitácora de seguridad y manda avisos por correo. Guarda hasta qué evento leyó, así un reinicio no repite ni pierde avisos. La misma alerta (misma regla y misma cuenta) no se repite dentro de una hora. Todas las alertas enviadas quedan en la tabla `alertas_seguridad` y se consultan con `GET /v1/admin/alertas`.

Los destinatarios son las cuentas de administración activas y los correos de `ALERTAS_CORREO`. Conviene que ahí haya al menos un correo de alguien que no administre el servidor, así una persona con acceso al servidor no puede silenciar las alertas sin que alguien más se entere.

### Avisos inmediatos

| Evento | A quién | Por qué |
|---|---|---|
| `login_admin`, `2fa_correcto` | A la propia cuenta de administración | Si no fue ella, alguien tiene su contraseña y su código |
| `2fa_codigo_respaldo_usado` | A la cuenta y a todo el equipo | Normalmente significa que se perdió un teléfono |
| `2fa_activado`, `2fa_codigos_regenerados` | A la propia cuenta | Cambios en su seguridad |
| `2fa_reiniciado` | A la cuenta y a todo el equipo | Alguien con acceso al servidor quitó un segundo factor |
| `refresh_reutilizado` | A la familia afectada | Se detectó una sesión copiada y se cerraron todas sus sesiones |
| `contrasena_restablecida` | A la cuenta | Si no fue ella, tiene que avisar de inmediato |

### Avisos por umbral, en una ventana de 15 minutos por cuenta

| Evento | Umbral | A quién |
|---|---|---|
| `2fa_fallido` | 5 | Equipo y la cuenta |
| `login_admin_fallido` | 5 | Equipo y la cuenta |
| `acceso_denegado` | 5 | Equipo |
| `requiere_2fa` | 10 | Equipo y la cuenta |

Los correos solo dicen qué pasó, cuándo, desde qué IP y con qué dispositivo. Nunca incluyen contraseñas, códigos ni enlaces que inicien sesión.

## Ancla externa de la bitácora

La cadena de hashes detecta si alguien edita o borra una fila. Lo que no puede detectar sola es que alguien con acceso total a la base rehaga la cadena completa desde cero. El ancla resuelve eso.

Cada `ANCLA_CADA_DIAS` (7 por omisión) la API verifica la cadena y manda por correo el número del último evento y su hash. Ese correo vive fuera del servidor. Para comprobar más adelante que nada cambió se usa

```bash
curl "https://api.tu-dominio.mx/v1/admin/bitacora/verificar?hastaId=1234&hash=9af1..." \
  -H "authorization: Bearer fqs_at_..."
```

La respuesta trae `coincideAncla`. Si es `false`, la bitácora se reescribió después de ese correo. Si la verificación de la cadena falla, el correo semanal sale con el asunto URGENTE y dice cuál es la primera fila alterada. También se puede mandar un ancla en el momento con `POST /v1/admin/bitacora/anclar`.

## Retención de datos

La LFPDPPP pide no conservar datos personales más tiempo del necesario. Estas son las reglas del sistema.

| Dato | Cuánto se conserva | Cómo |
|---|---|---|
| Bitácora de seguridad (incluye IPs) | 12 meses en la base, configurable con `BITACORA_RETENCION_MESES` | `python -m fqs.scripts.podar_bitacora` archiva las filas viejas cifradas y las borra |
| Logs del servidor en Docker (incluyen IPs) | 5 archivos de 10 MB por servicio | Rotación de Docker en `docker-compose.yml` |
| Cuentas de familia sin uso | Aviso a los 24 meses sin entrar, solicitud de eliminación 30 días después | Tarea automática cada hora, `CUENTAS_INACTIVAS_MESES` |
| Registros sin verificar | 1 día después de vencer el código | Limpieza automática cada 6 horas |
| Sesiones revocadas o vencidas | 7 a 30 días | Limpieza automática cada 6 horas |
| Códigos de recuperación y desafíos de segundo factor | 1 día después de vencer | Limpieza automática cada 6 horas |
| Respaldos | Los últimos 14 | `RESPALDO_CONSERVAR` |
| Cuenta eliminada a petición de la persona | Se anonimiza al atender la solicitud | Flujo ARCO existente |

### Poda de la bitácora sin romper la cadena

La bitácora es de solo agregar, ni el dueño de la base puede borrar filas. La única excepción es la función `podar_bitacora`, que solo corre con el usuario dueño y hace todo en una transacción.

1. El script guarda las filas viejas en `respaldos/bitacora-hasta-N.fqsr`, cifradas con AES-256-GCM y la misma `RESPALDO_CLAVE` de los respaldos.
2. Registra un corte en `bitacora_cortes` con el número y el hash de la última fila que se va a borrar.
3. Borra solo esas filas. El trigger revisa que cada fila borrada esté cubierta por un corte.

Después de la poda la verificación empieza en el hash del último corte, así la cadena sigue completa. Un ancla vieja también se puede seguir comprobando, porque `coincideAncla` busca el hash en las filas que quedan y en los cortes. Los cortes tampoco se pueden editar ni borrar.

```bash
python -m fqs.scripts.podar_bitacora
```

Conviene correrlo una vez al mes con cron, después del respaldo.

### Cuentas inactivas

Una cuenta de familia que no entra en `CUENTAS_INACTIVAS_MESES` recibe un correo que avisa que se eliminará en 30 días. Si en ese tiempo no entra, se crea una solicitud de eliminación con origen `inactividad`, y el equipo la atiende igual que cualquier otra (anonimiza la cuenta y borra sus fotos). Entrar a la app en cualquier momento cancela el aviso y la solicitud. Las cuentas de administración no entran en esta regla.
