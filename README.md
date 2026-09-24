# Sistema web de reservas para barbería

Proyecto final de Desarrollo de Software VIII.

Integrantes: Guillermo Cuevas, Jorge Jiménez, Jonathán Martínez, Luis González, Marlenis Quintero.

## Tecnologías

- Python 3.13 y Django 5.2
- PostgreSQL
- Tailwind CSS (django-tailwind, plantilla Standalone, no requiere Node.js)
- PayPal Sandbox (fases posteriores)

## Estado del proyecto

**Fase 1 – Base y seguridad (completada)**

- M02 Autenticación: registro, inicio y cierre de sesión, recuperación de contraseña.
- M01 Roles y permisos: Cliente, Barbero y Administrador, con paneles propios y bloqueo (403) ante un rol incorrecto.
- M04 Servicios con duración y precio.
- Pruebas automatizadas y datos de demostración.

## Instalación

1. Clonar el repositorio y entrar a la carpeta del proyecto (donde está `manage.py`).
2. Crear y activar el entorno virtual:
```
   python -m venv venv
   venv\Scripts\activate
```
   En PowerShell, si bloquea la activación: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`.
3. Instalar dependencias:
```
   pip install -r requirements.txt
```
4. Copiar `.env.example` como `.env` y llenar los valores (clave secreta y datos de PostgreSQL).
5. Crear en PostgreSQL una base de datos vacía con el nombre indicado en `DB_NAME`.
6. Aplicar migraciones:
```
   python manage.py migrate
```
7. Cargar los datos de demostración:
```
   python manage.py crear_datos_demo
```

## Ejecución

Se necesitan dos terminales, ambas con el entorno virtual activo:

```
python manage.py runserver
python manage.py tailwind start
```

Abrir http://127.0.0.1:8000/

## Usuarios de demostración

Contraseña de todos: `Demo12345!`

| Usuario | Rol |
|---|---|
| cliente_demo | Cliente |
| barbero_demo | Barbero |
| admin_demo | Administrador |

## Pruebas

```
python manage.py test
```

## Estructura

- `config/`: configuración del proyecto.
- `usuarios/`: modelo de usuario, autenticación, roles y permisos.
- `servicios/`: servicios con precio y duración.
- `theme/`: configuración de Tailwind.
- `templates/`: plantillas HTML.