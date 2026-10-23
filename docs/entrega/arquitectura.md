# Arquitectura del sistema

Familias que Suman tiene tres piezas que se comunican solo por HTTPS. La app Android la usan las familias, el panel web lo usa el equipo de la organización, y las dos consumen la misma API. La API es la única que habla con la base de datos. El servidor puede ser cualquier máquina con Docker. El despliegue actual es una máquina virtual de Azure en Chile Central (ver [../seguridad/despliegue-azure.md](../seguridad/despliegue-azure.md)).

```mermaid
flowchart LR
    subgraph Telefono[Teléfono Android]
        APP[App Familias que Suman<br/>Kotlin y Jetpack Compose<br/>Retrofit y OkHttp]
        ROOM[(Room<br/>copias de consultas<br/>y envíos pendientes)]
        KS[(Android Keystore<br/>llaves AES-GCM)]
        WM[WorkManager<br/>envíos al volver la red]
        APP --- ROOM
        APP --- KS
        WM --- ROOM
    end
    subgraph Navegador[Navegador del equipo]
        PANEL[Panel web<br/>HTML, CSS y JavaScript]
    end
    CFE[Cloudflare<br/>certificado público]
    subgraph Servidor[Máquina virtual de Azure o computadora con Docker]
        TUNEL[cloudflared<br/>túnel de salida]
        CADDY[Caddy<br/>HTTPS, HSTS, límite de 6 MB]
        API[API FastAPI<br/>uvicorn, Python 3.13]
        DB[(PostgreSQL 16)]
        FOTOS[(Volumen de fotos)]
        PROM[Prometheus<br/>métricas y alertas]
        GRAF[Grafana<br/>solo en 127.0.0.1]
    end
    OPER[Persona que opera el servidor]
    FCM[Firebase Cloud Messaging]
    BREVO[Brevo<br/>correo y SMS]
    HIBP[Pwned Passwords]

    APP -- HTTPS con Bearer --> CADDY
    APP -- HTTPS con Bearer --> CFE
    WM -- HTTPS con Idempotency-Key --> CFE
    CFE -- túnel --> TUNEL
    PANEL -- HTTPS con cookies HttpOnly --> CADDY
    CADDY --> API
    TUNEL --> API
    API -- rol fqs_backend --> DB
    API --> FOTOS
    API -- push --> FCM
    FCM -. notificación .-> APP
    API --> BREVO
    API -- 5 caracteres del SHA-1 --> HIBP
    DB -. NOTIFY de cupos y avisos .-> API
    PROM -- métricas en un puerto aparte --> API
    GRAF --> PROM
    OPER -- túnel SSH --> GRAF
```

## Capas de la app Android

| Capa | Contenido | Archivos principales |
|---|---|---|
| Interfaz | Pantallas de Jetpack Compose (inicio, explorar, actividad, campaña, proyecto, comunidad, historial, propuestas, notificaciones, perfil, privacidad, sesiones, seguridad de administración) | `ui/screens`, `ui/components` |
| Estado | `AppViewModel` pide datos al repositorio y expone el estado de cada pantalla (cargando, listo, error con reintento) | `viewmodel` |
| Datos | Repositorio único, cliente HTTP con Retrofit y OkHttp, modelos y mapeos del JSON de la API, flujo de cupos en tiempo real | `data/Repositorio.kt`, `data/remote` |
| Sesión | Tokens guardados cifrados con AES-GCM y una llave del Android Keystore, renovación automática al recibir 401 | `data/sesion` |
| Sin conexión | Room guarda cifrada la última respuesta de cada consulta y la cola de envíos pendientes. WorkManager manda la cola cuando vuelve la red, cada envío con su clave de idempotencia | `data/local` |
| Dispositivo | Cámara y galería para fotos, notificaciones push, llamada, WhatsApp, correo y mapas con intents del sistema | `data/Imagenes.kt`, `push` |

## Capas de la API

