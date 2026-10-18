from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

DIAS = [(0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"),
        (4, "Viernes"), (5, "Sábado"), (6, "Domingo")]


class PerfilBarbero(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="perfil_barbero", limit_choices_to={"rol": "BARBERO"})
    especialidad = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, verbose_name="Presentación")
    servicios = models.ManyToManyField("servicios.Servicio", related_name="barberos", blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["usuario__first_name", "usuario__username"]
        verbose_name = "Perfil de barbero"
        verbose_name_plural = "Perfiles de barberos"

    def __str__(self):
        return self.usuario.get_full_name() or self.usuario.username

    def clean(self):
        super().clean()
        if self.usuario_id and self.usuario.rol != "BARBERO":
            raise ValidationError({"usuario": "El usuario debe tener el rol Barbero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class DatoBarbero(models.Model):
    barbero = models.ForeignKey(PerfilBarbero, on_delete=models.PROTECT)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Todas las escrituras de agenda se serializan por barbero.
        with transaction.atomic():
            if self.barbero_id:
                self.barbero = PerfilBarbero.objects.select_for_update().get(pk=self.barbero_id)
            self.full_clean()
            return super().save(*args, **kwargs)


class Horario(DatoBarbero):
    dia = models.PositiveSmallIntegerField(choices=DIAS, verbose_name="Día de la semana")
    inicio = models.TimeField(verbose_name="Entrada")
    fin = models.TimeField(verbose_name="Salida")
    descanso_inicio = models.TimeField(null=True, blank=True, verbose_name="Inicio del descanso")
    descanso_fin = models.TimeField(null=True, blank=True, verbose_name="Fin del descanso")

    class Meta:
        ordering = ["dia", "inicio"]
        constraints = [
            models.CheckConstraint(condition=Q(dia__gte=0, dia__lte=6), name="horario_dia_valido"),
            models.CheckConstraint(condition=Q(fin__gt=F("inicio")), name="horario_orden_valido"),
            models.CheckConstraint(condition=(Q(descanso_inicio__isnull=True, descanso_fin__isnull=True) |
                Q(descanso_inicio__isnull=False, descanso_fin__isnull=False,
                  descanso_inicio__gt=F("inicio"), descanso_fin__lt=F("fin"),
                  descanso_fin__gt=F("descanso_inicio"))), name="horario_descanso_valido"),
        ]

    def __str__(self):
        return f"{self.get_dia_display()} {self.inicio:%H:%M}–{self.fin:%H:%M}"

    def clean(self):
        super().clean()
        if self.inicio is None or self.fin is None:
            return
        if any(t and (t.second or t.microsecond) for t in
               [self.inicio, self.fin, self.descanso_inicio, self.descanso_fin]):
            raise ValidationError("Usa horas con precisión de minutos, sin segundos.")
        if self.fin <= self.inicio:
            raise ValidationError({"fin": "La salida debe ser posterior a la entrada, en el mismo día."})
        if bool(self.descanso_inicio) != bool(self.descanso_fin):
            raise ValidationError("Indica tanto el inicio como el fin del descanso.")
        if self.descanso_inicio and not (self.inicio < self.descanso_inicio < self.descanso_fin < self.fin):
            raise ValidationError("El descanso debe estar completamente dentro del turno.")
        if self.barbero_id and self.dia is not None and Horario.objects.filter(
            barbero_id=self.barbero_id, dia=self.dia, inicio__lt=self.fin,
            fin__gt=self.inicio).exclude(pk=self.pk).exists():
            raise ValidationError("Este turno se superpone con otro horario del barbero.")
        if self.pk:
            validar_cambio_horario(self)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            PerfilBarbero.objects.select_for_update().get(pk=self.barbero_id)
            validar_cambio_horario(self, eliminar=True)
            return super().delete(*args, **kwargs)



class Bloqueo(DatoBarbero):
    class Motivo(models.TextChoices):
        AUSENCIA = "AUSENCIA", "Ausencia"
        VACACIONES = "VACACIONES", "Vacaciones"
        FERIADO = "FERIADO", "Feriado / día no disponible"
        OTRO = "OTRO", "Otro motivo"

    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    motivo = models.CharField(max_length=15, choices=Motivo.choices)
    nota = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-inicio"]
        constraints = [models.CheckConstraint(condition=Q(fin__gt=F("inicio")), name="bloqueo_orden_valido")]

    def __str__(self):
        return f"{self.get_motivo_display()}: {timezone.localtime(self.inicio):%d/%m/%Y %H:%M}"

    def clean(self):
        super().clean()
        if not self.inicio or not self.fin:
            return
        if timezone.is_naive(self.inicio) or timezone.is_naive(self.fin):
            raise ValidationError({"inicio": "Las fechas deben incluir la zona horaria de Panamá."})
        if self.fin <= self.inicio:
            raise ValidationError({"fin": "El fin debe ser posterior al inicio."})
        if self.barbero_id and Bloqueo.objects.filter(barbero_id=self.barbero_id,
            inicio__lt=self.fin, fin__gt=self.inicio).exclude(pk=self.pk).exists():
            raise ValidationError("Ya existe un bloqueo que cubre parte de este intervalo.")
        if self.barbero_id and Ocupacion.objects.filter(barbero_id=self.barbero_id,
            inicio__lt=self.fin, fin__gt=self.inicio).exists():
            raise ValidationError("El bloqueo afecta un intervalo ocupado. Resuelve esa ocupación antes de bloquear.")


class RangoFechaHora(models.Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Ocupacion(DatoBarbero):
    """Intervalo ocupado mínimo para M08. No representa pago ni reserva completa.

    La futura Fase 4 podrá relacionar su reserva con este intervalo. No se expone
    un flujo de creación de reservas ni de pago en esta fase.
    """
    servicio = models.ForeignKey("servicios.Servicio", on_delete=models.PROTECT)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    referencia = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["inicio"]
        constraints = [
            models.CheckConstraint(condition=Q(fin__gt=F("inicio")), name="ocupacion_orden_valido"),
            ExclusionConstraint(name="ocupacion_sin_solapamiento", expressions=[
                (RangoFechaHora("inicio", "fin", RangeBoundary()), RangeOperators.OVERLAPS),
                ("barbero", RangeOperators.EQUAL),
            ], violation_error_message="El barbero ya tiene un intervalo ocupado en ese horario."),
        ]

    def clean(self):
        super().clean()
        if self.barbero_id and self.servicio_id and self.inicio and self.fin:
            from .disponibilidad import validar_intervalo
            validar_intervalo(self.barbero, self.servicio, self.inicio, self.fin, excluir=self.pk)


def validar_cambio_horario(horario, eliminar=False):
    """Evita dejar ocupaciones futuras sin un turno que las contenga."""
    for ocupacion in Ocupacion.objects.filter(barbero_id=horario.barbero_id, fin__gt=timezone.now()):
        inicio=timezone.localtime(ocupacion.inicio,timezone.get_default_timezone())
        fin=timezone.localtime(ocupacion.fin,timezone.get_default_timezone())
        turnos=list(Horario.objects.filter(barbero_id=horario.barbero_id,dia=inicio.weekday()).exclude(pk=horario.pk))
        if not eliminar and horario.dia == inicio.weekday():
            turnos.append(horario)
        contenido=False
        for turno in turnos:
            if turno.inicio <= inicio.time() and fin.time() <= turno.fin:
                if not turno.descanso_inicio or fin.time() <= turno.descanso_inicio or inicio.time() >= turno.descanso_fin:
                    contenido=True
        if not contenido:
            raise ValidationError("El cambio dejaría un intervalo ocupado fuera del horario. Resuelve la ocupación antes de cambiar el turno.")
