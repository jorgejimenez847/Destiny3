from getpass import getpass
from decouple import config
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from servicios.models import Servicio
from usuarios.models import Usuario



USUARIOS = [
    ("cliente_demo", "Carlos", "Cliente", Usuario.Rol.CLIENTE, False),
    ("barbero_demo", "Bruno", "Barbero", Usuario.Rol.BARBERO, False),
    ("admin_demo", "Ana", "Admin", Usuario.Rol.ADMIN, True),
]

SERVICIOS = [
    ("Corte de cabello", "Corte clásico o moderno.", "8.00", 30),
    ("Arreglo de barba", "Perfilado y recorte de barba.", "5.00", 20),
    ("Corte + barba", "Combo completo.", "12.00", 50),
    ("Cejas", "Perfilado de cejas.", "3.00", 10),
]


class Command(BaseCommand):
    help = "Crea usuarios (uno por rol) y servicios de demostración."

    @transaction.atomic
    def handle(self, *args, **options):
        clave_demo = config("DEMO_PASSWORD", default="") or getpass("Contraseña para nuevos usuarios demo: ")
        if len(clave_demo) < 12:
            raise CommandError("Usa una contraseña de demostración de al menos 12 caracteres.")
        for username, nombre, apellido, rol, es_admin in USUARIOS:
            usuario, creado = Usuario.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": nombre,
                    "last_name": apellido,
                    "email": f"{username}@demo.com",
                    "rol": rol,
                    "is_staff": es_admin,
                    "is_superuser": es_admin,
                },
            )
            if creado:
                usuario.set_password(clave_demo)
                usuario.save()
            self.stdout.write(f"{'Creado' if creado else 'Ya existe'}: {username} ({rol})")

        for nombre, descripcion, precio, duracion in SERVICIOS:
            _, creado = Servicio.objects.get_or_create(
                nombre=nombre,
                defaults={
                    "descripcion": descripcion,
                    "precio": precio,
                    "duracion_minutos": duracion,
                },
            )
            self.stdout.write(f"{'Creado' if creado else 'Ya existe'}: {nombre}")

        self.stdout.write(self.style.SUCCESS(
            "Datos de demostración preparados. Se conservan usuarios, contraseñas y servicios existentes."
        ))