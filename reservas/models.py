import uuid
from django.conf import settings
from django.db import models
from django.db.models import F, Q


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
        REEMBOLSO_PENDIENTE = "REEMBOLSO_PENDIENTE", "Reembolso de prueba pendiente"
        REEMBOLSADO = "REEMBOLSADO", "Reembolso de prueba completado"

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
    detalle = models.CharField(max_length=200, blank=True)
    actualizada_en = models.DateTimeField(auto_now=True)


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
