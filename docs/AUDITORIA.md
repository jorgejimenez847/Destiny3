# Revisión de la auditoría cruzada

Fuente: Auditoría Cruzada de Software, 15/10/2026. Se contrastaron los hallazgos con el código y PostgreSQL, conservando los requisitos del Laboratorio 3.

| Hallazgo | Clasificación | Respuesta |
|---|---|---|
| H-01 Arranque sin entorno | Parcialmente aceptado | Las dependencias son un requisito previo. Se documenta la instalación con Anaconda. |
| H-02 Paquetes faltantes | Aceptado | Ya estaban declarados; se instalaron desde requirements.txt. |
| H-03 Falta de .env | Parcialmente aceptado | Se exigen secretos externos y se añade un generador local. No se acepta una SECRET_KEY fija por defecto. |
| H-04 Base sin configurar | Parcialmente aceptado | Se parametriza Docker y se documenta PostgreSQL. No se oculta una configuración incompleta cambiando de motor. |
| H-05 PostgreSQL detenido | Parcialmente aceptado | Es un problema del servicio local. Se comprueban conectividad, healthcheck y migraciones. |
| H-06 Respaldo SQLite | Rechazado | PostgreSQL es obligatorio y aporta la exclusión de intervalos. Docker permite reproducir el entorno local. |
| H-07 Migraciones sin aplicar | Parcialmente aceptado | Las migraciones ya estaban versionadas; aplicarlas forma parte de la instalación. Las nuevas también se incluyen. |
| H-08 Falta de datos demo | Parcialmente aceptado | El comando existía. Se documenta y amplía sin reemplazar cuentas ni contraseñas. |
| H-09 Pruebas sin entorno | Parcialmente aceptado | Requieren dependencias y base de pruebas. Se amplía la suite sobre PostgreSQL. |
| H-10 Prueba final satisfactoria | Rechazado como defecto | Es evidencia positiva de la auditoría, no un error. La validación de esta entrega se registra por separado. |

Se corrigió además la colisión de DEBUG con variables de Windows usando DJANGO_DEBUG, se verificó el CSS compilado y se añadieron restricciones positivas para precio y duración.