| Capa | Responsabilidad | Carpeta |
|---|---|---|
| Entrada HTTP | Middleware propio que pone el id de petición, calcula la IP real, agrega los encabezados de seguridad, limita el tamaño del cuerpo y exige `application/json` | `fqs/http/middleware.py` |
| Autenticación y acceso | Lee la sesión (Bearer o cookie del panel), revisa CSRF en el panel, y las dependencias `Usuario` y `Admin` exigen el nivel de cada ruta | `fqs/http/dependencias.py`, `fqs/http/cookies.py` |
| Límites | Decoradores de slowapi en cada ruta sensible y límites por cuenta | `fqs/limites.py` |
| Validación | Modelos estrictos de Pydantic, parámetros de ruta solo UUID | `fqs/validacion.py`, cada módulo de `fqs/rutas` |
| Rutas | Un módulo por área de negocio | `fqs/rutas` |
| Seguridad | Contraseñas, sesiones, segundo factor, bitácora, imágenes, QR, contraseñas filtradas | `fqs/seguridad` |
| Servicios | Base de datos, correo, SMS, push, almacenamiento de fotos, cupos en tiempo real, vigilancia de la bitácora | `fqs/db.py`, `fqs/correo.py`, `fqs/sms.py`, `fqs/push.py`, `fqs/almacen.py`, `fqs/tiempo_real.py`, `fqs/vigilancia.py` |
| Errores | Una sola forma de error para toda la API, traducción de errores de PostgreSQL | `fqs/http/manejo_errores.py`, `fqs/errores.py` |
| Métricas | Contadores e histogramas por plantilla de ruta, inicios de sesión y eventos de seguridad, servidos en un puerto que no es el de la API | `fqs/metricas.py` |

## Capa de datos

PostgreSQL 16 guarda todo en el schema `fqs`. Además de las tablas, la base tiene las reglas que no se pueden saltar aunque falle el backend.

- Cupos, edad mínima y dueño de los acompañantes se revisan en funciones y triggers dentro de la misma transacción de la inscripción.
- Las transiciones de estado de propuestas, testimonios y entregas se validan con triggers.
- La bitácora de seguridad es de solo agregar, cada fila lleva el hash de la anterior.
- Los avisos (recordatorios, sugerencias, favoritos, encuestas) se generan con funciones SQL y se anuncian con `NOTIFY`.
- La API se conecta con un rol del grupo `fqs_backend`, que no puede cambiar el esquema ni borrar la bitácora.

Los scripts están en `db/` del 01 al 10 y se aplican en orden.

## Flujo de una petición

1. La app manda la petición por HTTPS con su token en `Authorization`.
2. Caddy (o el túnel) termina TLS y pasa la petición a la API con la IP real en `X-Forwarded-For`.
3. El middleware asigna un id, revisa tamaño y tipo de contenido.
4. FastAPI resuelve la ruta. La dependencia de sesión busca el SHA-256 del token en la tabla `sesiones`.
5. Si la ruta tiene límite, slowapi cuenta la petición y responde 429 si se pasó.
6. Pydantic valida el cuerpo. Un campo de más o de otro tipo responde 400.
7. La ruta consulta PostgreSQL con parámetros. Las reglas de negocio críticas las aplica la base.
8. La respuesta sale con CSP, `nosniff`, `no-store` y HSTS, queda una línea en el log con la ruta, el estado y el tiempo, y se suman las métricas de esa plantilla de ruta.

## Tiempo real y notificaciones

Cuando cambian los lugares de una actividad, un trigger hace `NOTIFY fqs_cupos`. Una sola conexión de la API escucha ese canal y reenvía el cambio a las apps conectadas por Server-Sent Events (`GET /v1/cupos/stream`). Cuando se crea una notificación, otro trigger hace `NOTIFY fqs_notificaciones` y la API la manda por Firebase Cloud Messaging al teléfono.

## Monitoreo

La API publica métricas en el puerto 9464, que solo escucha en la red interna `monitoreo`. Prometheus las lee cada 15 segundos, las guarda 15 días y evalúa 9 reglas de alerta (API caída, errores 5xx, latencia, ráfagas de 429, inicios de sesión fallidos, fallos de administración, accesos denegados, reuso de refresh tokens y fallas al escribir la bitácora). Grafana consulta a Prometheus por la misma red y muestra el tablero, publicado solo en 127.0.0.1 del servidor. Ver [../seguridad/monitoreo.md](../seguridad/monitoreo.md).

