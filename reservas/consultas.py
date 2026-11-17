from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from barberos.models import PerfilBarbero
from .forms import FiltroCitasForm
from .models import Cita, Pago

ESTADOS_CONFIRMADOS = (
    Cita.Estado.CONFIRMADA,
    Cita.Estado.EN_ATENCION,
    Cita.Estado.COMPLETADA,
    Cita.Estado.NO_ASISTIO,
)


def citas_autorizadas(actor):
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    consulta = Cita.objects.select_related(
        "cliente", "barbero__usuario", "pago", "ocupacion"
    ).prefetch_related("eventos__actor")
    if actor.rol == "ADMIN":
        return consulta
    if actor.rol == "BARBERO":
        return consulta.filter(barbero__usuario=actor)
    raise PermissionDenied


def contexto_agenda(actor, parametros):
    administrador = actor.rol == "ADMIN"
    datos = parametros.copy()
    if not parametros and not administrador:
        hoy = timezone.localdate().isoformat()
        datos.update({"desde": hoy, "hasta": hoy})
    form = FiltroCitasForm(datos, administrador=administrador)
    consulta = citas_autorizadas(actor)
    if form.is_valid():
        valores = form.cleaned_data
        if valores["q"]:
            q = valores["q"]
            consulta = consulta.filter(
                Q(cliente_nombre__icontains=q)
                | Q(cliente__username__icontains=q)
                | Q(servicio_nombre__icontains=q)
                | Q(barbero_nombre__icontains=q)
                | Q(barbero__usuario__username__icontains=q)
            )
        if valores["desde"]:
            consulta = consulta.filter(inicio__date__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(inicio__date__lte=valores["hasta"])
        for campo in ("estado", "servicio", "barbero"):
            if valores.get(campo):
                consulta = consulta.filter(**{campo: valores[campo]})
    else:
        consulta = consulta.none()
    pagina = Paginator(consulta.order_by("inicio", "pk"), 20).get_page(
        parametros.get("pagina")
    )
    enlaces = datos.copy()
    enlaces.pop("pagina", None)
    return {
        "filtros": form,
        "citas": pagina,
        "pagina": pagina,
        "parametros": enlaces.urlencode(),
        "administrador": administrador,
    }


def resumen_dashboard():
    estados = dict(Cita.objects.values_list("estado").annotate(total=Count("pk")))
    confirmadas = Cita.objects.filter(estado__in=ESTADOS_CONFIRMADOS)
    pagos = Pago.objects.filter(
        estado=Pago.Estado.COMPLETADO,
        moneda_capturada="USD",
        cita__estado__in=ESTADOS_CONFIRMADOS,
        importe_capturado=F("cita__precio"),
        captura_id__isnull=False,
        reembolso_id__isnull=True,
    ).exclude(captura_id="")
    return {
        "reservas_por_estado": [
            (etiqueta, estados.get(estado, 0))
            for estado, etiqueta in Cita.Estado.choices
        ],
        "total_reservas": sum(estados.values()),
        "importe_confirmado": pagos.aggregate(total=Sum("importe_capturado"))["total"]
        or Decimal("0.00"),
        "pagos_confirmados": pagos.count(),
        "servicios_populares": confirmadas.values("servicio_id", "servicio__nombre")
        .annotate(total=Count("pk"))
        .order_by("-total", "servicio_id")[:5],
        "citas_por_barbero": PerfilBarbero.objects.select_related("usuario")
        .annotate(total=Count("cita", filter=Q(cita__estado__in=ESTADOS_CONFIRMADOS)))
        .filter(total__gt=0)
        .order_by("-total", "pk"),
    }
