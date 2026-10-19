import uuid
from datetime import timedelta
from decimal import Decimal
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils.dateparse import parse_datetime
from barberos.disponibilidad import validar_intervalo
from barberos.models import PerfilBarbero
from servicios.models import Servicio
from usuarios.permisos import rol_requerido
from .forms import ConfirmacionForm, SeleccionForm
from .models import Cita
from .servicios import (
    cancelar_cita,
    crear_cita,
    expirar_retenciones,
    preparar_orden,
    procesar_pago,
)

SALT = "reservas.seleccion"


def _propia(request, pk):
    return get_object_or_404(
        Cita.objects.select_related("pago", "ocupacion"), pk=pk, cliente=request.user
    )


@rol_requerido("CLIENTE")
@require_GET
def lista(request):
    citas = Cita.objects.filter(cliente=request.user).select_related("pago")[:20]
    return render(request, "reservas/lista.html", {"citas": citas})


@rol_requerido("CLIENTE")
@require_GET
def resumen(request):
    form = SeleccionForm(request.GET)
    if not form.is_valid():
        messages.error(request, "Selecciona un horario válido desde Disponibilidad.")
        return redirect("barberos:disponibilidad")
    servicio = get_object_or_404(Servicio, pk=form.cleaned_data["servicio"])
    barbero = get_object_or_404(
        PerfilBarbero.objects.select_related("usuario"), pk=form.cleaned_data["barbero"]
    )
    inicio = form.cleaned_data["inicio"]
    fin = inicio + timedelta(minutes=servicio.duracion_minutos)
    expirar_retenciones(barbero.pk)
    try:
        validar_intervalo(barbero, servicio, inicio, fin)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("barberos:disponibilidad")
    seleccion = signing.dumps(
        {
            "cliente": request.user.pk,
            "servicio": servicio.pk,
            "barbero": barbero.pk,
            "inicio": inicio.isoformat(),
            "precio": str(servicio.precio),
            "duracion": servicio.duracion_minutos,
            "solicitud": str(uuid.uuid4()),
        },
        salt=SALT,
    )
    return render(
        request,
        "reservas/resumen.html",
        {
            "servicio": servicio,
            "barbero": barbero,
            "inicio": inicio,
            "fin": fin,
            "form": ConfirmacionForm(initial={"seleccion": seleccion}),
        },
    )


@rol_requerido("CLIENTE")
@require_POST
def confirmar(request):
    form = ConfirmacionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Falta la selección de reserva.")
    try:
        datos = signing.loads(form.cleaned_data["seleccion"], salt=SALT, max_age=600)
        if datos["cliente"] != request.user.pk:
            return HttpResponseBadRequest("La selección no pertenece a esta sesión.")
        cita = crear_cita(
            request.user,
            datos["barbero"],
            datos["servicio"],
            parse_datetime(datos["inicio"]),
            uuid.UUID(datos["solicitud"]),
            Decimal(datos["precio"]),
            duracion_esperada=datos["duracion"],
        )
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        messages.error(
            request,
            "La selección venció o no es válida. Consulta los horarios nuevamente.",
        )
        return redirect("barberos:disponibilidad")
    except (ValidationError, IntegrityError) as exc:
        texto = (
            "; ".join(exc.messages)
            if isinstance(exc, ValidationError)
            else "El horario acaba de ser ocupado. Selecciona otro."
        )
        messages.error(request, texto)
        return redirect("barberos:disponibilidad")
    if cita.estado == Cita.Estado.PENDIENTE:
        messages.success(
            request, "Horario retenido. Completa el pago Sandbox antes de que expire."
        )
    else:
        messages.info(
            request,
            "Esta selección ya fue procesada. Consulta el estado de la reserva.",
        )
    return redirect("reservas:detalle", pk=cita.pk)


@rol_requerido("CLIENTE")
@require_GET
def detalle(request, pk):
    cita = _propia(request, pk)
    expirar_retenciones(cita.barbero_id)
    cita.refresh_from_db()
    return render(request, "reservas/detalle.html", {"cita": cita, "pago": cita.pago})


@rol_requerido("CLIENTE")
@require_POST
def pagar(request, pk):
    _propia(request, pk)
    try:
        return redirect(preparar_orden(pk, request.user))
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("reservas:detalle", pk=pk)


@rol_requerido("CLIENTE")
@require_GET
def retorno(request, pk):
    cita = _propia(request, pk)
    if request.GET.get("token") != cita.pago.orden_id or not cita.pago.orden_id:
        return HttpResponseBadRequest(
            "La referencia de PayPal no coincide con esta reserva."
        )
    messages.info(
        request,
        "La aprobación se comprobará en el servidor. Puedes verificar el pago ahora.",
    )
    return redirect("reservas:detalle", pk=pk)


@rol_requerido("CLIENTE")
@require_POST
def verificar(request, pk):
    _propia(request, pk)
    procesar_pago(pk)
    return redirect("reservas:detalle", pk=pk)


@rol_requerido("CLIENTE")
@require_GET
def cancelar_pago(request, pk):
    cita = _propia(request, pk)
    return render(request, "reservas/cancelar.html", {"cita": cita})


@rol_requerido("CLIENTE")
@require_POST
def cancelar(request, pk):
    _propia(request, pk)
    try:
        cancelar_cita(pk, request.user)
        messages.success(
            request, "La reserva pendiente se canceló y su horario quedó libre."
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("reservas:detalle", pk=pk)
