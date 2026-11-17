from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import ListView
from usuarios.permisos import rol_requerido
from .forms import FiltroServiciosForm, ServicioForm

from .models import Servicio


class ServicioListView(ListView):
    model = Servicio
    template_name = "servicios/lista.html"
    context_object_name = "servicios"

    def get_queryset(self):
        return Servicio.objects.filter(activo=True)


@rol_requerido("ADMIN")
@require_GET
def gestion(request):
    form = FiltroServiciosForm(request.GET)
    consulta = Servicio.objects.all()
    if form.is_valid():
        datos = form.cleaned_data
        if datos["q"]:
            consulta = consulta.filter(
                Q(nombre__icontains=datos["q"]) | Q(descripcion__icontains=datos["q"])
            )
        if datos["activo"]:
            consulta = consulta.filter(activo=datos["activo"] == "si")
    else:
        consulta = consulta.none()
    pagina = Paginator(consulta, 20).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)
    return render(
        request,
        "servicios/gestion.html",
        {
            "servicios": pagina,
            "pagina": pagina,
            "filtros": form,
            "parametros": parametros.urlencode(),
        },
    )


@rol_requerido("ADMIN")
@require_http_methods(["GET", "POST"])
def editar(request, pk=None):
    servicio = get_object_or_404(Servicio, pk=pk) if pk else Servicio()
    form = ServicioForm(
        request.POST if request.method == "POST" else None, instance=servicio
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Servicio guardado correctamente.")
        return redirect("servicios:gestion")
    return render(
        request,
        "gestion/form.html",
        {
            "form": form,
            "titulo": "Editar servicio" if pk else "Nuevo servicio",
            "volver": "servicios:gestion",
        },
    )
