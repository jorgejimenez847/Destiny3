# Validación de la entrega

18 de octubre de 2026 · Python 3.12.13, Django 5.2.17 y PostgreSQL 16.

## Revisión 1: funcionamiento

- **126 pruebas aprobadas** sobre PostgreSQL. Se mantienen las 73 pruebas previas; la que exigía que no existiera /reservas/ se actualizó para comprobar su autenticación, de acuerdo con el alcance nuevo.
- Cobertura: autenticación, permisos, servicios, perfiles, horarios, bloqueos, disponibilidad, reservas, retenciones, expiración, transiciones, cancelaciones, idempotencia, pagos simulados y errores de conexión.
- Concurrencia: dos clientes por horario, doble confirmación, expiración frente a nueva reserva, cancelación repetida y dos verificaciones de pago, además de las pruebas anteriores de exclusión PostgreSQL.
- check, check --database default y pip check: correctos.
- makemigrations --check --dry-run: sin cambios pendientes. Migraciones aplicadas en PostgreSQL conservando los datos.
- Tailwind compilado. PostgreSQL healthy y publicado solo en localhost.
- Lanzador scripts/iniciar.py comprobado: Django, Tailwind y procesador activos. El recorrido HTTP se repitió con ese arranque.

## Revisión 2: código y documentación

Se revisaron permisos, plazos de captura, reintentos, pagos tardíos y cierre de pagos cancelados. Se eliminaron rutas personales y referencias obsoletas y se simplificaron README y los documentos. El diff y los archivos preparados para publicación se comprueban para excluir secretos, .env, copias locales y dependencias temporales.

## Revisión 3: recorrido integral

Por HTTP contra el servidor real se comprobaron inicio, registro, logout/login, servicios, selección de barbero, disponibilidad, resumen, retención y creación REST de una orden Sandbox. Se verificaron reserva ajena 404, gestión no autorizada 403, cancelación, liberación del horario y carga del CSS. La cuenta temporal de este recorrido quedó desactivada y su reserva cancelada.

## Integración real de PayPal Sandbox

Las credenciales locales autenticaron mediante OAuth y permitieron crear una orden REST. El usuario aprobó con su cuenta compradora Sandbox. El procesador consultó la orden, capturó y confirmó la cita. Una consulta independiente a la API oficial comprobó **una captura COMPLETED de USD 8,00**; PostgreSQL registró pago COMPLETADO, cita CONFIRMADA y ocupación activa.

La página de confirmación respondió 200. Repetir la verificación por POST y desde el servicio no generó otra captura ni otro evento de confirmación. No se usaron endpoints Live. Las respuestas simuladas de la suite son evidencia adicional y no se confunden con esta transacción real de Sandbox.

## Límites

No hubo navegador disponible para inspección visual o comprobación móvil interactiva. Se comprobaron HTML, rutas y CSS por HTTP; la aprobación en PayPal la realizó el usuario. Se recomienda una revisión visual manual antes de presentar.

Una captura incierta conserva su intervalo hasta conocer el resultado; si PayPal no responde, la conciliación o devolución sigue pendiente y se reintenta. Los comprobantes, la cancelación de citas pagadas y los paneles avanzados de fases posteriores no forman parte de esta entrega.
