# Verificación en dos pasos de administración

Las cuentas de administración pueden publicar actividades, ver quién asiste, suspender cuentas y anonimizar datos. Por eso la contraseña sola no basta. Además de la contraseña se pide un código de 6 dígitos que cambia cada 30 segundos y que genera una app de autenticación en el teléfono de la persona (Google Authenticator, Microsoft Authenticator, 1Password, Authy o cualquiera compatible con TOTP).

Las familias no usan segundo factor, su inicio de sesión no cambia.

## Cómo funciona

1. La persona escribe correo y contraseña. Si su cuenta tiene el segundo factor activo, el servidor no entrega una sesión sino un desafío de un solo uso que vence en 5 minutos.
2. La persona escribe el código de su app. El servidor lo compara con el secreto de la cuenta, acepta el paso actual, el anterior y el siguiente (por si el reloj del teléfono está un poco desfasado) y guarda cuál aceptó. Un código igual o anterior ya no sirve.
3. Con el código correcto el servidor abre una sesión marcada como verificada. Al renovarse, la sesión conserva esa marca.

Cada desafío permite 5 códigos equivocados y además hay un tope de 5 por cuenta cada 15 minutos. Con 3 códigos válidos en cada momento entre un millón de combinaciones, la probabilidad de adivinar en 5 intentos es menor a 2 en cien mil.

El secreto se guarda cifrado con AES-256-GCM. La clave está en la variable `CLAVE_CIFRADO_2FA`, fuera de la base, y el id de la cuenta va como dato asociado, así copiar el secreto cifrado de una cuenta a otra no funciona.

Mientras la cuenta no tenga el segundo factor activo, el servidor solo le deja usar las rutas para activarlo. Cualquier otra ruta de administración responde 403 con el código `requiere_2fa` y el intento queda en la bitácora.

## Activarlo desde la app

1. Inicia sesión con la cuenta de administración.
2. Abre Perfil y toca Seguridad de administración.
3. Escribe tu contraseña otra vez.
4. Toca Abrir en mi app de autenticación, o copia la clave y agrégala a mano como cuenta basada en tiempo.
5. Escribe el código de 6 dígitos que muestra la app y toca Activar.
6. Guarda los 10 códigos de respaldo en un lugar seguro fuera del teléfono. Se muestran una sola vez.

Al activarlo se cierran las demás sesiones de la cuenta.

## Activarlo con la API

```bash
# 1. Iniciar sesión, la respuesta trae configurar2fa true y un accessToken
curl -X POST https://api.tu-dominio.mx/v1/auth/login -H "content-type: application/json" \
  -d '{"identificador":"admin@tu-dominio.mx","password":"..."}'

# 2. Generar la clave, la respuesta trae secreto y uri (otpauth://...)
curl -X POST https://api.tu-dominio.mx/v1/admin/2fa/iniciar -H "content-type: application/json" \
  -H "authorization: Bearer fqs_at_..." -d '{"password":"..."}'

# 3. Confirmar con el primer código, la respuesta trae los códigos de respaldo
curl -X POST https://api.tu-dominio.mx/v1/admin/2fa/confirmar -H "content-type: application/json" \
  -H "authorization: Bearer fqs_at_..." -d '{"codigo":"123456"}'
```

Desde ese momento el inicio de sesión responde `requiere2fa` y un `desafio`, que se canjea así.

```bash
curl -X POST https://api.tu-dominio.mx/v1/auth/2fa -H "content-type: application/json" \
  -d '{"desafio":"fqs_2f_...","codigo":"123456"}'
```

## Si se pierde el teléfono

Con un código de respaldo se entra igual que con el de la app, en el mismo campo. Cada uno sirve una vez. Ya dentro se pueden generar códigos nuevos con `POST /v1/admin/2fa/codigos-respaldo` enviando un código válido.

Si también se perdieron los códigos de respaldo, quien administra el servidor corre

```bash
python -m fqs.scripts.admin_2fa
```

El script pide el correo de la cuenta y una confirmación, borra su segundo factor, cierra todas sus sesiones y deja el evento `2fa_reiniciado` en la bitácora. La persona tendrá que activarlo de nuevo al entrar.

## Configuración

| Variable | Valor |
|---|---|
| `ADMIN_2FA` | `obligatorio` (por omisión). `opcional` solo se acepta fuera de producción |
| `CLAVE_CIFRADO_2FA` | 32 bytes aleatorios en base64. Se genera con `python -m fqs.scripts.generar_clave`. Si se pierde, todas las cuentas de administración tienen que volver a activar su segundo factor |

## Sesiones de administración

Una sesión de administración se cierra si pasa `ADMIN_INACTIVIDAD_MINUTOS` (30 por omisión) sin usarse y nunca dura más de `ADMIN_SESION_HORAS` (12 por omisión) desde que se inició, aunque se use todo el tiempo. Las familias conservan su sesión de 30 días. Cada inicio de sesión de administración manda un aviso por correo a esa cuenta, ver [vigilancia-y-retencion.md](vigilancia-y-retencion.md).

## Rotar la clave de cifrado

Si se sospecha que `CLAVE_CIFRADO_2FA` se filtró, se cambia sin que nadie tenga que volver a agregar la cuenta en su app.

1. `python -m fqs.scripts.generar_clave`
2. En `.env` mueve la clave vieja a `CLAVES_CIFRADO_2FA_ANTERIORES` y pon la nueva en `CLAVE_CIFRADO_2FA`. Reinicia la API, ya funciona con las dos.
3. `python -m fqs.scripts.rotar_clave_2fa` cifra de nuevo todos los secretos con la clave nueva y deja el evento `clave_2fa_rotada` en la bitácora.
4. Quita `CLAVES_CIFRADO_2FA_ANTERIORES` y reinicia la API.

Cada secreto cifrado lleva un identificador de 4 bytes de la clave con que se cifró (los primeros bytes de su SHA-256, no la clave), así la API sabe con cuál abrirlo.

## Bitácora relacionada

| Evento | Cuándo |
|---|---|
| `login_admin` | Inicio de sesión de una cuenta de administración sin segundo factor activo |
| `login_admin_fallido` | Contraseña equivocada en una cuenta de administración |
| `2fa_desafio` | Contraseña correcta, se pidió el código |
| `2fa_correcto` | Código correcto, sesión abierta |
| `2fa_fallido` | Código equivocado |
| `2fa_codigo_respaldo_usado` | Se entró con un código de respaldo |
| `2fa_iniciado`, `2fa_activado` | Activación |
| `2fa_codigos_regenerados` | Códigos de respaldo nuevos |
| `2fa_reiniciado` | Reinicio desde el servidor |
| `requiere_2fa` | Intento de administrar sin segundo factor |

Las fuentes de los algoritmos son el [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238) y el [RFC 4226](https://www.rfc-editor.org/rfc/rfc4226). La implementación se prueba contra los vectores de prueba de ambos documentos.
