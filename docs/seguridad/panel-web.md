# Panel web de administración

El panel es la forma en que el equipo de la OSF administra Familias que Suman desde una computadora, sin usar la API a mano. Lo sirve el mismo backend en `/panel/`, así que con el despliegue de Docker queda en `https://tu-dominio/panel/` con el mismo certificado de Caddy.

Está hecho con HTML, CSS y JavaScript sin dependencias ni paso de compilación. No se descarga nada de terceros (ni fuentes, ni bibliotecas, ni servicios de QR), así que no hay cadena de suministro del lado del navegador que vigilar.

## Qué se puede hacer

| Sección | Acciones |
|---|---|
| Inicio | Pendientes del equipo (propuestas, testimonios, reportes, entregas, solicitudes de eliminación, alertas) y próximas actividades |
| Asociaciones | Buscar, crear, editar, verificar, activar o desactivar, subir foto |
| Actividades | Crear, editar, publicar, regresar a borrador, finalizar, cancelar con motivo, ver participantes y registrar asistencia |
| Encuestas | Crear encuestas antes o después de una actividad, cerrarlas y ver resultados |
| Proyectos y campañas | Crear proyectos, crear campañas con artículos y puntos de entrega, cambiar su estado y ver el avance |
| Comunidad | Revisar propuestas, moderar testimonios, atender reportes, confirmar entregas de donativos y ver la calidad de cada asociación |
| Cuentas | Buscar personas, suspender o reactivar cuentas y resolver solicitudes de eliminación (derechos ARCO) |
| Ajustes | Ciudades, categorías, niveles, insignias y versiones del aviso de privacidad |
| Seguridad | Activar el segundo factor con QR, códigos de respaldo, sesiones abiertas, bitácora, verificación de integridad, ancla y alertas |

## Cómo se protege

### Sesión en cookies que el JavaScript no puede leer

La app Android guarda sus tokens cifrados con el Keystore. En un navegador no existe algo equivalente, y guardar el token en `localStorage` lo deja al alcance de cualquier script que llegue a ejecutarse en la página. Por eso el panel nunca recibe los tokens en el cuerpo de la respuesta, viajan en dos cookies.

