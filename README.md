# Destiny 3

Sistema web de reservas para barbería · Desarrollo de Software VIII.

Equipo: Guillermo Cuevas, Jorge Jiménez, Jonathán Martínez, Luis González y Marlenis Quintero.

Python 3.12/3.13, Django 5.2, PostgreSQL 16 y Tailwind CSS Standalone.

## Funcionalidades

- Fase 1: autenticación, recuperación de contraseña, roles y servicios con duración y precio.
- Fase 2: perfiles de barberos, servicios asignados, turnos, descansos, ausencias y días bloqueados.
- Fase 3: disponibilidad calculada y prevención de solapamientos en servidor y PostgreSQL.
- Fase 4: selección, resumen, retención temporal, pago PayPal Sandbox, confirmación y transiciones de estado.

La administración de perfiles y horarios requiere rol Administrador. Cada barbero consulta sus propios datos. Las reservas y sus pagos solo son accesibles para el cliente propietario. Los paneles avanzados, la cancelación de citas pagadas, los comprobantes y las demás funciones de las fases 5 y 6 quedan fuera de esta entrega.

## Instalación

Ejecuta desde la carpeta que contiene `manage.py`:

```powershell
conda activate dsw8408
python -m pip install -r requirements.txt
python -m pip check
```

Si no existe el entorno, créalo con `conda create -n dsw8408 python=3.12 pip`. También puedes usar un entorno virtual con Python 3.12 o 3.13.

Para una instalación nueva:

```powershell
python scripts/preparar_entorno.py
```

El script genera claves aleatorias en `.env` y nunca reemplaza un archivo existente. Conserva tus credenciales locales. Usa `.env.example` como referencia y no subas `.env` a Git. Para desarrollo se utiliza `DJANGO_DEBUG=True`; el valor por defecto es False.

### PostgreSQL y migraciones

Abre Docker Desktop y espera a que el motor esté disponible:

```powershell
docker compose up -d --wait db
python manage.py migrate
python manage.py check --database default
```

Docker utiliza DB_NAME, DB_USER, DB_PASSWORD y DB_PORT de `.env`, publica PostgreSQL solo en localhost y conserva los datos en un volumen. Django se ejecuta fuera del contenedor, con DB_HOST=localhost. Si utilizas un servidor propio, ajusta estas variables.

La migración de intervalos utiliza `btree_gist`. En un servidor administrado, el administrador debe habilitar la extensión si tu usuario no tiene permisos. Las pruebas necesitan permiso CREATEDB y usan una base `test_<DB_NAME>`, separada de la principal.

Cambiar las credenciales de `.env` no modifica un volumen PostgreSQL ya inicializado. Conserva las credenciales existentes; no borres el volumen para resolver errores de conexión.

### PayPal Sandbox

Configura localmente PAYPAL_MODE=sandbox, PAYPAL_CLIENT_ID y PAYPAL_CLIENT_SECRET. PAYPAL_RETURN_BASE debe coincidir con la dirección del sitio; para desarrollo es `http://127.0.0.1:8000`. El ejemplo versionado solo contiene los nombres de estas variables. No hay endpoints Live.

Los precios del catálogo se cobran en USD, con equivalencia numérica B/. 1,00 = USD 1,00. El importe se guarda al confirmar el resumen y se comprueba de nuevo en la respuesta del servidor de PayPal. La cuenta compradora debe ser **Personal Sandbox**, distinta de la cuenta Business asociada a la aplicación. No se mueve dinero real.

### Datos demo y estilos

```powershell
python manage.py crear_datos_demo
python manage.py crear_agenda_demo
python manage.py tailwind build
```

Se crean cliente_demo, barbero_demo y admin_demo si no existen. Las cuentas nuevas usan DEMO_PASSWORD del archivo local o una contraseña introducida de forma oculta. Los comandos no reemplazan contraseñas ni agendas existentes. Si olvidaste una contraseña local, elige otra con `python manage.py changepassword <usuario>`.

