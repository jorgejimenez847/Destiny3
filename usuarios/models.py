from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class UsuarioManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("rol", "ADMIN")
        if extra_fields["rol"] != "ADMIN":
            raise ValueError("Un superusuario debe tener rol Administrador.")
        return super().create_superuser(username, email, password, **extra_fields)


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        CLIENTE = "CLIENTE", "Cliente"
        BARBERO = "BARBERO", "Barbero"
        ADMIN = "ADMIN", "Administrador"

    rol = models.CharField(
        max_length=10,
        choices=Rol.choices,
        default=Rol.CLIENTE,
    )
    telefono = models.CharField(max_length=20, blank=True)

    objects = UsuarioManager()

    def es_cliente(self):
        return self.rol == self.Rol.CLIENTE

    def es_barbero(self):
        return self.rol == self.Rol.BARBERO

    def es_admin(self):
        return self.rol == self.Rol.ADMIN

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_rol_display()})"