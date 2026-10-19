from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models


class Servicio(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    duracion_minutos = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Duración real del servicio en minutos; debe ser mayor que cero.",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.CheckConstraint(condition=models.Q(precio__gt=0), name="servicio_precio_positivo"),
            models.CheckConstraint(condition=models.Q(duracion_minutos__gt=0), name="servicio_duracion_positiva"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.duracion_minutos} min)"
