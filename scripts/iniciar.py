"""Inicia Django, Tailwind y el procesador con el mismo Python activo."""

from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys
import time


def preparar(root):
    faltantes = [
        paquete for paquete in ("django", "tailwind", "decouple", "widget_tweaks", "psycopg2")
        if find_spec(paquete) is None
    ]
    if faltantes:
        raise SystemExit(
            "Faltan dependencias: " + ", ".join(faltantes)
            + ". Activa tu entorno y ejecuta: python -m pip install -r requirements.txt"
        )

    def ejecutar(argumentos, mensaje):
        try:
            subprocess.run([sys.executable, "manage.py", *argumentos], cwd=root, check=True)
        except (subprocess.CalledProcessError, OSError) as error:
            raise SystemExit(mensaje) from error

    ejecutar(
        ["check", "--database", "default"],
        "No se pudo comprobar Django. Revisa el error anterior y tu .env. "
        "Para una instalación nueva: python scripts/preparar_entorno.py",
    )
    ejecutar(
        ["migrate", "--check"],
        "No se pudo comprobar la base de datos o hay migraciones pendientes. "
        "Revisa PostgreSQL y .env; con Docker: docker compose up -d --wait db. "
        "Después ejecuta: python manage.py migrate",
    )
    css = root / "theme/static/css/dist/styles.css"
    if not css.is_file() or css.stat().st_size == 0:
        print("Faltan los estilos compilados; preparando Tailwind...", flush=True)
        mensaje = (
            "No se generaron los estilos. Ejecuta: python manage.py tailwind build. "
            "Comprueba las dependencias y la conexión a Internet para descargar "
            "el ejecutable de Tailwind en la primera compilación."
        )
        ejecutar(["tailwind", "build"], mensaje)
        if not css.is_file() or css.stat().st_size == 0:
            raise SystemExit(mensaje)


def main():
    root = Path(__file__).resolve().parent.parent
    procesos = []
    try:
        preparar(root)
        for argumentos in [
            ["procesar_retenciones"],
            ["tailwind", "start"],
            ["runserver", "127.0.0.1:8000", "--noreload"],
        ]:
            procesos.append(
                subprocess.Popen([sys.executable, "manage.py", *argumentos], cwd=root)
            )
        print(
            "Destiny 3 disponible en http://127.0.0.1:8000/. Ctrl+C detiene los tres procesos.",
            flush=True,
        )
        while all(p.poll() is None for p in procesos):
            time.sleep(1)
        raise SystemExit(
            "Un proceso se detuvo; se cierra la sesión para evitar reservas sin procesador."
        )
    except KeyboardInterrupt:
        pass
    except OSError as error:
        raise SystemExit(f"No se pudo iniciar un proceso: {error}") from error
    finally:
        for proceso in procesos:
            if proceso.poll() is None:
                proceso.terminate()
        for proceso in procesos:
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()
                proceso.wait()


if __name__ == "__main__":
    main()
