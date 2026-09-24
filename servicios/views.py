from django.views.generic import ListView

from .models import Servicio


class ServicioListView(ListView):
    model = Servicio
    template_name = "servicios/lista.html"
    context_object_name = "servicios"

    def get_queryset(self):
        return Servicio.objects.filter(activo=True)