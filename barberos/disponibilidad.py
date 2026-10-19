"""Motor reutilizable. Intervalos [inicio, fin) en hora de Panamá.

Consultar disponibilidad no ocupa ni reserva nada. Las ocupaciones se validan de
nuevo al escribir y PostgreSQL impide conflictos incluso entre transacciones.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Bloqueo, Horario, Ocupacion


@dataclass(frozen=True)
class Franja:
    inicio: datetime
    fin: datetime


def _fecha_hora(fecha, hora):
    return timezone.make_aware(
        datetime.combine(fecha, hora), timezone.get_default_timezone()
    )


def _comprobar_servicio(barbero, servicio):
    if (
        not barbero.activo
        or not barbero.usuario.is_active
        or barbero.usuario.rol != "BARBERO"
    ):
        raise ValidationError("El barbero no está disponible.")
    if not servicio.activo or servicio.duracion_minutos <= 0:
        raise ValidationError(
            "El servicio no está disponible o tiene una duración inválida."
        )
    if not barbero.servicios.filter(pk=servicio.pk).exists():
        raise ValidationError("El barbero no ofrece el servicio seleccionado.")


def tramos_laborales(barbero, fecha):
    """Turnos divididos por los descansos; ningún servicio puede cruzar un hueco."""
    tramos = []
    for h in Horario.objects.filter(barbero=barbero, dia=fecha.weekday()):
        if h.descanso_inicio:
            tramos.extend(
                [
                    Franja(
                        _fecha_hora(fecha, h.inicio),
                        _fecha_hora(fecha, h.descanso_inicio),
                    ),
                    Franja(
                        _fecha_hora(fecha, h.descanso_fin), _fecha_hora(fecha, h.fin)
                    ),
                ]
            )
        else:
            tramos.append(
                Franja(_fecha_hora(fecha, h.inicio), _fecha_hora(fecha, h.fin))
            )
    return tramos


def _restar(tramos, inicio, fin):
    libres = []
    for tramo in tramos:
        if fin <= tramo.inicio or inicio >= tramo.fin:
            libres.append(tramo)
        else:
            if tramo.inicio < inicio:
                libres.append(Franja(tramo.inicio, inicio))
            if fin < tramo.fin:
                libres.append(Franja(fin, tramo.fin))
    return libres


def calcular_disponibilidad(barbero, servicio, fecha, *, ahora=None, paso_minutos=15):
    """Genera candidatos desde cada tramo libre, con duración real del servicio.

    El paso es la separación entre candidatos, no la duración del servicio.
    Se excluyen horas pasadas, descansos, bloqueos y ocupaciones persistidas.
    """
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise ValidationError("Selecciona una fecha válida.")
    if (
        not isinstance(paso_minutos, int)
        or isinstance(paso_minutos, bool)
        or not 1 <= paso_minutos <= 60
    ):
        raise ValidationError("El paso debe estar entre 1 y 60 minutos.")
    ahora = ahora or timezone.now()
    if timezone.is_naive(ahora):
        raise ValidationError("La hora de referencia debe incluir zona horaria.")
    if fecha < timezone.localdate(ahora, timezone.get_default_timezone()):
        raise ValidationError("No se puede consultar disponibilidad en fechas pasadas.")
    _comprobar_servicio(barbero, servicio)
    inicio_dia = _fecha_hora(fecha, time.min)
    fin_dia = _fecha_hora(fecha + timedelta(days=1), time.min)
    tramos = tramos_laborales(barbero, fecha)
    for modelo in [Bloqueo, Ocupacion]:
        consulta = modelo.objects.filter(
            barbero=barbero, inicio__lt=fin_dia, fin__gt=inicio_dia
        )
        if modelo is Ocupacion:
            consulta = consulta.filter(activa=True)
        for inicio, fin in consulta.values_list("inicio", "fin"):
            tramos = _restar(tramos, inicio, fin)
    duracion = timedelta(minutes=servicio.duracion_minutos)
    paso = timedelta(minutes=paso_minutos)
    franjas = []
    for tramo in sorted(tramos, key=lambda t: t.inicio):
        candidato = tramo.inicio
        if candidato < ahora:
            candidato += ((ahora - candidato) // paso) * paso
            if candidato < ahora:
                candidato += paso
        while candidato + duracion <= tramo.fin:
            franjas.append(Franja(candidato, candidato + duracion))
            candidato += paso
    return franjas


def validar_intervalo(barbero, servicio, inicio, fin, *, excluir=None, ahora=None):
    """Valida cualquier inicio, sin depender del formulario ni de una grilla UI."""
    if not inicio or not fin or timezone.is_naive(inicio) or timezone.is_naive(fin):
        raise ValidationError("Indica inicio y fin con zona horaria.")
    if fin <= inicio:
        raise ValidationError("El fin debe ser posterior al inicio.")
    if inicio < (ahora or timezone.now()):
        raise ValidationError("El intervalo no puede comenzar en el pasado.")
    if inicio.second or inicio.microsecond or fin.second or fin.microsecond:
        raise ValidationError("Usa horas con precisión de minutos.")
    _comprobar_servicio(barbero, servicio)
    if fin - inicio != timedelta(minutes=servicio.duracion_minutos):
        raise ValidationError(
            "El intervalo debe coincidir con la duración real del servicio."
        )
    fecha = timezone.localdate(inicio, timezone.get_default_timezone())
    if not any(
        t.inicio <= inicio and fin <= t.fin for t in tramos_laborales(barbero, fecha)
    ):
        raise ValidationError(
            "El intervalo está fuera del horario laboral o cruza un descanso."
        )
    if Bloqueo.objects.filter(barbero=barbero, inicio__lt=fin, fin__gt=inicio).exists():
        raise ValidationError("El intervalo coincide con una ausencia o día bloqueado.")
    if (
        Ocupacion.objects.filter(
            activa=True, barbero=barbero, inicio__lt=fin, fin__gt=inicio
        )
        .exclude(pk=excluir)
        .exists()
    ):
        raise ValidationError(
            "El barbero ya tiene un intervalo ocupado en ese horario."
        )
