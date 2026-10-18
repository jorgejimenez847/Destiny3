"""Crea configuración local segura. Nunca reemplaza un .env existente."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env ya existe: se conserva. Revisa .env.example para las opciones nuevas.")
values = (root / ".env.example").read_text(encoding="utf-8")
for key in ("SECRET_KEY", "DB_PASSWORD", "DEMO_PASSWORD"):
    values = values.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(48)}\n")
with target.open("x", encoding="utf-8") as stream:
    stream.write(values)
print(".env creado con claves aleatorias. No lo compartas ni lo subas a Git.")
