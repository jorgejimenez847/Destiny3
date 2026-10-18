from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from .models import Servicio

class ValidacionServicioTests(TestCase):
    def test_duracion_cero_y_precio_no_positivo_rechazados(self):
        for datos in [dict(precio=1,duracion_minutos=0),dict(precio=0,duracion_minutos=30),dict(precio=-1,duracion_minutos=30)]:
            with self.subTest(datos=datos),self.assertRaises(ValidationError):
                Servicio(nombre="Invalido",**datos).full_clean()

    def test_base_rechaza_duracion_cero(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            Servicio.objects.create(nombre="Invalido",precio=1,duracion_minutos=0)
