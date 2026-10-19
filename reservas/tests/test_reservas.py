from datetime import timedelta
from decimal import Decimal
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from reservas.models import Cita, EstadoProcesador, Pago
from reservas.servicios import (
    cancelar_cita,
    cambiar_estado_operativo,
    ejecutar_ciclo,
    expirar_retenciones,
)
from barberos.models import Ocupacion
from barberos.disponibilidad import calcular_disponibilidad
from .base import ReservaTestCase, momento


class ReservaTests(ReservaTestCase):
    def test_crea_cita_y_retiene_diez_minutos(self):
        antes = timezone.now()
        cita = self.reservar()
        self.assertEqual(cita.estado, Cita.Estado.PENDIENTE)
        self.assertEqual(cita.precio, Decimal("8.00"))
        self.assertEqual(cita.fin - cita.inicio, timedelta(minutes=30))
        self.assertTrue(cita.ocupacion.activa)
        self.assertAlmostEqual((cita.expira_en - antes).total_seconds(), 600, delta=3)
        self.assertEqual(cita.eventos.count(), 1)

    def test_repetir_seleccion_es_idempotente(self):
        identificador = uuid.uuid4()
        uno = self.reservar(solicitud_id=identificador)
        dos = self.reservar(solicitud_id=identificador)
        self.assertEqual(uno.pk, dos.pk)
        self.assertEqual(Cita.objects.count(), 1)
        self.assertEqual(Ocupacion.objects.count(), 1)

    def test_no_admite_otro_cliente_ni_parametros_con_misma_solicitud(self):
        cita = self.reservar()
        with self.assertRaises(ValidationError):
            self.reservar(solicitud_id=cita.solicitud_id, inicio=momento(10))

    def test_otro_cliente_no_puede_tomar_retencion(self):
        from usuarios.models import Usuario

        otro = Usuario.objects.create_user(username="otrocliente", rol="CLIENTE")
        self.reservar()
        with self.assertRaises(ValidationError):
            self.reservar(cliente=otro)

    def test_barbero_y_admin_no_reservan_como_cliente(self):
        for usuario in [self.usuario, self.admin]:
            with self.subTest(usuario=usuario), self.assertRaises(PermissionDenied):
                self.reservar(cliente=usuario)

    def test_revalida_precio_y_servicio(self):
        with self.assertRaises(ValidationError):
            self.reservar(precio_esperado=Decimal("0.01"))
        self.barbero.servicios.clear()
        with self.assertRaises(ValidationError):
            self.reservar()

    def test_no_crea_reservas_sin_procesador_o_con_latido_vencido(self):
        EstadoProcesador.objects.all().delete()
        with self.assertRaises(ValidationError):
            self.reservar()
        EstadoProcesador.objects.create(
            pk=1, ultimo_latido=timezone.now() - timedelta(minutes=5)
        )
        with self.assertRaises(ValidationError):
            self.reservar()

    def test_ciclo_expira_sin_visita_y_libera_con_historial(self):
        cita = self.reservar()
        Cita.objects.filter(pk=cita.pk).update(
            expira_en=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(ejecutar_ciclo(), 1)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.EXPIRADA)
        self.assertFalse(cita.ocupacion.activa)
        self.assertEqual(cita.eventos.count(), 2)
        nueva = self.reservar()
        self.assertNotEqual(nueva.pk, cita.pk)

    def test_cancelacion_pendiente_idempotente(self):
        cita = self.reservar()
        cancelar_cita(cita.pk, self.cliente)
        cancelar_cita(cita.pk, self.cliente)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CANCELADA)
        self.assertFalse(cita.ocupacion.activa)
        self.assertEqual(cita.eventos.count(), 2)

    def test_otro_usuario_no_cancela(self):
        cita = self.reservar()
        with self.assertRaises(PermissionDenied):
            cancelar_cita(cita.pk, self.admin)

    def test_captura_incierta_no_expira_ni_se_cancela(self):
        cita = self.reservar()
        Pago.objects.filter(cita=cita).update(
            captura_solicitada_en=timezone.now(), estado=Pago.Estado.VERIFICANDO
        )
        Cita.objects.filter(pk=cita.pk).update(
            expira_en=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(expirar_retenciones(), 0)
        with self.assertRaises(ValidationError):
            cancelar_cita(cita.pk, self.cliente)
        cita.refresh_from_db()
        self.assertTrue(cita.ocupacion.activa)

    def test_ocupacion_liberada_no_afecta_disponibilidad_ni_exclusion(self):
        cita = self.reservar()
        cancelar_cita(cita.pk, self.cliente)
        franjas = calcular_disponibilidad(
            self.barbero, self.servicio, momento(9).date(), ahora=momento(0)
        )
        self.assertEqual(franjas[0].inicio, momento(9))
        self.reservar()

    def test_estados_operativos_rechazan_cliente_otra_persona_y_hora_futura(self):
        cita = self.reservar()
        with self.assertRaises(PermissionDenied):
            cambiar_estado_operativo(cita.pk, Cita.Estado.CONFIRMADA, self.cliente)
        with self.assertRaises(PermissionDenied):
            cambiar_estado_operativo(
                cita.pk, Cita.Estado.EN_ATENCION, self.otro_usuario
            )
        with self.assertRaises(ValidationError):
            cambiar_estado_operativo(cita.pk, Cita.Estado.EN_ATENCION, self.usuario)

    def test_transiciones_de_atencion_validas_y_rechazadas(self):
        from unittest.mock import patch
        from reservas.servicios import procesar_pago

        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            factory.return_value.consultar.return_value = self.orden(
                cita, "COMPLETED", self.captura()
            )
            procesar_pago(cita.pk)
        with patch("reservas.servicios.timezone.now", return_value=momento(10)):
            cambiar_estado_operativo(cita.pk, Cita.Estado.EN_ATENCION, self.usuario)
            cambiar_estado_operativo(cita.pk, Cita.Estado.COMPLETADA, self.usuario)
            with self.assertRaises(ValidationError):
                cambiar_estado_operativo(cita.pk, Cita.Estado.EN_ATENCION, self.admin)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.COMPLETADA)
