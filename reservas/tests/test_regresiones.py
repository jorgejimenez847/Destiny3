from datetime import timedelta
import uuid
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from reservas.models import Cita, Pago
from reservas.paypal import PayPalClient, PayPalError, enlace_aprobacion
from reservas.servicios import (
    _aplicar_resultado, cancelar_cita, expirar_retenciones, preparar_orden, procesar_pago,
)
from usuarios.models import Usuario
from .base import ReservaTestCase


class PresentacionReservaTests(ReservaTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cliente)

    def test_comprobante_no_disponible_muestra_una_pagina_util_sin_alterar_el_pago(self):
        cita = self.reservar()
        url = reverse("reservas:comprobante", args=[cita.pk])
        antes = Pago.objects.values().get(cita=cita)
        with patch("reservas.paypal.requests.Session") as paypal:
            respuesta = self.client.get(url)
        self.assertContains(respuesta, "Comprobante no disponible", status_code=409)
        self.assertContains(respuesta, "Volver a mi reserva", status_code=409)
        self.assertContains(respuesta, reverse("reservas:detalle", args=[cita.pk]), status_code=409)
        self.assertNotContains(respuesta, "Page not found", status_code=409)
        self.assertNotContains(respuesta, "Descargar comprobante", status_code=409)
        self.assertIn("no-store", respuesta["Cache-Control"])
        self.assertEqual(Pago.objects.values().get(cita=cita), antes)
        paypal.assert_not_called()

    def test_comprobante_ajeno_o_inexistente_no_revela_informacion(self):
        cita = self.reservar()
        otro = Usuario.objects.create_user(username="cliente_ajeno")
        self.client.force_login(otro)
        for pk in (cita.pk, uuid.uuid4()):
            with self.subTest(pk=pk):
                respuesta = self.client.get(reverse("reservas:comprobante", args=[pk]))
                self.assertContains(respuesta, "No encontramos un comprobante disponible para tu cuenta.", status_code=404)
                self.assertContains(respuesta, "Volver a mis reservas", status_code=404)
                self.assertNotContains(respuesta, "Page not found", status_code=404)
                self.assertNotContains(respuesta, str(cita.pk), status_code=404)
                self.assertNotContains(respuesta, cita.servicio_nombre, status_code=404)
                self.assertIn("private", respuesta["Cache-Control"])

    def test_cancelacion_y_expiracion_anteriores_no_muestran_aprobacion_pendiente(self):
        cita = self.con_orden()
        for estado, mensaje in (
            ("CANCELADA", "La reserva se canceló sin realizar un cobro."),
            ("EXPIRADA", "El plazo de pago venció sin realizar un cobro."),
        ):
            Cita.objects.filter(pk=cita.pk).update(estado=estado)
            Pago.objects.filter(cita=cita).update(estado="CERRADO", detalle="Falta aprobar la orden en PayPal Sandbox.")
            for actor, nombre in (
                (self.cliente, "reservas:detalle"),
                (self.admin, "reservas:gestion_detalle"),
                (self.usuario, "reservas:gestion_detalle"),
            ):
                self.client.force_login(actor)
                respuesta = self.client.get(reverse(nombre, args=[cita.pk]))
                self.assertContains(respuesta, mensaje)
                self.assertNotContains(respuesta, "Falta aprobar")
                self.assertNotContains(respuesta, "Sandbox")
            self.assertEqual(Pago.objects.get(cita=cita).detalle, "Falta aprobar la orden en PayPal Sandbox.")

    def test_cancelar_actualiza_detalle_y_elimina_revisiones_pendientes(self):
        cita = self.con_orden()
        Pago.objects.filter(cita=cita).update(
            detalle="Falta aprobar la orden en PayPal.",
            proxima_revision=timezone.now(),
            procesando_hasta=timezone.now() + timedelta(seconds=60),
        )
        cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
        pago = Pago.objects.get(cita=cita)
        self.assertEqual(pago.estado, "CERRADO")
        self.assertEqual(pago.detalle, "La reserva se canceló sin realizar un cobro.")
        self.assertIsNone(pago.proxima_revision)
        self.assertIsNone(pago.procesando_hasta)

    def test_expirar_actualiza_detalle_y_elimina_revisiones_pendientes(self):
        cita = self.con_orden()
        Cita.objects.filter(pk=cita.pk).update(expira_en=timezone.now() - timedelta(seconds=1))
        Pago.objects.filter(cita=cita).update(detalle="Falta aprobar la orden en PayPal.", proxima_revision=timezone.now())
        self.assertEqual(expirar_retenciones(), 1)
        pago = Pago.objects.get(cita=cita)
        self.assertEqual(pago.estado, "CERRADO")
        self.assertEqual(pago.detalle, "El plazo de pago venció sin realizar un cobro.")
        self.assertIsNone(pago.proxima_revision)


