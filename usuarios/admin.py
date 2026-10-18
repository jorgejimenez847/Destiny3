from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Información adicional", {"fields": ("rol", "telefono")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("Información adicional", {"fields": ("rol", "telefono", "email", "first_name", "last_name")}),)
    list_display = ("username", "email", "rol", "is_staff")