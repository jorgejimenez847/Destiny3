from django.contrib import admin
from .models import PerfilBarbero

@admin.register(PerfilBarbero)
class PerfilBarberoAdmin(admin.ModelAdmin):
    list_display = ["usuario", "especialidad", "activo"]
    list_filter = ["activo", "servicios"]
    search_fields = ["usuario__username", "usuario__first_name", "especialidad"]
    filter_horizontal = ["servicios"]
