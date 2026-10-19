from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.utils import timezone
from reservas.models import Cita, Pago
from reservas.paypal import PayPalError
from reservas.servicios import (
    preparar_orden,
    procesar_pago,
    cancelar_cita,
    expirar_retenciones,
)
from .base import ReservaTestCase


class PagoTests(ReservaTestCase):
    def test_crea_orden_y_reutiliza_enlace_sin_duplicar(self):
        cita = self.reservar()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            factory.return_value.crear.return_value = self.orden(cita, "CREATED")
            primera = preparar_orden(cita.pk, self.cliente)
            segunda = preparar_orden(cita.pk, self.cliente)
            self.assertEqual(primera, segunda)
            factory.return_value.crear.assert_called_once()

    def test_captura_y_verifica_importe_moneda_y_orden(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            api = factory.return_value
            api.consultar.return_value = self.orden(cita)
            api.capturar.return_value = self.orden(cita, "COMPLETED", self.captura())
            procesar_pago(cita.pk)
            procesar_pago(cita.pk)
            api.capturar.assert_called_once()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CONFIRMADA)
        self.assertEqual(cita.pago.captura_id, "CAPTURA-TEST")
        self.assertTrue(cita.ocupacion.activa)

    def test_no_captura_orden_sin_aprobacion(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory.return_value.consultar.return_value = self.orden(cita, "CREATED")
            procesar_pago(cita.pk)
            factory.return_value.capturar.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PENDIENTE)
        self.assertIsNone(cita.pago.captura_solicitada_en)

    def test_orden_ajena_no_confirma_ni_captura(self):
        cita = self.con_orden()
        orden = self.orden(cita)
        orden["purchase_units"][0]["custom_id"] = "OTRA-RESERVA"
        with patch("reservas.servicios.PayPalClient") as factory:
            factory.return_value.consultar.return_value = orden
            procesar_pago(cita.pk)
            factory.return_value.capturar.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PENDIENTE)

    def test_datos_de_importe_o_moneda_incorrectos_antes_de_capturar(self):
        cita = self.con_orden()
        for valor, moneda in [("0.01", "USD"), ("8.00", "EUR")]:
            orden = self.orden(cita)
            orden["purchase_units"][0]["amount"] = {
                "value": valor,
                "currency_code": moneda,
            }
            with patch("reservas.servicios.PayPalClient") as factory:
                factory.return_value.consultar.return_value = orden
                procesar_pago(cita.pk)
                factory.return_value.capturar.assert_not_called()
            Pago.objects.filter(cita=cita).update(procesando_hasta=None)

    def test_timeout_de_captura_se_reconcilia_sin_doble_pago(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            api = factory.return_value
            api.consultar.return_value = self.orden(cita)
            api.capturar.side_effect = PayPalError()
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PENDIENTE)
        self.assertIsNotNone(cita.pago.captura_solicitada_en)
        caducidad = timezone.now() - timedelta(seconds=1)
        Cita.objects.filter(pk=cita.pk).update(expira_en=caducidad)
        Pago.objects.filter(cita=cita).update(
            captura_solicitada_en=caducidad - timedelta(seconds=1)
        )
        self.assertEqual(expirar_retenciones(), 0)
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            factory.return_value.consultar.return_value = self.orden(
                cita, "COMPLETED", self.captura()
            )
            procesar_pago(cita.pk)
            factory.return_value.capturar.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CONFIRMADA)

    def test_reintento_captura_conserva_mismo_identificador(self):
        cita = self.con_orden()
        ids = []
        with patch("reservas.servicios.PayPalClient") as factory:
            api = factory.return_value
            api.consultar.return_value = self.orden(cita)

            def timeout(pago):
                ids.append(pago.solicitud_capturar)
                raise PayPalError()

            api.capturar.side_effect = timeout
            procesar_pago(cita.pk)
            procesar_pago(cita.pk)
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], ids[1])

    def test_rechazo_definitivo_libera_horario(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            api = factory.return_value
            api.consultar.return_value = self.orden(cita)
            api.capturar.side_effect = PayPalError(
                recuperable=False, codigo="INSTRUMENT_DECLINED"
            )
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PAGO_FALLIDO)
        self.assertFalse(cita.ocupacion.activa)

    def test_captura_pendiente_no_se_presenta_como_pago_completado(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            api = factory.return_value
            api.consultar.return_value = self.orden(cita)
            api.capturar.return_value = self.orden(
                cita, "COMPLETED", self.captura("PENDING")
            )
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PENDIENTE)
        self.assertEqual(cita.pago.estado, Pago.Estado.VERIFICANDO)

    def test_orden_aprobada_despues_de_expirar_no_se_captura(self):
        cita = self.con_orden()
        Cita.objects.filter(pk=cita.pk).update(
            expira_en=timezone.now() - timedelta(seconds=1)
        )
        with patch("reservas.servicios.PayPalClient") as factory:
            factory.return_value.consultar.return_value = self.orden(cita)
            procesar_pago(cita.pk)
            factory.return_value.capturar.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.EXPIRADA)

    def test_pago_tardio_de_cita_cancelada_se_devuelve_sin_confirmar(self):
        cita = self.con_orden()
        cancelar_cita(cita.pk, self.cliente)
        nueva = self.reservar()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            api = factory.return_value
            api.consultar.return_value = self.orden(cita, "COMPLETED", self.captura())
            api.reembolsar.return_value = {
                "id": "REEMBOLSO-TEST",
                "status": "COMPLETED",
            }
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        nueva.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CANCELADA)
        self.assertEqual(cita.pago.estado, Pago.Estado.REEMBOLSADO)
        self.assertTrue(nueva.ocupacion.activa)

    def test_captura_con_importe_incorrecto_se_devuelve(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            api = factory.return_value
            api.consultar.return_value = self.orden(
                cita, "COMPLETED", self.captura(importe="1.00")
            )
            api.reembolsar.return_value = {
                "id": "REEMBOLSO-TEST",
                "status": "COMPLETED",
            }
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PAGO_FALLIDO)
        self.assertEqual(cita.pago.estado, Pago.Estado.REEMBOLSADO)

    def test_fallo_de_reembolso_se_reintentara(self):
        cita = self.con_orden()
        cancelar_cita(cita.pk, self.cliente)
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            api = factory.return_value
            api.consultar.return_value = self.orden(cita, "COMPLETED", self.captura())
            api.reembolsar.side_effect = PayPalError()
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.pago.estado, Pago.Estado.REEMBOLSO_PENDIENTE)
        self.assertFalse(cita.ocupacion.activa)

    def test_timeout_al_crear_no_confirma_reserva(self):
        cita = self.reservar()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory.return_value.crear.side_effect = PayPalError()
            with self.assertRaises(ValidationError):
                preparar_orden(cita.pk, self.cliente)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PENDIENTE)
        self.assertIsNone(cita.pago.orden_id)

    def test_cancelada_no_puede_iniciar_pago(self):
        cita = self.reservar()
        cancelar_cita(cita.pk, self.cliente)
        with self.assertRaises(ValidationError):
            preparar_orden(cita.pk, self.cliente)

    def test_captura_iniciada_fuera_del_plazo_no_confirma(self):
        cita = self.con_orden()
        expira = timezone.now() - timedelta(minutes=1)
        Cita.objects.filter(pk=cita.pk).update(expira_en=expira)
        Pago.objects.filter(cita=cita).update(
            captura_solicitada_en=expira + timedelta(seconds=5)
        )
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            api = factory.return_value
            api.consultar.return_value = self.orden(cita, "COMPLETED", self.captura())
            api.reembolsar.return_value = {
                "id": "REEMBOLSO-TEST",
                "status": "COMPLETED",
            }
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.PAGO_FALLIDO)
        self.assertEqual(cita.pago.estado, Pago.Estado.REEMBOLSADO)

    def test_consultar_una_cancelada_sin_cobro_no_reabre_pago(self):
        cita = self.con_orden()
        cancelar_cita(cita.pk, self.cliente)
        with patch("reservas.servicios.PayPalClient") as factory:
            factory.return_value.consultar.return_value = self.orden(cita, "CREATED")
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CANCELADA)
        self.assertEqual(cita.pago.estado, Pago.Estado.CERRADO)
        self.assertIsNone(cita.pago.proxima_revision)
