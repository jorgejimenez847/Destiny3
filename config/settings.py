from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Seguridad ---
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost").split(",")

# --- Apps instaladas ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Terceros
    "tailwind",
    "widget_tweaks",

    # Apps propias (Fase 1)
    "usuarios",
    "servicios",

    # Tema de Tailwind
    "theme",
]

# Recarga automática del navegador, solo en desarrollo
if DEBUG:
    INSTALLED_APPS += ["django_browser_reload"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    MIDDLEWARE += ["django_browser_reload.middleware.BrowserReloadMiddleware"]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Modelo de usuario personalizado ---
AUTH_USER_MODEL = "usuarios.Usuario"

# --- Base de datos: PostgreSQL ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Email (recuperación de contraseña) ---
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

# --- Redirecciones de autenticación ---
LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "usuarios:redirigir_por_rol"
LOGOUT_REDIRECT_URL = "usuarios:login"

# --- Tailwind ---
TAILWIND_APP_NAME = "theme"
INTERNAL_IPS = ["127.0.0.1"]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Panama"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"