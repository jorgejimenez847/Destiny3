from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from reservas.models import Cita, Pago, SolicitudCancelacion
from reservas.paypal import PayPalError
from reservas.servicios import (
    _aplicar_resultado,
    cancelar_cita,
    cambiar_estado_operativo,
    ejecutar_ciclo,
    estados_operativos_permitidos,
    procesar_pago,
)
from usuarios.models import Usuario
from .base import ReservaTestCase


@contextmanager
def reloj(ahora):
    with patch("reservas.servicios.timezone", wraps=timezone) as servicios, patch(
        "reservas.models.timezone", wraps=timezone
    ) as modelos:
        servicios.now.return_value = modelos.now.return_value = ahora
        yield


class CancelacionPagadaTests(ReservaTestCase):
    def confirmada(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar.return_value = self.orden(
                cita, "COMPLETED", self.captura()
            )
            procesar_pago(cita.pk)
        return Cita.objects.select_related("pago", "ocupacion").get(pk=cita.pk)

    def solicitar(self, cita, resultado=None, error=None, motivo="Cambio de planes"):
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            api = factory.return_value
            if error:
                api.reembolsar.side_effect = error
            else:
                api.reembolsar.return_value = (
                    resultado if resultado is not None else self.reembolso()
                )
            cancelar_cita(cita.pk, self.cliente, motivo)
        cita.refresh_from_db()
        return api

    def test_confirmada_con_mas_de_24_horas_reembolsa_y_libera_con_historial(self):
        cita = self.confirmada()
        originales = (
            cita.servicio_nombre,
            cita.barbero_nombre,
            cita.cliente_nombre,
            cita.precio,
            cita.pago.captura_id,
            cita.pago.solicitud_reembolsar,
        )
        antes = timezone.now()
        api = self.solicitar(cita)
        solicitud = cita.cancelacion
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertFalse(cita.ocupacion.activa)
        self.assertEqual(cita.pago.estado, "REEMBOLSADO")
        self.assertEqual(cita.pago.reembolso_id, "REEMBOLSO-TEST")
        self.assertEqual(cita.pago.reembolso_estado, "COMPLETED")
        self.assertIsNotNone(cita.pago.reembolso_finalizado_en)
        self.assertEqual(solicitud.motivo, "Cambio de planes")
        self.assertEqual(solicitud.solicitante, self.cliente)
        self.assertGreaterEqual(solicitud.solicitada_en, antes)
        self.assertEqual(solicitud.finalizada_en, cita.pago.reembolso_finalizado_en)
        self.assertEqual(cita.eventos.last().anterior, "CONFIRMADA")
        self.assertEqual(cita.eventos.last().nuevo, "CANCELADA")
        self.assertEqual(cita.eventos.last().actor, self.cliente)
        self.assertEqual(
            originales,
            (
                cita.servicio_nombre,
                cita.barbero_nombre,
                cita.cliente_nombre,
                cita.precio,
                cita.pago.captura_id,
                cita.pago.solicitud_reembolsar,
            ),
        )
        api.reembolsar.assert_called_once()
        self.assertFalse(cita.comprobante_disponible)
        self.reservar()

    def test_limite_exacto_de_24_horas_en_panama_permitido(self):
        cita = self.confirmada()
        ahora = cita.inicio - timedelta(hours=24)
        self.assertIsNotNone(ahora.tzinfo)
        with reloj(ahora):
            self.assertTrue(cita.puede_cancelarse)
            self.solicitar(cita)
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertEqual(cita.cancelacion.solicitada_en, ahora)

    def test_menos_de_24_horas_incluso_un_microsegundo_se_rechaza(self):
        cita = self.confirmada()
        for falta in (
            timedelta(hours=24) - timedelta(microseconds=1),
            timedelta(hours=23),
            timedelta(0),
        ):
            with self.subTest(falta=falta), reloj(cita.inicio - falta), patch(
                "reservas.servicios.PayPalClient"
            ) as factory:
                self.assertFalse(cita.puede_cancelarse)
                with self.assertRaises(ValidationError):
                    cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
                factory.assert_not_called()
        self.assertFalse(SolicitudCancelacion.objects.exists())
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CONFIRMADA")
        self.assertTrue(cita.ocupacion.activa)

    def test_citas_en_atencion_completadas_no_asistidas_y_fallidas_no_cancelables(self):
        cita = self.confirmada()
        for estado in ("EN_ATENCION", "COMPLETADA", "NO_ASISTIO", "PAGO_FALLIDO"):
            Cita.objects.filter(pk=cita.pk).update(estado=estado)
            cita.refresh_from_db()
            self.assertFalse(cita.puede_cancelarse)
            with self.assertRaises(ValidationError), patch(
                "reservas.servicios.PayPalClient"
            ) as factory:
                cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
            factory.assert_not_called()

    def test_solo_cliente_propietario_activo_puede_cancelar(self):
        cita = self.confirmada()
        otro = Usuario.objects.create_user(username="cliente-sin-permiso")
        inactivo = Usuario.objects.get(pk=self.cliente.pk)
        inactivo.is_active = False
        for actor in (otro, self.admin, self.usuario, inactivo, AnonymousUser()):
            with self.subTest(actor=str(actor)), self.assertRaises(PermissionDenied):
                cancelar_cita(cita.pk, actor, "Cambio de planes")
        self.assertFalse(SolicitudCancelacion.objects.exists())

    def test_exige_motivo_y_pago_verificado_sin_operaciones_incompatibles(self):
        cita = self.confirmada()
        for motivo in (None, "", "  ", "x" * 181):
            with self.subTest(motivo=motivo), self.assertRaises(ValidationError):
                cancelar_cita(cita.pk, self.cliente, motivo)
        original = Pago.objects.values().get(cita=cita)
        for cambio in (
            {"importe_capturado": "0.01"},
            {"moneda_capturada": "EUR"},
            {"captura_id": None},
            {"captura_id": "../otra"},
            {"orden_id": None},
            {"estado": "VERIFICANDO"},
            {"reembolso_id": "OTRO"},
            {"procesando_hasta": timezone.now() + timedelta(minutes=1)},
        ):
            Pago.objects.filter(cita=cita).update(**(original | cambio))
            with self.subTest(cambio=cambio), self.assertRaises(ValidationError):
                cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
        self.assertFalse(SolicitudCancelacion.objects.exists())

    def test_reembolso_pendiente_conserva_horario_y_no_permite_atencion_ni_pdf(self):
        cita = self.confirmada()
        self.solicitar(cita, self.reembolso("PENDING"))
        self.assertEqual(cita.estado, "CONFIRMADA")
        self.assertTrue(cita.ocupacion.activa)
        self.assertTrue(cita.cancelacion_pendiente)
        self.assertIsNone(cita.cancelacion.finalizada_en)
        self.assertFalse(cita.puede_cancelarse)
        self.assertFalse(cita.comprobante_disponible)
        with self.assertRaises(ValidationError):
            self.reservar()
        with reloj(cita.inicio):
            self.assertEqual(estados_operativos_permitidos(cita, self.admin), [])
            with self.assertRaises(ValidationError):
                cambiar_estado_operativo(cita.pk, "EN_ATENCION", self.admin)

    def test_pendiente_se_consulta_por_referencia_y_finaliza_aunque_ya_falten_menos_de_24_horas(
        self,
    ):
        cita = self.confirmada()
        with reloj(cita.inicio - timedelta(hours=24)):
            self.solicitar(cita, self.reembolso("PENDING"))
        with reloj(cita.inicio - timedelta(hours=23)), patch(
            "reservas.servicios.PayPalClient"
        ) as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar_reembolso.return_value = self.reembolso()
            procesar_pago(cita.pk)
            factory.return_value.reembolsar.assert_not_called()
            factory.return_value.consultar_reembolso.assert_called_once_with(
                "REEMBOLSO-TEST"
            )
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertFalse(cita.ocupacion.activa)

    def test_timeout_no_se_interpreta_como_devolucion_y_se_recupera_sin_otro_post(self):
        cita = self.confirmada()
        self.solicitar(cita, error=PayPalError())
        solicitud = cita.cancelacion.pk
        self.assertTrue(cita.ocupacion.activa)
        self.assertEqual(cita.pago.estado, "REEMBOLSO_PENDIENTE")
        self.assertIsNone(cita.pago.reembolso_id)
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.buscar_reembolso.return_value = self.reembolso()
            procesar_pago(cita.pk)
            factory.return_value.reembolsar.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertEqual(cita.cancelacion.pk, solicitud)

    def test_reintento_sin_reembolso_local_usa_mismo_identificador(self):
        cita = self.confirmada()
        identificadores = []

        def fallo(pago):
            identificadores.append(pago.solicitud_reembolsar)
            raise PayPalError()

        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            api = factory.return_value
            api.buscar_reembolso.return_value = None
            api.reembolsar.side_effect = fallo
            cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
            procesar_pago(cita.pk)
        self.assertEqual(len(identificadores), 2)
        self.assertEqual(identificadores[0], identificadores[1])

    def test_respuestas_fallidas_incompletas_o_ajenas_no_cancelan(self):
        cita = self.confirmada()
        resultados = [
            self.reembolso("FAILED"),
            self.reembolso("CANCELLED"),
            {},
            None,
            {"id": "OTRO", "status": "COMPLETED"},
            self.reembolso(importe="0.01"),
            self.reembolso(captura="CAPTURA-AJENA"),
        ]
        self.solicitar(cita, self.reembolso("PENDING"))
        for resultado in resultados:
            with self.subTest(resultado=resultado), patch(
                "reservas.servicios.PayPalClient"
            ) as factory:
                factory._id.side_effect = lambda valor: valor
                factory.return_value.consultar_reembolso.return_value = resultado
                procesar_pago(cita.pk)
            cita.refresh_from_db()
            self.assertEqual(cita.estado, "CONFIRMADA")
            self.assertEqual(cita.pago.estado, "REEMBOLSO_PENDIENTE")
            self.assertTrue(cita.ocupacion.activa)
            self.assertIsNone(cita.cancelacion.finalizada_en)

    def test_repetir_solicitud_no_modifica_motivo_ni_lanza_otra_devolucion(self):
        cita = self.confirmada()
        self.solicitar(cita, self.reembolso("PENDING"))
        eventos = cita.eventos.count()
        with patch("reservas.servicios.PayPalClient") as factory:
            for _ in range(3):
                cancelar_cita(cita.pk, self.cliente, "Otro motivo")
            factory.assert_not_called()
        self.assertEqual(cita.eventos.count(), eventos)
        self.assertEqual(cita.cancelacion.motivo, "Cambio de planes")
        self.assertEqual(SolicitudCancelacion.objects.count(), 1)

    def test_respuesta_de_captura_repetida_no_pisa_cancelacion_pendiente(self):
        cita = self.confirmada()
        self.solicitar(cita, self.reembolso("PENDING"))
        antes = Pago.objects.values().get(cita=cita)
        _aplicar_resultado(cita.pk, self.orden(cita, "COMPLETED", self.captura()))
        self.assertEqual(Pago.objects.values().get(cita=cita), antes)

    def test_procesador_finaliza_reembolso_sin_visitas_del_cliente(self):
        cita = self.confirmada()
        self.solicitar(cita, self.reembolso("PENDING"))
        Pago.objects.filter(cita=cita).update(
            proxima_revision=timezone.now() - timedelta(seconds=1)
        )
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar_reembolso.return_value = self.reembolso()
            ejecutar_ciclo()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertFalse(cita.ocupacion.activa)

    def test_pdf_se_conserva_antes_de_solicitar_y_se_rechaza_despues(self):
        cita = self.confirmada()
        self.client.force_login(self.cliente)
        url = reverse("reservas:comprobante", args=[cita.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.solicitar(cita)
        self.assertEqual(self.client.get(url).status_code, 409)
        self.assertNotContains(
            self.client.get(reverse("reservas:lista")), "Descargar comprobante"
        )

    def test_interfaz_muestra_politica_motivo_y_resultado_sin_promesas_prematuras(self):
        cita = self.confirmada()
        self.client.force_login(self.cliente)
        url = reverse("reservas:cancelar", args=[cita.pk])
        self.assertContains(
            self.client.get(reverse("reservas:detalle", args=[cita.pk])),
            "Cancelar reserva",
        )
        self.assertContains(
            self.client.get(reverse("reservas:cancelar_pago", args=[cita.pk])),
            "24 horas",
        )
        self.assertEqual(self.client.post(url, {"motivo": ""}).status_code, 400)
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.reembolsar.return_value = self.reembolso("PENDING")
            respuesta = self.client.post(
                url, {"motivo": "Cambio de planes", "estado": "CANCELADA"}, follow=True
            )
        self.assertContains(respuesta, "Cancelación en proceso")
        self.assertNotContains(
            respuesta, "La reserva se canceló y su horario quedó libre."
        )
        self.assertContains(
            self.client.get(reverse("reservas:lista")), "Cancelación en proceso"
        )
        self.assertNotContains(respuesta, "Sandbox")

    def test_cliente_ajeno_no_puede_cancelar_mediante_url(self):
        cita = self.confirmada()
        otro = Usuario.objects.create_user(username="otro-cliente-http")
        self.client.force_login(otro)
        self.assertEqual(
            self.client.post(
                reverse("reservas:cancelar", args=[cita.pk]),
                {"motivo": "Cambio de planes"},
            ).status_code,
            404,
        )

    def test_referencia_duplicada_no_produce_500_y_se_reconcilia_sin_otro_post(self):
        from .base import momento

        cita = self.confirmada()
        otra = self.reservar(inicio=momento(10))
        Pago.objects.filter(cita=otra).update(reembolso_id="REEMBOLSO-TEST")
        self.solicitar(cita)
        self.assertEqual(cita.estado, "CONFIRMADA")
        self.assertTrue(cita.ocupacion.activa)
        self.assertEqual(cita.pago.estado, "REEMBOLSO_PENDIENTE")
        self.assertIsNone(cita.pago.reembolso_id)
        self.assertIsNone(cita.pago.procesando_hasta)
        self.assertIn("necesita revisión", cita.pago.detalle)
        self.assertEqual(Pago.objects.get(cita=otra).reembolso_id, "REEMBOLSO-TEST")
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.buscar_reembolso.return_value = self.reembolso(
                referencia="REF-RECUPERADO"
            )
            procesar_pago(cita.pk)
            factory.return_value.reembolsar.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")

    def test_reembolso_sandbox_con_host_oficial_alternativo(self):
        cita = self.confirmada()
        respuesta = self.reembolso()
        respuesta["links"][0]["href"] = respuesta["links"][0]["href"].replace(
            "api-m.sandbox", "api.sandbox"
        )
        self.solicitar(cita, respuesta)
        self.assertEqual(cita.estado, "CANCELADA")

    def test_reembolso_con_moneda_o_vinculo_incorrectos_no_libera_el_horario(self):
        cita = self.confirmada()
        self.solicitar(cita, self.reembolso("PENDING"))
        for respuesta in (
            self.reembolso() | {"amount": {"value": "8.00", "currency_code": "EUR"}},
            self.reembolso()
            | {
                "links": [
                    {
                        "rel": "up",
                        "href": "https://api-m.paypal.com/v2/payments/captures/CAPTURA-TEST",
                    }
                ]
            },
            self.reembolso() | {"links": None},
        ):
            with patch("reservas.servicios.PayPalClient") as factory:
                factory._id.side_effect = lambda valor: valor
                factory.return_value.consultar_reembolso.return_value = respuesta
                procesar_pago(cita.pk)
            cita.refresh_from_db()
            self.assertEqual(cita.estado, "CONFIRMADA")
            self.assertTrue(cita.ocupacion.activa)

    def test_respuesta_de_un_intento_antiguo_no_sobrescribe_otro_en_proceso(self):
        from reservas.servicios import _guardar_reembolso

        cita = self.confirmada()
        self.solicitar(cita, self.reembolso("PENDING"))
        intento = timezone.now() + timedelta(seconds=120)
        Pago.objects.filter(cita=cita).update(procesando_hasta=intento)
        antes = Pago.objects.values().get(cita=cita)
        _guardar_reembolso(
            cita.pk, intento - timedelta(seconds=1), ("REEMBOLSO-TEST", "COMPLETED"), ""
        )
        self.assertEqual(Pago.objects.values().get(cita=cita), antes)

    def test_solicitudes_pendientes_y_reembolsos_tardios_no_se_confunden(self):
        cita = self.con_orden()
        cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar.return_value = self.orden(
                cita, "COMPLETED", self.captura()
            )
            factory.return_value.reembolsar.return_value = self.reembolso("PENDING")
            procesar_pago(cita.pk)
            self.assertFalse(SolicitudCancelacion.objects.filter(cita=cita).exists())
            factory.return_value.consultar_reembolso.return_value = self.reembolso()
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertEqual(cita.pago.estado, "REEMBOLSADO")
        self.assertFalse(cita.ocupacion.activa)
        self.assertFalse(SolicitudCancelacion.objects.filter(cita=cita).exists())
