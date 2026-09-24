from django.test import TestCase

from .models import Servicio


class ServicioTests(TestCase):
    def test_servicio_guarda_duracion_y_precio(self):
        s = Servicio.objects.create(nombre="Corte", precio="8.50", duracion_minutos=30)
        self.assertEqual(s.duracion_minutos, 30)
        self.assertTrue(s.activo)
        self.assertEqual(str(s), "Corte (30 min)")