## Uso sin conexión

Cada consulta que llega bien del backend se guarda en Room, cifrada con una llave del Android Keystore distinta de la de la sesión. Si después no hay red, la pantalla muestra esa copia y un aviso al pie con la hora en que se guardó y un botón para reintentar. Un error del servidor (por ejemplo 401 o 404) nunca se tapa con la copia.

Las escrituras que no compiten por un recurso limitado se pueden hacer sin conexión. Son favoritos, avisos de una asociación, me gusta y no me gusta, propuestas, reportes y testimonios con su foto. Si fallan por falta de red se guardan en una cola (las fotos cifradas en una carpeta que no se respalda), la acción se da por hecha y el aviso al pie dice cuántos envíos esperan. WorkManager los manda en orden cuando hay red, aunque la app esté cerrada o el teléfono se haya reiniciado, con espera exponencial si el servidor no responde.

Cada envío lleva una clave de idempotencia que se genera una sola vez. Si la respuesta se pierde en el camino y se reintenta, la API devuelve la respuesta original en lugar de crear otra propuesta o reporte (`fqs/idempotencia.py`, tabla `idempotencia` de `db/10_idempotencia.sql`). Si el servidor rechaza un envío (por ejemplo calificar una actividad a la que no se asistió), el aviso al pie muestra su mensaje.

Inscribirse, cancelar y registrar entregas siempre necesitan conexión, porque dependen de los lugares y de las campañas activas en ese momento. Al cerrar sesión, al expirar la sesión o al pedir la eliminación de la cuenta se borra todo lo guardado en el teléfono.

## Despliegue actual

