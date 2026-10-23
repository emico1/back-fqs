# Fijación de certificado en la app

Sin fijación, la app confía en cualquier certificado firmado por una autoridad que el teléfono tenga instalada de fábrica. Es suficiente en la mayoría de los casos, porque la versión release ya ignora los certificados que instala el usuario (que es como funcionan los proxies de intercepción). La fijación agrega una capa más. La app solo acepta la conexión si alguna llave pública de la cadena del servidor coincide con una huella que trae la propia app, aunque alguien consiga un certificado válido para el dominio.

El riesgo de fijar es dejar la app sin servicio si el servidor cambia de llave y la app no la conoce. Por eso está desactivada por omisión y Gradle exige al menos dos huellas.

## Qué fijar con Caddy y Let's Encrypt

Por omisión Caddy genera una llave nueva cuando renueva el certificado (cada 60 días aproximadamente, y Let's Encrypt planea acortar la vigencia), así que fijar la llave del certificado del servidor rompería la app en la primera renovación. Lo recomendable es fijar las llaves de las dos raíces de Let's Encrypt, que duran hasta 2035 y 2040. OkHttp revisa toda la cadena, incluida la raíz.

| Raíz | Huella SHA-256 de la llave pública | Vence |
|---|---|---|
| ISRG Root X1 | `sha256/C5+lpZ7tcVwmwQIMcRtPbsQtWLABXhQzejna0wHFr8M=` | junio de 2035 |
| ISRG Root X2 | `sha256/diGVwiVYbubAI3RW4hB9xU8e/CH2GnkuvVFZE8zmgzI=` | septiembre de 2040 |

Estas huellas se calcularon desde los certificados raíz del sistema con el comando de abajo. Si el servidor usa otra autoridad (por ejemplo ZeroSSL) hay que calcular las de esa autoridad.

## Cómo activarla

En `gradle.properties` de la app

```properties
fqs.api.release=https://api.tu-dominio.mx/
fqs.api.pins=sha256/C5+lpZ7tcVwmwQIMcRtPbsQtWLABXhQzejna0wHFr8M=,sha256/diGVwiVYbubAI3RW4hB9xU8e/CH2GnkuvVFZE8zmgzI=
```

Solo aplica a la versión release. En debug la app habla con la computadora por HTTP y no hay certificado que fijar.

## Calcular una huella

De un certificado en archivo

```bash
openssl x509 -in certificado.pem -pubkey -noout | openssl pkey -pubin -outform der \
  | openssl dgst -sha256 -binary | openssl enc -base64
```

De lo que presenta el servidor, uno por cada certificado de la cadena

```bash
openssl s_client -connect api.tu-dominio.mx:443 -servername api.tu-dominio.mx -showcerts </dev/null
```

## Cómo comprobar que funciona

1. Compila la versión release con una huella equivocada en `fqs.api.pins` (dos huellas inventadas con el formato correcto).
2. Abre la app. Ninguna pantalla debe cargar datos y en Logcat aparece `Certificate pinning failure`.
3. Vuelve a poner las huellas correctas y la app funciona.

La implementación usa `CertificatePinner` de OkHttp en `ClienteHttp.kt`. Se aplica al cliente de la API, al de renovación de sesión, a las imágenes (Coil) y al flujo de cupos en vivo, porque todos parten del mismo cliente.
