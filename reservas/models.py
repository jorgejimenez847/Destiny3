import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class Cita(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pago pendiente"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        CANCELADA = "CANCELADA", "Cancelada"
        EXPIRADA = "EXPIRADA", "Retención expirada"
        PAGO_FALLIDO = "PAGO_FALLIDO", "Pago fallido"
        EN_ATENCION = "EN_ATENCION", "En atención"
        COMPLETADA = "COMPLETADA", "Completada"
        NO_ASISTIO = "NO_ASISTIO", "No asistió"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    solicitud_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    cliente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="citas"
    )
    barbero = models.ForeignKey("barberos.PerfilBarbero", on_delete=models.PROTECT)
    servicio = models.ForeignKey("servicios.Servicio", on_delete=models.PROTECT)
    ocupacion = models.OneToOneField(
        "barberos.Ocupacion", on_delete=models.PROTECT, related_name="cita"
    )
    cliente_nombre = models.CharField(max_length=301, default="", editable=False)
    servicio_nombre = models.CharField(max_length=100)
    barbero_nombre = models.CharField(max_length=300)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    duracion_minutos = models.PositiveIntegerField()
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    moneda = models.CharField(max_length=3, default="USD", editable=False)
    estado = models.CharField(
        max_length=15, choices=Estado.choices, default=Estado.PENDIENTE
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    expira_en = models.DateTimeField()

    class Meta:
        ordering = ["-creada_en"]
        constraints = [
            models.CheckConstraint(
                condition=Q(fin__gt=F("inicio")), name="cita_intervalo_valido"
            ),
            models.CheckConstraint(
                condition=Q(precio__gt=0, duracion_minutos__gt=0, moneda="USD"),
                name="cita_importe_duracion_validos",
            ),
            models.CheckConstraint(
                condition=Q(
                    estado__in=[
                        "PENDIENTE",
                        "CONFIRMADA",
                        "CANCELADA",
                        "EXPIRADA",
                        "PAGO_FALLIDO",
                        "EN_ATENCION",
                        "COMPLETADA",
                        "NO_ASISTIO",
                    ]
                ),
                name="cita_estado_valido",
            ),
        ]
        indexes = [models.Index(fields=["estado", "expira_en"])]

    @property
    def cancelacion_pendiente(self):
        solicitud = getattr(self, "cancelacion", None)
        return solicitud is not None and solicitud.finalizada_en is None

    @property
    def puede_cancelarse(self):
        try:
            pago = self.pago
        except Pago.DoesNotExist:
            return False
        if self.cancelacion_pendiente:
            return False
        ahora = timezone.now()
        if self.estado == self.Estado.CONFIRMADA:
            return (
                self.inicio - ahora >= timedelta(hours=24)
                and pago.estado == Pago.Estado.COMPLETADO
                and pago.captura_verificada
                and not pago.reembolso_id
                and pago.reembolso_iniciado_en is None
                and (not pago.procesando_hasta or pago.procesando_hasta <= ahora)
            )
        return (
            self.estado == self.Estado.PENDIENTE
            and ahora < min(self.expira_en, self.inicio)
            and pago.captura_solicitada_en is None
            and not pago.captura_id
            and pago.importe_capturado is None
            and pago.estado
            in {
                Pago.Estado.NUEVO,
                Pago.Estado.CREANDO,
                Pago.Estado.CREADO,
                Pago.Estado.VERIFICANDO,
            }
        )

    @property
    def numero_comprobante(self):
        return f"D3-{self.pk.hex.upper()}"

    @property
    def fecha_comprobante(self):
        return next(
            (
                evento.fecha
                for evento in self.eventos.all()
                if evento.nuevo == self.Estado.CONFIRMADA
            ),
            None,
        )

    @property
    def comprobante_disponible(self):
        try:
            pago = self.pago
        except Pago.DoesNotExist:
            return False
        return bool(
            self.estado
            in {
                self.Estado.CONFIRMADA,
                self.Estado.EN_ATENCION,
                self.Estado.COMPLETADA,
                self.Estado.NO_ASISTIO,
            }
            and pago.estado == Pago.Estado.COMPLETADO
            and pago.captura_id
            and not pago.reembolso_id
            and pago.importe_capturado == self.precio
            and pago.moneda_capturada == self.moneda == "USD"
            and self.cliente_nombre
            and self.fecha_comprobante
        )

    def __str__(self):
        return f"{self.servicio_nombre} · {self.get_estado_display()}"


class Pago(models.Model):
    class Estado(models.TextChoices):
        NUEVO = "NUEVO", "Sin orden"
        CERRADO = "CERRADO", "Sin cobro; retención finalizada"
        CREANDO = "CREANDO", "Preparando pago"
        CREADO = "CREADO", "Esperando aprobación"
        VERIFICANDO = "VERIFICANDO", "Verificando pago"
        COMPLETADO = "COMPLETADO", "Pago completado"
        FALLIDO = "FALLIDO", "Pago rechazado"
        REEMBOLSO_PENDIENTE = "REEMBOLSO_PENDIENTE", "Reembolso pendiente"
        REEMBOLSADO = "REEMBOLSADO", "Reembolso completado"

    cita = models.OneToOneField(Cita, on_delete=models.PROTECT, related_name="pago")
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.NUEVO
    )
    orden_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    captura_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    reembolso_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    solicitud_crear = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    solicitud_capturar = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True
    )
    solicitud_reembolsar = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True
    )
    aprobacion_url = models.URLField(max_length=1000, blank=True)
    receptor_id = models.CharField(max_length=100, blank=True)
    captura_solicitada_en = models.DateTimeField(null=True, blank=True)
    procesando_hasta = models.DateTimeField(null=True, blank=True)
    proxima_revision = models.DateTimeField(null=True, blank=True)
    importe_capturado = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    moneda_capturada = models.CharField(max_length=3, blank=True)
    reembolso_estado = models.CharField(max_length=20, blank=True, editable=False)
    reembolso_iniciado_en = models.DateTimeField(null=True, blank=True, editable=False)
    reembolso_finalizado_en = models.DateTimeField(
        null=True, blank=True, editable=False
    )
    detalle = models.CharField(max_length=200, blank=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    @property
    def captura_verificada(self):
        return bool(
            self.orden_id
            and self.captura_id
            and self.importe_capturado == self.cita.precio
            and self.moneda_capturada == self.cita.moneda == "USD"
        )

    @property
    def detalle_actual(self):
        if self.estado == self.Estado.CERRADO:
            return {
                Cita.Estado.CANCELADA: "La reserva se canceló sin realizar un cobro.",
                Cita.Estado.EXPIRADA: "El plazo de pago venció sin realizar un cobro.",
            }.get(self.cita.estado, self.detalle)
        return self.detalle


class SolicitudCancelacion(models.Model):
    cita = models.OneToOneField(
        Cita, on_delete=models.PROTECT, related_name="cancelacion"
    )
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.CharField(max_length=180)
    solicitada_en = models.DateTimeField(default=timezone.now, editable=False)
    finalizada_en = models.DateTimeField(null=True, blank=True, editable=False)


class EventoCita(models.Model):
    cita = models.ForeignKey(Cita, on_delete=models.PROTECT, related_name="eventos")
    anterior = models.CharField(max_length=15, blank=True)
    nuevo = models.CharField(max_length=15)
    motivo = models.CharField(max_length=250)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "pk"]


class EstadoProcesador(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    ultimo_latido = models.DateTimeField()