| Cookie (producción) | Atributos | Para qué |
|---|---|---|
| `__Host-fqs_panel` | `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, sin `Domain` | Token de acceso de 15 minutos |
| `__Secure-fqs_panel_r` | `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/v1/panel/sesion` | Token de renovación, solo viaja a renovar y salir |

El prefijo `__Host-` obliga al navegador a rechazar la cookie si no trae `Secure`, `Path=/` y ningún `Domain`. Así un subdominio comprometido no puede plantar ni pisar la sesión. En desarrollo (http) se usan los nombres `fqs_panel` y `fqs_panel_r` sin prefijos, porque los prefijos exigen HTTPS.

Las sesiones del panel son sesiones de administración normales, con las mismas reglas que en la app. Cierre tras 30 minutos sin uso, tope de 12 horas, rotación del token de renovación con detección de reuso y la marca de si se abrieron con segundo factor.

### Mismo inicio de sesión que la app

El panel y la app usan el mismo código (`fqs/seguridad/acceso.py`) para revisar la contraseña, aplicar los límites por IP y por cuenta, pedir el código de la app de autenticación y escribir en la bitácora. Ninguna de las dos entradas puede quedar más débil que la otra. Una cuenta de familia que intenta entrar al panel recibe un 403 y el intento queda en la bitácora como `acceso_denegado`.

Con `ADMIN_2FA=obligatorio`, una cuenta sin segundo factor solo puede ver la pantalla de Seguridad para activarlo. El QR lo dibuja el propio servidor (`fqs/seguridad/qr.py`), la clave nunca sale a un servicio externo. El panel lo muestra como imagen, nunca como HTML.

### Falsificación de peticiones (CSRF)

Una cookie se manda sola, así que una página maliciosa podría intentar que el navegador de alguien del equipo haga una acción en el panel. Hay tres capas independientes, como recomienda la hoja de OWASP sobre CSRF.

1. `SameSite=Strict`. El navegador no manda la cookie en peticiones que vienen de otro sitio.
2. Encabezado `X-FQS-Panel`. Toda petición con cookie que no sea GET lo necesita. Un formulario de otro sitio no puede ponerlo, y si un script de otro origen lo intenta el navegador primero hace una consulta CORS que esta API nunca autoriza.
3. Encabezado `Origin`. Si viene, su host tiene que ser exactamente el host al que se habla. `Origin` con valor `null` se rechaza.

Las peticiones con `Authorization` (la app) no cambian, porque un navegador no agrega ese encabezado por su cuenta.

### Contenido que no se ejecuta

- Política CSP propia para el panel, solo recursos del mismo origen, sin scripts ni estilos en línea, sin `eval`, sin objetos y sin poder meterse en un iframe.

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self';
font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

- Todo el texto que viene de la base (nombres de asociaciones, testimonios, propuestas, reportes) se coloca con `textContent`. Si alguien escribe etiquetas HTML en una propuesta, el equipo las ve como texto y no se ejecutan.
- Una prueba automática revisa que ningún archivo del panel use `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function` ni `localStorage`, y que la página no tenga scripts, estilos ni manejadores en línea.
- Los archivos del panel se cargan en memoria al arrancar. Una ruta con `../` o codificada no puede leer nada fuera de la carpeta, simplemente no existe en la lista.

### Fotos oficiales

Con varias personas en el panel, cualquiera del equipo puede editar lo que subió otra, así que una foto de asociación, actividad, proyecto, campaña o insignia puede ser de cualquier cuenta de administración. Una foto subida por una familia nunca se puede usar como foto oficial.

## Evidencia

- [evidencia/panel-https.txt](evidencia/panel-https.txt), el panel en modo producción detrás de Caddy. CSP, HSTS, rechazo por CSRF sin encabezado y con otro origen, ruta con `../` y las cookies con prefijos `__Host-` y `__Secure-`.
- [evidencia/panel/xss-como-texto.png](evidencia/panel/xss-como-texto.png), una asociación con `<script>` en el nombre se ve como texto y no se ejecuta.
- [evidencia/panel/seguridad.png](evidencia/panel/seguridad.png), la pantalla de seguridad con la bitácora verificada.
- [evidencia/panel/inicio.png](evidencia/panel/inicio.png) y [evidencia/panel/actividad.png](evidencia/panel/actividad.png), inicio y ficha de una actividad.

Estas capturas salen de un recorrido automático con Chromium que activa el segundo factor escaneando el QR, cierra sesión, vuelve a entrar con código y crea una asociación, una actividad y una campaña.

## Correo de confirmación a acompañantes

Cuando una familia inscribe a alguien de su comunidad que es mayor de edad el día de la actividad y tiene correo, esa persona recibe la confirmación con la actividad, la asociación, la fecha en la zona horaria de la ciudad, el lugar y el nombre de quien la inscribió. Si el equipo cancela la actividad, recibe también el aviso con el motivo.

| Cuidado | Por qué |
|---|---|
| Nunca se escribe a menores, aunque tengan correo registrado | Protección de datos de niñas, niños y adolescentes |
| Solo se incluye el nombre de quien inscribió, no su correo ni su teléfono | Minimización de datos, el acompañante no necesita más para reconocerla |
| No se escribe al acompañante que tiene el mismo correo que el titular | El titular ya recibe su propio aviso en la app |
| Máximo 30 correos de este tipo por titular al día | El correo del acompañante lo escribe la familia y no está verificado. Sin tope, alguien podría usar las inscripciones para mandar correos a cualquier dirección |
| El envío corre aparte de la petición | Si el proveedor de correo falla, la inscripción ya quedó hecha y solo se registra el error |
| El correo dice que no se creó ninguna cuenta | Quien no conozca a la persona sabe que puede ignorarlo |

## Fuentes
- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Set-Cookie y prefijos de cookies, MDN](https://developer.mozilla.org/pt-BR/docs/Web/HTTP/Reference/Headers/Set-Cookie)
- [OWASP Web Security Testing Guide, almacenamiento del navegador](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/11-Client-side_Testing/12-Testing_Browser_Storage)
