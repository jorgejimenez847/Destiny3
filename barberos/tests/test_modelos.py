from datetime import time
from django.core.exceptions import ValidationError
from barberos.models import Bloqueo, Horario, PerfilBarbero
from .base import AgendaTestCase, momento

class PerfilTests(AgendaTestCase):
    def test_solo_usuario_barbero(self):
        with self.assertRaises(ValidationError):
            PerfilBarbero.objects.create(usuario=self.cliente, especialidad="Cortes")

    def test_servicios_y_estado(self):
        self.assertIn(self.servicio, self.barbero.servicios.all())
        self.barbero.activo = False
        self.barbero.save()
        self.assertFalse(PerfilBarbero.objects.get(pk=self.barbero.pk).activo)

class HorarioTests(AgendaTestCase):
    def test_turno_con_descanso_valido(self):
        self.turno()
        self.assertEqual(Horario.objects.count(), 1)

    def test_turno_sin_descanso(self):
        self.turno(descanso_inicio=None, descanso_fin=None)

    def test_turnos_adyacentes_permitidos(self):
        self.turno(fin=time(12), descanso_inicio=None, descanso_fin=None)
        self.turno(inicio=time(12), descanso_inicio=None, descanso_fin=None)
        self.assertEqual(Horario.objects.count(), 2)

    def test_rechaza_invertidos_iguales_segundos_y_dia_invalido(self):
        for datos in [dict(inicio=time(17)), dict(fin=time(8)), dict(dia=7), dict(inicio=time(9,0,1))]:
            with self.subTest(datos=datos), self.assertRaises(ValidationError):
                self.turno(**datos)

    def test_rechaza_descansos_incompletos_fuera_o_invertidos(self):
        for datos in [dict(descanso_fin=None), dict(descanso_inicio=time(8)),
                      dict(descanso_fin=time(12)), dict(descanso_fin=time(18))]:
            with self.subTest(datos=datos), self.assertRaises(ValidationError):
                self.turno(**datos)

    def test_rechaza_superposicion(self):
        self.turno()
        for ini, fin in [(8,10),(10,11),(16,18),(8,18),(9,17)]:
            with self.subTest(inicio=ini,fin=fin), self.assertRaises(ValidationError):
                self.turno(inicio=time(ini),fin=time(fin),descanso_inicio=None,descanso_fin=None)

    def test_misma_hora_otro_barbero_u_otro_dia(self):
        self.turno()
        self.turno(barbero=self.otro)
        self.turno(dia=1)
        self.assertEqual(Horario.objects.count(),3)

    def test_editar_no_choca_con_si_mismo(self):
        turno=self.turno()
        turno.fin=time(18)
        turno.save()

class BloqueoTests(AgendaTestCase):
    def test_dia_completo_y_vacaciones(self):
        b=Bloqueo.objects.create(barbero=self.barbero,inicio=momento(0),fin=momento(0,dia=10),motivo="VACACIONES")
        self.assertEqual((b.fin-b.inicio).days,3)

    def test_rechaza_intervalos_invalidos(self):
        for fin in [momento(9),momento(8)]:
            with self.subTest(fin=fin), self.assertRaises(ValidationError):
                Bloqueo.objects.create(barbero=self.barbero,inicio=momento(9),fin=fin,motivo="OTRO")

    def test_rechaza_solapamiento_permite_adyacencia(self):
        Bloqueo.objects.create(barbero=self.barbero,inicio=momento(9),fin=momento(10),motivo="AUSENCIA")
        with self.assertRaises(ValidationError):
            Bloqueo.objects.create(barbero=self.barbero,inicio=momento(9,30),fin=momento(11),motivo="OTRO")
        Bloqueo.objects.create(barbero=self.barbero,inicio=momento(10),fin=momento(11),motivo="OTRO")

    def test_rechaza_fechas_sin_zona(self):
        with self.assertRaises(ValidationError):
            Bloqueo.objects.create(barbero=self.barbero,inicio=momento(9).replace(tzinfo=None),fin=momento(10),motivo="OTRO")
