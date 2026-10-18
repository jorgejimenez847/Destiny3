# Destiny 3 · Sistema web de reservas para barbería

Desarrollo de Software VIII. Integrantes: Guillermo Cuevas, Jorge Jiménez, Jonathán Martínez, Luis González y Marlenis Quintero.

Python 3.12/3.13 · Django 5.2 · PostgreSQL 16 · Tailwind CSS Standalone.

## Alcance de esta versión

- Fase 1: registro, login/logout, recuperación de contraseña, roles y catálogo de servicios con duración y precio positivos.
- Fase 2: perfiles de barberos, especialidad, servicios, estado, turnos semanales, descansos, ausencias, vacaciones y días completos no disponibles.
- Fase 3: consulta de disponibilidad calculada y prevención de superposiciones en Python y PostgreSQL, incluidas escrituras concurrentes.
- Reserva completa, bloqueo durante pago, PayPal y estados de cita corresponden a la **Fase 4** y no están implementados.

## Instalación en Windows / Anaconda

Abre una terminal en la raíz que contiene `manage.py` y `.git`. En este equipo está dentro de OneDrive, en `DESARROLLO DE SOFTWARE VIII/Destiny3/Destiny3`; la carpeta `DesarrolloSoftwareVIII/portal_dsw` es otro proyecto.

```powershell
conda activate dsw8408
python --version
python -m pip install -r requirements.txt
python -m pip check
```

Si no existe el entorno: `conda create -n dsw8408 python=3.12 pip`, seguido de su activación. También se admite un entorno virtual con Python 3.12 o 3.13; no hace falta crearlo si usas Anaconda.

Genera configuración local **solo para una instalación nueva**:

```powershell
python scripts/preparar_entorno.py
```

El script crea `.env` con claves aleatorias y no reemplaza archivos existentes. Revisa los valores con `.env.example` como referencia. No subas `.env` a Git. Si ya existe, conserva sus credenciales y añade `DJANGO_DEBUG=True` para desarrollo. Se evita la variable genérica `DEBUG`, que en Windows puede tener valores ajenos a Django. El valor por defecto de `DJANGO_DEBUG` es False; no hay clave secreta fija ni cambio automático de motor de BD.

### PostgreSQL

Inicia Docker Desktop, espera a que el motor esté operativo y ejecuta:

```powershell
docker compose up -d --wait db
docker compose ps
python manage.py check
python manage.py migrate
python manage.py showmigrations
```

`docker-compose.yml` toma DB_NAME, DB_USER, DB_PASSWORD y DB_PORT desde `.env`, conserva datos en un volumen y publica el puerto solo en localhost. DB_HOST debe ser `localhost` al ejecutar Django en Windows. Un servidor PostgreSQL propio también sirve si ajustas `.env`.

La migración de M08 habilita `btree_gist`. En Docker el usuario inicial puede crear esta extensión. En PostgreSQL administrado, pide al administrador habilitarla si el usuario de migraciones carece de permisos. Para ejecutar pruebas el usuario también necesita permiso CREATEDB; Django crea y destruye una base `test_<DB_NAME>`, no la principal.

**Importante:** cambiar DB_USER/DB_PASSWORD en `.env` no cambia las credenciales de un volumen ya inicializado. Conserva las credenciales existentes o solicita un cambio controlado; no borres el volumen para resolverlo.

### Tailwind

```powershell
python manage.py tailwind build
```

El primer build puede descargar el ejecutable oficial de Tailwind. No se requiere Node.js. El CSS compilado se ignora en Git: recompílalo después de clonar y después de modificar templates. Sin este paso el HTML puede mostrarse sin estilo.

## Datos de demostración

```powershell
python manage.py crear_datos_demo
python manage.py crear_agenda_demo
```

`crear_datos_demo` crea `cliente_demo`, `barbero_demo` y `admin_demo` y cuatro servicios si no existen. Para usuarios nuevos usa DEMO_PASSWORD desde `.env`, o pide una clave mediante entrada oculta. No muestra la contraseña ni cambia cuentas existentes. Si olvidaste una contraseña existente, puedes elegir otra mediante `python manage.py changepassword admin_demo` (acción manual).

`crear_agenda_demo` crea el perfil del barbero demo y sus turnos de lunes a sábado, 09:00–17:00 con descanso 12:00–13:00, solo cuando crea el perfil. Añade ejemplos para el siguiente día de lunes a sábado: 09:00–09:30 ocupado, 10:00–11:00 ausente y el día siguiente completo no disponible. Son intervalos reales persistidos; no horas disponibles precargadas. El comando no reemplaza agendas ni ocupaciones existentes y explica si algún ejemplo no pudo añadirse. Usa `--fecha AAAA-MM-DD` para elegir una fecha futura.

## Iniciar el sitio

Dos terminales en la raíz del proyecto, ambas con `conda activate dsw8408`:

```powershell
# Terminal 1
python manage.py runserver
```

```powershell
# Terminal 2
python manage.py tailwind start
```

