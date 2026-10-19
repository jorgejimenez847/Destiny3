"""Inicia Django, Tailwind y el procesador con el mismo Python activo."""

from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
procesos = []
try:
    subprocess.run([sys.executable, "manage.py", "check"], cwd=root, check=True)
    for argumentos in [
        ["procesar_retenciones"],
        ["tailwind", "start"],
        ["runserver", "127.0.0.1:8000", "--noreload"],
    ]:
        procesos.append(
            subprocess.Popen([sys.executable, "manage.py", *argumentos], cwd=root)
        )
    print(
        "Destiny 3 disponible en http://127.0.0.1:8000/. Ctrl+C detiene los tres procesos."
    )
    while all(p.poll() is None for p in procesos):
        time.sleep(1)
    raise SystemExit(
        "Un proceso se detuvo; se cierra la sesión para evitar reservas sin procesador."
    )
except KeyboardInterrupt:
    pass
finally:
    for p in procesos:
        if p.poll() is None:
            p.terminate()
    for p in procesos:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
