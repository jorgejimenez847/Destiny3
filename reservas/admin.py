from django.contrib import admin
from .models import Cita, EventoCita, Pago


class ConsultaAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.rol == "ADMIN" and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return request.user.rol == "ADMIN" and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Cita)
class CitaAdmin(ConsultaAdmin):
    list_display = ["id", "cliente", "barbero", "inicio", "estado"]
    list_filter = ["estado"]


admin.site.register(Pago, ConsultaAdmin)
admin.site.register(EventoCita, ConsultaAdmin)
