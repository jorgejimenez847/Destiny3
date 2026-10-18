# Validación de la entrega · 18 de octubre de 2026

Entorno: Anaconda dsw8408, Python 3.12.13, Django 5.2.17, PostgreSQL 16 en Docker.

- Fase 1 original: 13 pruebas aprobadas antes de desarrollar.
- Fase 2: 37 pruebas aprobadas, incluidas las originales.
- Entrega final: **73 pruebas aprobadas** con `python manage.py test --noinput`, en PostgreSQL (15.759 s en la última ejecución).
- `python -m pip check`: sin dependencias rotas.
- `python manage.py check`: sin incidencias.
- `python manage.py check --database default`: sin incidencias tras recrear el contenedor con el mismo volumen.
- `python manage.py makemigrations --check --dry-run`: sin cambios pendientes.
- `showmigrations --plan`: todas las migraciones aplicadas, incluida btree_gist/exclusión de ocupaciones.
- `python manage.py tailwind build`: compilación correcta con Tailwind 4.3.0. Watcher iniciado.
- Docker Compose validado; PostgreSQL healthy y publicado únicamente en 127.0.0.1:5432.

## Verificación de las páginas reales

Consultas HTTP al servidor Django en 127.0.0.1:8000:

- Inicio, catálogo, login, registro y disponibilidad: 200.
- CSS compilado: 200, con clases de la paleta zinc/ámbar.
- Disponibilidad demo del 19/10/2026: calculada correctamente; primera franja a las 09:30.
- Día completo bloqueado del 20/10/2026: estado sin disponibilidad.
- Gestión con sesión de administrador: 200; con sesiones de barbero y cliente: 403.
- Perfil propio del barbero: 200. Las sesiones temporales de esta verificación se cerraron.

La herramienta de navegador informó que no hay navegador disponible. No se afirma revisión visual, ni verificación interactiva a anchuras móviles. La estructura responsive y los controles se conservaron y verificaron por código/HTTP; queda pendiente inspección visual manual antes de presentar.

## Concurrencia

Cuatro pruebas con conexiones independientes comprueban: ocupaciones simultáneas mediante el modelo, escrituras directas bajo exclusión PostgreSQL, horarios superpuestos y bloqueo frente a ocupación. Solo una operación incompatible se persiste. En SQL directo sin bloqueo puede abortarse una transacción por deadlock; la prueba verifica ese caso concreto, sin ignorar otros errores. La escritura normal ordena las operaciones bloqueando el perfil del barbero.

## Límites de alcance

No se implementaron reserva completa, pagos, bloqueo temporal de pago ni estados de citas: corresponden a Fase 4. Los intervalos ocupados son la estructura mínima necesaria para M08 y los ejemplos de demostración.

No se cambiaron contraseñas de usuarios existentes. La SECRET_KEY local se reforzó con un valor aleatorio y se conserva exclusivamente en .env; las sesiones previas pueden requerir iniciar sesión nuevamente.
