from datetime import time, timedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from barberos.disponibilidad import calcular_disponibilidad, validar_intervalo
from barberos.models import Bloqueo, Ocupacion
from .base import AgendaTestCase, momento

class DisponibilidadTests(AgendaTestCase):
    def setUp(self):
        self.turno()

    def franjas(self, **kwargs):
        datos=dict(barbero=self.barbero,servicio=self.servicio,fecha=momento(9).date(),ahora=momento(0))
        datos.update(kwargs)
        return calcular_disponibilidad(**datos)

    def ocupar(self, inicio=None, fin=None, **kwargs):
        return Ocupacion.objects.create(barbero=self.barbero,servicio=self.servicio,
            inicio=inicio or momento(9),fin=fin or momento(9,30),**kwargs)

    def test_calculo_real_respeta_entrada_salida_y_descanso(self):
        franjas=self.franjas()
        self.assertEqual(franjas[0].inicio,momento(9))
        self.assertEqual(franjas[-1].fin,momento(17))
        self.assertTrue(all(f.fin-f.inicio==timedelta(minutes=30) for f in franjas))
        self.assertFalse(any(f.inicio < momento(13) and f.fin > momento(12) for f in franjas))

    def test_duracion_cincuenta_minutos_cruza_limite(self):
        self.servicio.duracion_minutos=50
        self.servicio.save()
        franjas=self.franjas()
        self.assertTrue(all(f.fin-f.inicio==timedelta(minutes=50) for f in franjas))
        self.assertNotIn(momento(11,15),[f.inicio for f in franjas])
        self.assertNotIn(momento(16,15),[f.inicio for f in franjas])

    def test_bloqueo_parcial_descuenta_intervalo_completo(self):
        Bloqueo.objects.create(barbero=self.barbero,inicio=momento(10,10),fin=momento(11,10),motivo="AUSENCIA")
        franjas=self.franjas()
        self.assertFalse(any(f.inicio < momento(11,10) and f.fin > momento(10,10) for f in franjas))
        self.assertIn(momento(11,10),[f.inicio for f in franjas])

    def test_dia_completo_y_vacaciones_sin_disponibilidad(self):
        Bloqueo.objects.create(barbero=self.barbero,inicio=momento(0,dia=6),fin=momento(0,dia=10),motivo="VACACIONES")
        self.assertEqual(self.franjas(),[])

    def test_sin_turno_sin_disponibilidad(self):
        self.assertEqual(self.franjas(fecha=momento(9,dia=8).date()),[])

    def test_duracion_mayor_que_cualquier_tramo(self):
        self.servicio.duracion_minutos=500
        self.servicio.save()
        self.assertEqual(self.franjas(),[])

    def test_barbero_inactivo_usuario_inactivo_servicio_inactivo(self):
        self.barbero.activo=False
        with self.assertRaises(ValidationError): self.franjas()
        self.barbero.activo=True
        self.usuario.is_active=False
        self.barbero.usuario=self.usuario
        with self.assertRaises(ValidationError): self.franjas()
        self.usuario.is_active=True
        self.servicio.activo=False
        with self.assertRaises(ValidationError): self.franjas()

    def test_servicio_no_ofrecido(self):
        self.barbero.servicios.clear()
        with self.assertRaises(ValidationError): self.franjas()

    def test_horas_pasadas_y_limite_de_ahora(self):
        franjas=self.franjas(ahora=momento(10,7))
        self.assertEqual(franjas[0].inicio,momento(10,15))
        self.assertEqual(self.franjas(ahora=momento(17)),[])

    def test_fecha_pasada_y_paso_invalido(self):
        with self.assertRaises(ValidationError): self.franjas(ahora=momento(0,dia=8))
        for paso in [0,-1,61,True]:
            with self.subTest(paso=paso), self.assertRaises(ValidationError): self.franjas(paso_minutos=paso)

    def test_ocupaciones_descontadas_y_barberos_independientes(self):
        self.ocupar()
        franjas=self.franjas()
        self.assertEqual(franjas[0].inicio,momento(9,30))
        self.turno(barbero=self.otro)
        self.assertEqual(self.franjas(barbero=self.otro)[0].inicio,momento(9))

    def test_intervalos_adyacentes_y_final_de_turno_permitidos(self):
        self.ocupar()
        self.ocupar(inicio=momento(9,30),fin=momento(10))
        self.ocupar(inicio=momento(16,30),fin=momento(17))
        self.assertEqual(Ocupacion.objects.count(),3)

    def test_superposiciones_iguales_interiores_y_extremos_rechazados(self):
        self.ocupar(inicio=momento(10),fin=momento(10,30))
        for inicio,fin in [(momento(10),momento(10,30)),(momento(9,45),momento(10,15)),
                           (momento(10,15),momento(10,45)),(momento(10,5),momento(10,35))]:
            with self.subTest(inicio=inicio), self.assertRaises(ValidationError):
                self.ocupar(inicio=inicio,fin=fin)

    def test_no_permite_cruzar_descanso_o_salida_o_duracion_falsa(self):
        for inicio,fin in [(momento(11,45),momento(12,15)),(momento(16,45),momento(17,15)),
                           (momento(8,45),momento(9,15)),(momento(10),momento(10,20))]:
            with self.subTest(inicio=inicio), self.assertRaises(ValidationError):
                self.ocupar(inicio=inicio,fin=fin)

    def test_valida_ausencias_fechas_pasadas_y_segundos(self):
        Bloqueo.objects.create(barbero=self.barbero,inicio=momento(10),fin=momento(11),motivo="OTRO")
        with self.assertRaises(ValidationError): self.ocupar(inicio=momento(10),fin=momento(10,30))
        with self.assertRaises(ValidationError): validar_intervalo(self.barbero,self.servicio,momento(9),momento(9,30),ahora=momento(10))
        with self.assertRaises(ValidationError): self.ocupar(inicio=momento(9).replace(second=1),fin=momento(9,30).replace(second=1))

    def test_editar_ocupacion_no_choca_con_si_misma(self):
        ocupacion=self.ocupar()
        ocupacion.referencia="Actualizada"
        ocupacion.save()

    def test_postgresql_impide_saltarse_validacion_mediante_bulk(self):
        self.ocupar()
        with self.assertRaises(IntegrityError),transaction.atomic():
            Ocupacion.objects.bulk_create([Ocupacion(barbero=self.barbero,servicio=self.servicio,
                inicio=momento(9,15),fin=momento(9,45))])

    def test_bloqueo_no_invalida_ocupacion_existente(self):
        self.ocupar()
        with self.assertRaises(ValidationError):
            Bloqueo.objects.create(barbero=self.barbero,inicio=momento(9),fin=momento(10),motivo="OTRO")

    def test_cambio_y_borrado_de_turno_no_invalidan_ocupacion(self):
        self.ocupar()
        h=self.barbero.horario_set.get()
        h.inicio=time(10)
        with self.assertRaises(ValidationError): h.save()
        h.refresh_from_db()
        with self.assertRaises(ValidationError): h.delete()

    def test_api_http_consulta_y_rechaza_pareja_incompatible(self):
        url=reverse("barberos:disponibilidad")
        r=self.client.get(url,{"servicio":self.servicio.pk,"barbero":self.barbero.pk,"fecha":"2030-01-07"})
        self.assertContains(r,"09:00")
        self.assertContains(r,"30 minutos")
        self.barbero.servicios.clear()
        r=self.client.get(url,{"servicio":self.servicio.pk,"barbero":self.barbero.pk,"fecha":"2030-01-07"})
        self.assertTrue(r.context["form"].errors)
        self.assertIsNone(r.context["franjas"])

    def test_consulta_no_crea_ocupaciones_y_solo_acepta_get(self):
        url=reverse("barberos:disponibilidad")
        self.client.get(url,{"servicio":self.servicio.pk,"barbero":self.barbero.pk,"fecha":"2030-01-07"})
        self.assertEqual(Ocupacion.objects.count(),0)
        self.assertEqual(self.client.post(url,{}).status_code,405)

    def test_no_hay_endpoint_de_reserva(self):
        self.assertEqual(self.client.get("/reservas/").status_code,404)


    def test_otro_barbero_puede_ocupar_misma_hora(self):
        self.turno(barbero=self.otro)
        self.ocupar()
        Ocupacion.objects.create(barbero=self.otro,servicio=self.servicio,inicio=momento(9),fin=momento(9,30))
        self.assertEqual(Ocupacion.objects.count(),2)

    def test_exclusion_postgres_tambien_protege_actualizacion_directa(self):
        self.ocupar()
        otra=self.ocupar(inicio=momento(10),fin=momento(10,30))
        with self.assertRaises(IntegrityError),transaction.atomic():
            Ocupacion.objects.filter(pk=otra.pk).update(inicio=momento(9,15),fin=momento(9,45))

    def test_terminar_en_descanso_o_comenzar_al_final_del_descanso(self):
        self.ocupar(inicio=momento(11,30),fin=momento(12))
        self.ocupar(inicio=momento(13),fin=momento(13,30))
        self.assertEqual(Ocupacion.objects.count(),2)
