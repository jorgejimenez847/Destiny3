from datetime import datetime, time
from zoneinfo import ZoneInfo
from django.test import TestCase
from usuarios.models import Usuario
from servicios.models import Servicio
from barberos.models import PerfilBarbero, Horario

def momento(hora, minuto=0, dia=7):
    return datetime(2030, 1, dia, hora, minuto, tzinfo=ZoneInfo("America/Panama"))

class AgendaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user(username="administrador", rol="ADMIN")
        cls.cliente = Usuario.objects.create_user(username="cliente", rol="CLIENTE")
        cls.usuario = Usuario.objects.create_user(username="barbero", rol="BARBERO")
        cls.otro_usuario = Usuario.objects.create_user(username="otro", rol="BARBERO")
        cls.barbero = PerfilBarbero.objects.create(usuario=cls.usuario, especialidad="Cortes")
        cls.otro = PerfilBarbero.objects.create(usuario=cls.otro_usuario, especialidad="Barba")
        cls.servicio = Servicio.objects.create(nombre="Corte", precio="8.00", duracion_minutos=30)
        cls.barbero.servicios.add(cls.servicio)
        cls.otro.servicios.add(cls.servicio)

    def turno(self, **kwargs):
        datos = dict(barbero=self.barbero, dia=0, inicio=time(9), fin=time(17),
                     descanso_inicio=time(12), descanso_fin=time(13))
        datos.update(kwargs)
        return Horario.objects.create(**datos)