El sistema corre en una máquina virtual de Azure en Chile Central. La app y el panel entran por el túnel de Cloudflare, la máquina solo acepta SSH desde la IP del equipo, y cada servicio está en la red de Docker que necesita. La imagen está en [arquitectura-despliegue.png](arquitectura-despliegue.png).

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, Segoe UI, Arial","fontSize":"14px","lineColor":"#5B6B7F","clusterBkg":"#F7F9FC","clusterBorder":"#C9D3E0","edgeLabelBackground":"#FFFFFF"},"flowchart":{"curve":"basis","nodeSpacing":40,"rankSpacing":70,"padding":12}}}%%
flowchart LR

    subgraph CLIENTES["Clientes"]
        direction TB
        subgraph MOVIL["App Android 0.3.1 · APK release firmado"]
            direction TB
            APP["<b>App Familias que Suman</b><br/>Kotlin · Jetpack Compose<br/>Retrofit · OkHttp"]
            ROOM[("<b>Room</b><br/>copias de consultas<br/>envíos pendientes")]
            KS[("<b>Android Keystore</b><br/>AES-256-GCM<br/>sesión y datos locales")]
            WM["<b>WorkManager</b><br/>envíos al volver la red"]
            APP --- ROOM
            APP --- KS
            WM --- ROOM
        end
        PANEL["<b>Panel web</b><br/>HTML · CSS · JavaScript<br/>cookies HttpOnly"]
        OPS(["<b>Equipo de operación</b><br/>SSH con llave Ed25519<br/>túnel SSH a Grafana"])
    end

    subgraph INTERNET["Internet"]
        direction TB
        CFE["<b>Cloudflare</b><br/>TLS con certificado público<br/>túnel trycloudflare.com"]
    end

    subgraph AZURE["Microsoft Azure · Chile Central · Azure for Students"]
        direction LR
        NSG{{"<b>Grupo de seguridad de red</b><br/>solo SSH 22 desde la IP del equipo<br/>80 y 443 cerrados"}}
        subgraph VM["vm-familias · Standard_B2als_v2 · Ubuntu 24.04 · Trusted Launch"]
            direction LR
            subgraph SALIDA["Red salida"]
                direction TB
                CFD["<b>cloudflared</b><br/>túnel de salida"]
                CADDY["<b>Caddy</b><br/>HTTPS · HSTS"]
            end
            subgraph APLICACION["Aplicación"]
                API["<b>API FastAPI</b> :3000<br/>tokens opacos · 2FA admin<br/>límites por ruta slowapi<br/>Idempotency-Key · bitácora"]
            end
            subgraph INTERNA["Red interna sin internet"]
                direction TB
                PG[("<b>PostgreSQL 16</b><br/>rol de mínimo privilegio")]
                FOTOS[("<b>Volumen de fotos</b><br/>sin metadatos")]
            end
            subgraph MONITOREO["Red monitoreo sin internet"]
                direction TB
                PROM["<b>Prometheus</b><br/>métricas 15 días · 9 alertas"]
                GRAF["<b>Grafana</b><br/>solo 127.0.0.1 3001"]
            end
        end
    end

    subgraph EXTERNOS["Servicios externos"]
        direction TB
        FCM(["<b>Firebase Cloud Messaging</b><br/>push al teléfono"])
        BREVO(["<b>Brevo</b><br/>correo y SMS"])
        HIBP(["<b>Pwned Passwords</b><br/>k-anonimato"])
    end

    APP   -->|"HTTPS · REST /v1 · Bearer"| CFE
    WM    -->|"HTTPS · Idempotency-Key"| CFE
    PANEL -->|"HTTPS · cookies"| CFE
    CFE   -->|"túnel cifrado"| CFD
    CFD   -->|"HTTP interno"| API
    CADDY -.->|"entrada con dominio propio"| API
    API   -->|"SQL parametrizado · psycopg"| PG
    API   --> FOTOS
    PG    -.->|"NOTIFY cupos y avisos"| API
    PROM  -->|"GET /metrics puerto 9464"| API
    GRAF  -->|"PromQL"| PROM
    API   -->|"push"| FCM
    API   -->|"códigos y avisos"| BREVO
    API   -->|"5 caracteres del SHA-1"| HIBP
    OPS   -->|"SSH 22"| NSG

    classDef client fill:#E8F0FB,stroke:#1F3A5F,stroke-width:1.5px,color:#1F3A5F
    classDef edge   fill:#FFF4E5,stroke:#F38020,stroke-width:1.5px,color:#7A3E00
    classDef app    fill:#E6F4EC,stroke:#2E9E5B,stroke-width:2px,color:#14532D
    classDef data   fill:#F1EAFB,stroke:#6B46C1,stroke-width:1.5px,color:#3B1F73
    classDef obs    fill:#FEF3E2,stroke:#E8710A,stroke-width:1.5px,color:#7C3A00
    classDef sec    fill:#FDECEC,stroke:#C53030,stroke-width:1.5px,color:#742A2A
    classDef ext    fill:#FFFFFF,stroke:#8A97A8,stroke-width:1.5px,stroke-dasharray:5 4,color:#3A4656

    class APP,ROOM,KS,WM,PANEL client
    class CFE,CFD,CADDY edge
    class API app
    class PG,FOTOS data
    class PROM,GRAF obs
    class NSG sec
    class FCM,BREVO,HIBP,OPS ext

    style CLIENTES   fill:#F7F9FC,stroke:#1F3A5F,stroke-width:1.5px
    style MOVIL      fill:#FFFFFF,stroke:#9DB3D3
    style INTERNET   fill:#FAFAFA,stroke:#B0B8C4,stroke-dasharray:6 4
    style AZURE      fill:#F3F8FD,stroke:#0078D4,stroke-width:2px
    style VM         fill:#FFFFFF,stroke:#2496ED,stroke-width:1.5px,stroke-dasharray:6 4
    style SALIDA     fill:#FFFBF5,stroke:#F3C089
    style APLICACION fill:#F6FBF8,stroke:#9FD3B4
    style INTERNA    fill:#FAF7FE,stroke:#C5B3EA
    style MONITOREO  fill:#FFFAF3,stroke:#F5C48A
    style EXTERNOS   fill:#FAFAFA,stroke:#B0B8C4,stroke-dasharray:6 4
```