class RespuestasTardiasTests(ReservaTestCase):
    def test_error_al_crear_orden_no_reabre_un_pago_cancelado(self):
        for recuperable in (True, False):
            with self.subTest(recuperable=recuperable):
                cita = self.reservar()

                def error(*args):
                    cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
                    raise PayPalError(recuperable=recuperable)

                with patch("reservas.servicios.PayPalClient") as factory:
                    factory.return_value.crear.side_effect = error
                    from django.core.exceptions import ValidationError
                    with self.assertRaises(ValidationError):
                        preparar_orden(cita.pk, self.cliente)
                cita.refresh_from_db()
                self.assertEqual(cita.estado, "CANCELADA")
                self.assertFalse(cita.ocupacion.activa)
                self.assertEqual(cita.pago.estado, "CERRADO")
                self.assertIn("se canceló", cita.pago.detalle)

    def test_resultado_repetido_no_altera_pago_confirmado_ni_inicia_reembolso(self):
        cita = self.con_orden()
        orden = self.orden(cita, "COMPLETED", self.captura())
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar.return_value = orden
            procesar_pago(cita.pk)
        for estado in ("CONFIRMADA", "EN_ATENCION", "COMPLETADA", "NO_ASISTIO"):
            Cita.objects.filter(pk=cita.pk).update(estado=estado)
            antes = Pago.objects.values().get(cita=cita)
            eventos = cita.eventos.count()
            with patch("reservas.servicios.PayPalClient") as factory:
                _aplicar_resultado(cita.pk, orden)
                _aplicar_resultado(cita.pk, self.orden(cita, "CREATED"))
                factory.assert_not_called()
            cita.refresh_from_db()
            self.assertEqual(cita.estado, estado)
            self.assertEqual(Pago.objects.values().get(cita=cita), antes)
            self.assertEqual(cita.eventos.count(), eventos)


@override_settings(PAYPAL_MODE="sandbox", PAYPAL_CLIENT_ID="cliente-test", PAYPAL_CLIENT_SECRET="secreto-test")
class RespuestasPayPalTests(SimpleTestCase):
    def test_respuesta_oauth_invalida_se_trata_como_error_de_pago(self):
        for datos in (None, [], "texto", {}, {"access_token": []}, {"access_token": 12}, {"access_token": " "}):
            with self.subTest(datos=datos), patch("reservas.paypal.requests.Session") as factory:
                session = factory.return_value
                session.post.return_value.status_code = 200
                session.post.return_value.json.return_value = datos
                with self.assertRaises(PayPalError):
                    PayPalClient().consultar("ORDEN-TEST")
                session.request.assert_not_called()

    def test_enlaces_de_aprobacion_malformados_no_producen_error_500(self):
        for orden in (None, [], {"links": None}, {"links": "texto"},
                      {"links": [None, "texto"]},
                      {"links": [{"rel": "approve", "href": []}]},
                      {"links": [{"rel": "approve", "href": "https://[invalido"}]}):
            with self.subTest(orden=orden), self.assertRaises(PayPalError):
                enlace_aprobacion(orden)

    def test_enlace_sandbox_valido_se_conserva_entre_otros_invalidos(self):
        url = "https://www.sandbox.paypal.com/checkoutnow?token=ORDEN-TEST"
        self.assertEqual(enlace_aprobacion({"links": [None, {"rel": "approve", "href": url}]}), url)
