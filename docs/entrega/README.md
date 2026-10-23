# Tercera entrega

Índice de lo que pide cada parte de la rúbrica y dónde está.

| Parte | Qué pide | Dónde |
|---|---|---|
| Todas | Cumplimiento de cada punto de la rúbrica | [cumplimiento-rubrica.md](cumplimiento-rubrica.md) |
| 1 | Sistema completo funcionando | Backend en este repositorio, app en el repositorio `fqs-app`, [manual-instalacion.md](manual-instalacion.md) |
| 2.1 | Controles en la API | [../seguridad/README.md](../seguridad/README.md), [../../README.md](../../README.md) sección Seguridad |
| 2.2 | Contenedores, túnel y monitoreo | `Dockerfile`, `docker-compose.yml`, [../seguridad/despliegue.md](../seguridad/despliegue.md), [../seguridad/monitoreo.md](../seguridad/monitoreo.md) |
| 2.3 | Rechazos y OWASP ZAP | `tests/test_08_rechazos.py`, [../seguridad/escaneos.md](../seguridad/escaneos.md) |
| 3 | Evidencia de pruebas y matriz de trazabilidad | [matriz-trazabilidad.md](matriz-trazabilidad.md) |
| 4 | Manual de usuario | [manual-usuario.md](manual-usuario.md) |
| 4 | Manual de instalación | [manual-instalacion.md](manual-instalacion.md) |
| 4 | Arquitectura | [arquitectura.md](arquitectura.md) |
| 4 | Decisiones técnicas | [decisiones-tecnicas.md](decisiones-tecnicas.md) |
| 4 | Plan de implantación | [plan-implantacion.md](plan-implantacion.md) |
| 5 | Administración final del proyecto | [administracion-proyecto.md](administracion-proyecto.md) |
| 6 | Presentación de 15 minutos | Guion abajo |

## Guion de la presentación

| Tiempo | Contenido | Material |
|---|---|---|
| 2 minutos | El problema de la organización (familias que quieren ayudar y no encuentran cómo), alcance y los RF16 a RF21 | Backlog |
| 5 minutos | En el teléfono físico con el APK firmado y el túnel. Registro con código, inscripción con acompañantes viendo los lugares bajar en vivo, donación a una campaña, propuesta con el error de asociación existente, evaluar sin asistir (error de CU-02). En el panel, publicar una actividad y ver la notificación llegar al teléfono | App y panel |
| 2 minutos | Niveles de prueba, 146 pruebas correctas y la matriz con el estado de cada requisito | `pruebas.txt` y la matriz |
| 2 minutos | Límites por ruta con un 429 en vivo que aparece en el tablero de Grafana, rechazo de inyección SQL y de token manipulado, segundo factor, reporte de ZAP | `test_08_rechazos.py`, escaneos y Grafana |
| 1 minuto | Lo diferenciador, cupos en tiempo real sin choques por el último lugar y bitácora encadenada que delata cualquier alteración | Demostración de cupos |
| 3 minutos | Docker Compose con Caddy, túnel, Prometheus y Grafana, plan de implantación, carga inicial y rollback | Plan de implantación |