La agenda demo añade turnos de lunes a sábado con descanso, una ausencia parcial, un día completo bloqueado y un intervalo ocupado. El comando indica la fecha; puedes elegir otra con `--fecha AAAA-MM-DD`. Tailwind no requiere Node.js y puede descargar su ejecutable oficial en la primera compilación.

## Iniciar el proyecto

```powershell
conda activate dsw8408
python scripts/iniciar.py
```

El lanzador ejecuta Django, Tailwind y el procesador de retenciones con el mismo entorno. Abre http://127.0.0.1:8000/. Ctrl+C detiene los tres. Si alguno se detiene, el lanzador cierra la sesión para evitar reservas sin procesador.

También puedes ejecutar cada comando en una terminal distinta:

```powershell
python manage.py runserver
python manage.py tailwind start
python manage.py procesar_retenciones
```

**El procesador debe permanecer activo.** Libera retenciones vencidas y consulta pagos cada pocos segundos, aunque nadie visite el sitio. Un latido controla su disponibilidad; no se aceptan reservas nuevas si lleva más de 90 segundos detenido. Para ejecutar un ciclo manual: `python manage.py procesar_retenciones --una-vez`.

## Reservas y pagos

1. Inicia sesión como Cliente y abre Disponibilidad.
2. Selecciona servicio, barbero compatible y fecha; elige un horario.
3. Revisa el resumen y confirma. El servidor vuelve a comprobar la disponibilidad y retiene el intervalo durante un máximo de diez minutos.
4. Abre PayPal Sandbox y aprueba con la cuenta compradora ficticia.
5. El procesador verifica la orden, captura el pago y confirma la cita. Al volver al sitio también puedes pulsar Verificar pago. Mis reservas permite consultar el resultado y la actividad de esa cita.

La disponibilidad descuenta duración real, turnos, descansos, bloqueos y ocupaciones activas. Dos intervalos adyacentes son válidos; los intervalos superpuestos se rechazan mediante transacciones y una exclusión GiST de PostgreSQL.

Cancelar antes de la captura o dejar vencer la retención libera el horario. Si una captura queda incierta por una desconexión, el intervalo permanece protegido hasta conocer el resultado; no se cobra otra vez ni se libera un posible pago. Los reintentos utilizan los mismos identificadores de PayPal. Un pago tardío que no pueda confirmar su cita se devuelve en Sandbox, sin afectar una reserva nueva. Si PayPal está caído, la verificación o devolución queda pendiente y se reintenta.

Los estados de atención están definidos con transiciones controladas para Administrador o barbero asignado; la interfaz completa de agenda de atención se desarrollará en Fase 6. La recuperación de contraseña usa correo por consola en desarrollo.

## Pruebas y diagnóstico

Última validación: 126 pruebas aprobadas en PostgreSQL y un pago completo verificado en PayPal Sandbox. La revisión visual en navegador y móvil queda pendiente.

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
python manage.py tailwind build
```

- Dependencias ausentes: activa el entorno correcto e instala con `python -m pip install -r requirements.txt`.
- Error dockerDesktopLinuxEngine: abre Docker Desktop y espera a que termine de iniciar.
- Error PostgreSQL: revisa `.env`, puerto, credenciales del volumen y `docker compose ps`.
- Página sin estilos: compila Tailwind y comprueba `/static/css/dist/styles.css`.
- Barbero sin disponibilidad: revisa rol, usuario/perfil activos, servicios asignados, turnos y bloqueos.
- Reservas pausadas: inicia `procesar_retenciones`; comprueba su terminal y conectividad con PostgreSQL.

Referencias de integración: [Orders v2](https://developer.paypal.com/api/orders/v2/), [OAuth](https://developer.paypal.com/api/rest/authentication/) e [idempotencia](https://developer.paypal.com/api/rest/reference/idempotency/).
