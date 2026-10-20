from django.contrib import admin
from usuarios.permisos import es_administrador
from .models import PerfilBarbero

@admin.register(PerfilBarbero)
class PerfilBarberoAdmin(admin.ModelAdmin):
    list_display = ["usuario", "especialidad", "activo"]
    list_filter = ["activo", "servicios"]
    search_fields = ["usuario__username", "usuario__first_name", "especialidad"]
    filter_horizontal = ["servicios"]

    def has_module_permission(self, request):
        return es_administrador(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return es_administrador(request.user) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return es_administrador(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return es_administrador(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False  # Se desactivan perfiles para conservar referencias y agenda.
