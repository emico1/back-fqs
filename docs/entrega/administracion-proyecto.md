# Administración final del proyecto

Equipo Fernanda Santillán Dantés, Katia Marlene Villarreal Alvarado, Juan Esteban Jaramillo Lucero y Emiliano Cabrera Osuna. Socio formador Familias que Suman.

Las secciones marcadas como por completar necesitan datos que solo tiene el equipo (fechas del Planner y quién hizo cada tarea). Lo demás sale del código, de los repositorios y de los documentos de las entregas.

## Backlog final

### Requerimientos funcionales

| Id | Requerimiento | Estado |
|---|---|---|
| RF-01 | Asociaciones verificadas con su información | Terminado |
| RF-02 | Contenido por ciudad | Terminado |
| RF-05 | Cupos en tiempo real | Terminado |
| RF-07 | Recordatorios | Terminado |
| RF-09 | Proyectos con campañas | Terminado |
| RF-11 | Historial de participación | Terminado |
| RF-12 | Experiencias con foto e historias | Terminado, falta evidencia de cámara en dispositivo |
| RF-13 | Encuestas antes y después | Terminado |
| RF-15 | Privacidad y derechos ARCO | Terminado |
| RF16 | Notificaciones | Terminado, falta evidencia de push real en dispositivo |
| RF17 | Proponer causas | Terminado |
| RF18 | Reportar malas experiencias | Terminado |
| RF19 | Registro con preferencias | Terminado |
| RF20 | Favoritos con notificaciones | Terminado |
| RF21 | Me gusta y no me gusta | Terminado |
| RF-03, RF-04, RF-06, RF-08, RF-10, RF-14 | Por completar con el texto del Planner | Por completar |

### Historias de usuario y casos

| Id | Historia | Estado |
|---|---|---|
| CP-01 | Como familia quiero proponer una asociación o iniciativa para que la organización la revise | Terminado con el error diseñado de asociación existente |
| CU-02 | Como familia quiero seguir y evaluar una asociación para recibir sus novedades y opinar | Terminado con el error diseñado de evaluar sin asistir |
| SA-01 | Como familia quiero registrar a mis acompañantes y que reciban la confirmación por correo | Terminado |
| SA-02 | Como organización quiero que solo existan cuentas individuales | Terminado |
| HU-ADM | Como equipo de la organización quiero administrar todo desde un panel web | Terminado |

### Tareas técnicas

| Tarea | Estado |
|---|---|
| Esquema de base de datos con reglas críticas en PostgreSQL (migraciones 01 a 10) | Terminado |
| API en FastAPI con validación estricta y descripción OpenAPI | Terminado |
| Límites de peticiones por ruta con slowapi, sin límite global | Terminado |
| 146 pruebas de integración, de rechazo, de métricas y de reintentos con pytest | Terminado |
| Monitoreo con Prometheus y Grafana, reglas de alerta y tablero | Terminado, falta la captura del tablero en la computadora del equipo |
| Uso sin conexión en la app (Room y WorkManager) y reintentos idempotentes en la API | Terminado en código, falta compilar y probar en modo avión |
| Máquina virtual de Azure con script y cloud-init | Terminado, corre en Chile Central con el túnel |
| Docker Compose con Caddy y perfil de túnel | Terminado |
| Panel web de administración | Terminado |
| Respaldos cifrados, rotación de claves y poda de la bitácora | Terminado |
| Escaneos con OWASP ZAP y sqlmap | Terminado |
| APK release firmado e instalado en un teléfono físico | Pendiente del equipo |
| Grabación de la demostración por el túnel | Pendiente del equipo |

### Requerimientos no funcionales

Los RNF-01 a RNF-11 de la [matriz de trazabilidad](matriz-trazabilidad.md) cubren los controles de la parte 2 de la rúbrica. Todos están cumplidos salvo la evidencia en dispositivo (RNF-08, RNF-10 y RNF-11).

## Qué quedó terminado, parcial y fuera

| Situación | Elementos |
|---|---|
| Terminado y probado | Todos los RF referenciados en el código, CP-01, CU-02, los pedidos del socio y los controles de seguridad |
| Parcial | RF-12 y RF16 están probados en el backend, falta grabar la cámara y el push en un teléfono físico |
| Fuera | Inscripciones y entregas sin conexión (dependen de los lugares en ese momento), varias instancias de la API (los límites viven en memoria), publicación en Google Play |

## Bitácora de hitos

| Hito | Fecha prevista | Fecha real | Cumplimiento |
|---|---|---|---|
| Primera entrega, requerimientos y diseño | Por completar | Por completar | Por completar |
| Avance del reto, CP-01, CU-02 y preguntas al socio | Por completar | Por completar | Por completar |
| Esquema de base de datos | Por completar | Por completar | Por completar |
| App conectada al backend (fase 1 y fase 2) | Por completar | Por completar | Por completar |
| Panel web de administración | Por completar | 19 de octubre de 2026 | Por completar |
| Backend en FastAPI con límites por ruta, pruebas y escaneos | Por completar | 20 de octubre de 2026 | Por completar |
| Monitoreo con Prometheus y Grafana | Por completar | 20 de octubre de 2026 | Por completar |
| Tercera entrega y presentación final | Por completar | Por completar | Por completar |

