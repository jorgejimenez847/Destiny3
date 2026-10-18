# Revisión técnica de la auditoría cruzada

Fuentes: Auditoría Cruzada de Software (15/10/2026) y Laboratorio 3, secciones 8 y 9.
Los resultados de otro equipo describen su instalación; no demuestran por sí solos defectos del código ni pruebas sobre PostgreSQL.

| Hallazgo | Clasificación | Justificación y respuesta |
|---|---|---|
| H-01 Arranque sin entorno configurado | Parcialmente aceptado | Las dependencias son un prerrequisito. Se documenta Anaconda y una secuencia de instalación verificable. No debe arrancar sin Django instalado. |
| H-02 Paquetes faltantes | Aceptado | Faltaban decouple, widget-tweaks y el controlador PostgreSQL en dsw8408; requirements.txt ya los declaraba. Se instalaron desde ese archivo, sin añadir dependencias de aplicación. |
| H-03 Arranque sin .env | Parcialmente aceptado | Es correcto exigir secretos externos. Se añade generador local con claves aleatorias y ejemplo; se rechaza una SECRET_KEY fija como valor por defecto. |
| H-04 Base de datos sin configurar | Parcialmente aceptado | PostgreSQL es obligatorio. Se documenta y parametriza Docker desde .env. No se debe ocultar una configuración incompleta cambiando de motor. |
| H-05 PostgreSQL detenido | Parcialmente aceptado | Es un problema del servicio local; se inicia Docker y se verifica conectividad y migraciones. Se incorpora healthcheck y guía de diagnóstico. |
| H-06 Falta de respaldo local SQLite | Rechazado | PostgreSQL es requisito explícito y garantiza exclusión de intervalos. Docker proporciona la alternativa local reproducible. No habrá fallback silencioso a SQLite. |
| H-07 Base sin inicializar | Parcialmente aceptado | Existían migraciones versionadas; aplicarlas es un paso de instalación. En esta copia las de Fase 1 ya estaban aplicadas. Las nuevas se añaden y verifican. |
| H-08 Falta de datos demo | Parcialmente aceptado | El comando ya existía. Se documenta y amplía sin sobrescribir usuarios ni contraseñas existentes. La clave se obtiene de configuración local o entrada oculta. |
| H-09 Pruebas sin entorno | Parcialmente aceptado | El entorno y la BD de pruebas deben estar preparados. Se conserva la suite y se amplía; no se considera un defecto de la autenticación. |
| H-10 Prueba final satisfactoria | Rechazado como defecto | Es evidencia positiva de 13 pruebas en otro entorno, no un error. Se vuelve a verificar aquí y se registran resultados propios. |

## Hallazgos adicionales de esta revisión

- La variable global DEBUG=release del equipo interfería con python-decouple. Se usa DJANGO_DEBUG con valor por defecto False.
- Las capturas de la auditoría muestran páginas sin CSS: se exige compilar Tailwind en la instalación y verificar su carga.
- Se añaden restricciones positivas a duración y precio; duración cero no permite un cálculo realista.
- No se integra el flujo de reservas, pagos ni estados de Fase 4.