Abre http://127.0.0.1:8000/. Con el CSS ya compilado, el watcher no es obligatorio para una demostración sin cambios de diseño. La recuperación de contraseña usa por defecto correo por consola; el enlace se muestra en la terminal de Django. SMTP real queda como configuración posterior.

## Cómo demostrar las fases 2 y 3

1. Como visitante, abre **Disponibilidad**, selecciona Corte de cabello, el barbero demo y la fecha que indicó `crear_agenda_demo`. Verás huecos reales de 30 minutos; no se ofrecen intervalos que crucen la ausencia ni el descanso. La primera franja comienza a las 09:30 por la ocupación de 09:00.
2. Consulta el día siguiente: aparecerá el estado sin disponibilidad. Prueba un servicio de 50 minutos: cambiarán los horarios que caben dentro de cada tramo.
3. Inicia sesión como administrador y abre **Gestionar barberos**. Edita especialidad, servicios y estado; añade/edita/elimina turnos y bloqueos, con confirmación antes de eliminar.
4. Intenta un turno invertido, un descanso fuera del turno o turnos superpuestos. El formulario muestra errores y no guarda datos inválidos.
5. Añade un bloqueo en un hueco libre y vuelve a consultar disponibilidad. No podrás añadirlo sobre un intervalo ocupado ni reducir/eliminar un turno que ampare ocupaciones futuras.
6. Inicia sesión como barbero: **Mi perfil y horario** es de consulta. Intentar editar o acceder al perfil de otro barbero responde 403. El cliente tampoco puede administrar agendas.
7. Las pruebas de concurrencia muestran que solo una de dos escrituras simultáneas puede persistirse. No hay botón de reservar o pagar: consultar no aparta horarios.

Para crear otro barbero: administrador Django → Usuarios → Añadir → rol Barbero; después **Gestionar barberos → Nuevo perfil**, asigna servicios y añade turnos. La interfaz propia exige rol ADMIN; el administrador Django además exige cuenta staff y permisos.

## Reglas de disponibilidad e integridad

- Zona horaria: America/Panama. Turnos dentro del mismo día, precisión de minutos; para un descanso adicional puedes dividir el día en varios turnos no superpuestos.
- Solo barberos/usuarios/servicios activos y parejas barbero-servicio asignadas ofrecen disponibilidad.
- Los candidatos se generan cada 15 minutos desde cada tramo libre. Este paso organiza las alternativas; la duración real proviene del servicio. La validación backend acepta cualquier inicio válido, sin depender de esa grilla.
- Intervalos semiabiertos `[inicio, fin)`: dos intervalos adyacentes son válidos. No se puede cruzar un descanso, bloqueo, hueco entre turnos o fin de jornada.
- Los días sin turnos, los pasados y los bloqueados no ofrecen horarios. El día actual excluye horas ya transcurridas.
- `Ocupacion` es una estructura mínima de M08, sin cliente, pago ni estados de reserva. Sus escrituras bloquean el perfil dentro de una transacción, vuelven a validar y tienen una exclusión GiST en PostgreSQL.
- La Fase 4 debe usar este punto de escritura para ocupaciones, mantener el bloqueo transaccional y gestionar la vida útil de las reservas. Consultar disponibilidad es una instantánea y no garantiza un hueco hasta su escritura validada.
- SQL directo/bulk que omita el bloqueo sigue protegido contra solapamientos por PostgreSQL; una transacción puede abortar por conflicto/deadlock. El flujo del modelo evita esta competencia mediante bloqueo ordenado. No se deben usar actualizaciones masivas para saltarse reglas de agenda.

## Pruebas

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
```

Pruebas sobre PostgreSQL: autenticación y roles, servicios, perfiles, horarios, descansos, bloqueos, días completos, formularios/permisos por GET y POST, disponibilidad y duraciones, fronteras de intervalos, exclusión en BD y dos transacciones simultáneas. Los datos demo se prueban dos veces para comprobar que no se duplican ni cambian contraseñas.

Revisión de los diez hallazgos recibidos: [docs/AUDITORIA.md](docs/AUDITORIA.md). Diseño y recorrido de presentación: [docs/DEMOSTRACION.md](docs/DEMOSTRACION.md).

## Solución de problemas

- `No module named decouple/widget_tweaks/psycopg2`: confirma `conda activate dsw8408`, revisa `where.exe python` e instala con `python -m pip install -r requirements.txt`.
- Error de tubería `dockerDesktopLinuxEngine`: abre Docker Desktop y espera al motor Linux. No requiere sustituir PostgreSQL por SQLite.
- Error de conexión/contraseña PostgreSQL: revisa `.env`, puerto y `docker compose ps`; no compartas ni imprimas credenciales al pedir ayuda.
- `SECRET_KEY` o variables DB ausentes: genera `.env` solo si no existe o completa el archivo local con `.env.example` como guía.
- `Invalid truth value: release`: usa esta versión y `DJANGO_DEBUG=True` en `.env`.
- Página sin estilos: ejecuta `python manage.py tailwind build` y verifica `/static/css/dist/styles.css`.
- Un barbero no aparece: comprueba rol, usuario activo, perfil activo y servicio asignado; después configura su horario.
