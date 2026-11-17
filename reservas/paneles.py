from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from usuarios.permisos import rol_requerido
from .consultas import citas_autorizadas, contexto_agenda
from .forms import EstadoCitaForm
from .servicios import cambiar_estado_operativo, estados_operativos_permitidos


@rol_requerido("ADMIN")
@require_GET
def gestion(request):
    return render(
        request, "reservas/gestion.html", contexto_agenda(request.user, request.GET)
    )


def _contexto(cita, actor, form=None):
    opciones = estados_operativos_permitidos(cita, actor)
    if form is not None:
        form.fields["estado"].choices = opciones
    return {
        "cita": cita,
        "pago": cita.pago,
        "opciones": opciones,
        "form": form if form is not None else EstadoCitaForm(opciones=opciones),
    }


@rol_requerido("ADMIN", "BARBERO")
@require_GET
def detalle(request, pk):
    cita = get_object_or_404(citas_autorizadas(request.user), pk=pk)
    return render(
        request, "reservas/gestion_detalle.html", _contexto(cita, request.user)
    )


@rol_requerido("ADMIN", "BARBERO")
@require_POST
def estado(request, pk):
    cita = get_object_or_404(citas_autorizadas(request.user), pk=pk)
    form = EstadoCitaForm(
        request.POST, opciones=estados_operativos_permitidos(cita, request.user)
    )
    if form.is_valid():
        try:
            cambiar_estado_operativo(cita.pk, form.cleaned_data["estado"], request.user)
        except ValidationError as exc:
            cita.refresh_from_db()
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, "Estado de la cita actualizado.")
            return redirect("reservas:gestion_detalle", pk=cita.pk)
    return render(
        request,
        "reservas/gestion_detalle.html",
        _contexto(cita, request.user, form),
        status=400,
    )