## Desviaciones

| Desviación | Causa | Efecto | Qué se hizo |
|---|---|---|---|
| Las cuentas pasaron de familiares a individuales con acompañantes | Respuesta del socio formador | Cambió el registro y el modelo de datos | Migración del esquema y acompañantes con correo de confirmación |
| Se agregó un panel web que no estaba en el plan | Administrar desde la app era incómodo para el equipo de la organización | Más alcance | Panel sin dependencias servido por la misma API |
| Se agregó verificación por SMS | Algunas familias no usan correo | Riesgo de costo por bombeo de SMS | Solo números de México y topes diarios |
| Uso sin conexión con alcance limitado | Una inscripción sin red podría tomar un lugar que ya no existe | Las inscripciones y entregas siguen siendo solo en línea | Copias cifradas de las consultas y cola idempotente para favoritos, calificaciones, propuestas, reportes y testimonios |

## Riesgos

| Riesgo | Probabilidad e impacto | Acción tomada | Resultado |
|---|---|---|---|
| Robo de cuenta de administración | Media y alto | Segundo factor obligatorio, sesión corta, alertas por correo | Probado con pruebas automáticas |
| Filtración de credenciales en el repositorio | Media y alto | `.gitignore`, gitleaks en CI, el archivo de Firebase nunca va en el repositorio ni en los zips | gitleaks sin hallazgos en lo entregado |
| Fuerza bruta y abuso de la API | Alta y medio | Límites por ruta y por cuenta | 429 comprobado en pruebas y en el escaneo |
| Costo de SMS por abuso | Media y medio | Topes por número y por día | Probado |
| Pérdida de datos del servidor | Baja y alto | Respaldos cifrados diarios y verificación de que se pueden abrir | Probado restaurando un respaldo |
| Dependencia de servicios externos (Brevo, Firebase) | Media y medio | El sistema arranca y funciona sin ellos, solo se pierde el envío | Comprobado sin llaves configuradas |
| Ataque o falla sin que nadie se entere | Media y alto | Prometheus con alertas de API caída, errores, ráfagas de 429, fallos de administración y reuso de tokens, y tablero en Grafana | Alertas disparadas en la prueba con Prometheus |
| Que la organización no tenga quien opere el servidor | Media y alto | Manual de instalación, scripts de operación y plan de implantación | Por validar con el socio |

## Distribución del trabajo

Por completar por el equipo con las tareas del Planner y los commits de cada integrante. La evidencia más directa es el historial de los dos repositorios.

```bash
git shortlog -sn --all
git log --author="Nombre" --oneline
```

| Integrante | Responsabilidades | Contribuciones principales | Evidencia |
|---|---|---|---|
| Fernanda Santillán Dantés | Por completar | Por completar | Commits y tareas del Planner |
| Katia Marlene Villarreal Alvarado | Por completar | Por completar | Commits y tareas del Planner |
| Juan Esteban Jaramillo Lucero | Por completar | Por completar | Commits y tareas del Planner |
| Emiliano Cabrera Osuna | Por completar | Por completar | Commits y tareas del Planner |

## Retrospectiva

### Qué funcionó

- **Definir el contrato de la API antes que las pantallas.** La app y el panel se construyeron contra rutas, JSON y errores ya definidos, así el trabajo del backend y el de la app avanzaron en paralelo sin bloquearse.
- **Pruebas de integración contra la base real.** Probar con el mismo rol de mínimo privilegio que producción encontró problemas de permisos que pruebas con una base simulada no habrían visto.
- **Poner las reglas críticas en PostgreSQL.** La concurrencia del último lugar y las reglas de edad y asistencia se resolvieron una vez, en la base, y ningún error del backend las puede saltar.
- **Preguntar al socio formador con opciones concretas.** Preguntas cerradas como cuenta individual o familiar dieron respuestas que se pudieron implementar sin interpretación.

### Qué no funcionó

- **Confirmar tarde las restricciones técnicas del curso.** Algunas decisiones de tecnología y de límites de peticiones se ajustaron después de la revisión con el profesor, a pocos días de la entrega, cuando debieron acordarse al inicio.
- **Dejar la evidencia en dispositivo para el final.** El backend tiene pruebas automáticas, pero la cámara, el push real y el APK firmado solo se comprueban en un teléfono, y eso quedó pendiente.
- **El backlog no siempre reflejó lo que se construyó.** Hubo funciones que se agregaron (panel web, SMS) sin actualizar el Planner al momento, y al armar la matriz de trazabilidad hubo que reconstruir los identificadores desde el código.

### Qué cambiaríamos en un proyecto similar

1. En la primera semana pedir por escrito al profesor las restricciones técnicas (lenguaje, framework, base de datos, despliegue) y guardarlas en el repositorio.
2. Escribir la matriz de trazabilidad desde la primera entrega y actualizarla en cada pull request, con el id del requerimiento en el nombre de la rama o del commit.
3. Diseñar los límites de peticiones como parte de cada endpoint, revisando su riesgo, en lugar de agregarlos al final.
4. Grabar la evidencia en dispositivo al terminar cada flujo, no al final del semestre.
5. Mantener el contrato de la API en un archivo OpenAPI versionado, para que la app y el backend se revisen contra él en cada cambio.
