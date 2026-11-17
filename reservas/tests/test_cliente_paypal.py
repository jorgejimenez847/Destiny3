import secrets
from unittest.mock import patch
import requests
from django.test import SimpleTestCase, override_settings
from reservas.paypal import API, PayPalClient, PayPalError, enlace_aprobacion


class ClientePayPalTests(SimpleTestCase):
    def setUp(self):
        self.config = override_settings(
            PAYPAL_MODE="sandbox",
            PAYPAL_CLIENT_ID=secrets.token_urlsafe(20),
            PAYPAL_CLIENT_SECRET=secrets.token_urlsafe(30),
        )
        self.config.enable()
        self.addCleanup(self.config.disable)

    def test_solo_sandbox_y_sin_credenciales_rechazado(self):
        with override_settings(PAYPAL_MODE="live"), self.assertRaises(PayPalError):
            PayPalClient()
        with override_settings(PAYPAL_CLIENT_SECRET=""), self.assertRaises(PayPalError):
            PayPalClient()

    def test_oauth_y_get_usan_endpoints_sandbox(self):
        with patch("reservas.paypal.requests.Session") as factory:
            session = factory.return_value
            session.post.return_value.status_code = 200
            session.post.return_value.json.return_value = {
                "access_token": "token-ficticio"
            }
            session.request.return_value.status_code = 200
            session.request.return_value.json.return_value = {"id": "ORDEN-TEST"}
            api = PayPalClient()
            self.assertEqual(api.consultar("ORDEN-TEST")["id"], "ORDEN-TEST")
            self.assertEqual(session.post.call_args.args[0], API + "/v1/oauth2/token")
            self.assertEqual(
                session.request.call_args.args[1],
                API + "/v2/checkout/orders/ORDEN-TEST",
            )
            self.assertFalse(session.request.call_args.kwargs["allow_redirects"])

    def test_no_filtra_respuesta_de_error(self):
        sensible = secrets.token_urlsafe(30)
        with patch("reservas.paypal.requests.Session") as factory:
            factory.return_value.post.side_effect = requests.Timeout(sensible)
            with self.assertRaises(PayPalError) as contexto:
                PayPalClient().consultar("ORDEN-TEST")
            self.assertNotIn(sensible, str(contexto.exception))

    def test_no_admite_urls_externas_en_aprobacion(self):
        for url in [
            "https://www.paypal.com/checkoutnow",
            "https://sandbox.paypal.com.ejemplo.com/",
            "http://sandbox.paypal.com/",
            "https://user:pass@sandbox.paypal.com/",
        ]:
            with self.subTest(url=url), self.assertRaises(PayPalError):
                enlace_aprobacion({"links": [{"rel": "approve", "href": url}]})

    def test_rechaza_referencia_con_traversal(self):
        with self.assertRaises(PayPalError):
            PayPalClient().consultar("../otra-ruta")

    def test_reembolso_total_usa_identificador_estable_y_consulta_por_id(self):
        from types import SimpleNamespace
        import uuid
        pago = SimpleNamespace(captura_id="CAPTURA-TEST", solicitud_reembolsar=uuid.uuid4())
        with patch.object(PayPalClient, "_solicitar", return_value={}) as solicitar:
            api = PayPalClient()
            api.reembolsar(pago)
            solicitar.assert_called_with("POST", "/v2/payments/captures/CAPTURA-TEST/refund", data={}, request_id=pago.solicitud_reembolsar)
            api.consultar_reembolso("REF-TEST")
            solicitar.assert_called_with("GET", "/v2/payments/refunds/REF-TEST")
        with self.assertRaises(PayPalError):
            PayPalClient().consultar_reembolso("../otra-ruta")

    def test_recupera_referencia_de_reembolso_desde_la_orden(self):
        from types import SimpleNamespace
        pago = SimpleNamespace(orden_id="ORDEN-TEST", captura_id="CAPTURA-TEST", cita_id="CITA-TEST")
        unidad = {"reference_id": "CITA-TEST", "custom_id": "CITA-TEST",
                  "payments": {"captures": [{"id": "CAPTURA-TEST", "status": "REFUNDED"}], "refunds": [{"id": "REF-TEST"}]}}
        orden = {"id": "ORDEN-TEST", "purchase_units": [unidad]}
        with patch.object(PayPalClient, "consultar", return_value=orden), patch.object(PayPalClient, "consultar_reembolso", return_value={"status": "COMPLETED"}) as consultar:
            self.assertEqual(PayPalClient().buscar_reembolso(pago), {"status": "COMPLETED"})
            consultar.assert_called_once_with("REF-TEST")

    def test_orden_invalida_o_reembolsada_sin_referencia_no_autoriza_otro_post(self):
        from types import SimpleNamespace
        pago = SimpleNamespace(orden_id="ORDEN-TEST", captura_id="CAPTURA-TEST", cita_id="CITA-TEST")
        unidad = {"reference_id": "CITA-TEST", "custom_id": "CITA-TEST",
                  "payments": {"captures": [{"id": "CAPTURA-TEST", "status": "REFUNDED"}]}}
        orden = {"id": "ORDEN-TEST", "purchase_units": [unidad]}
        for dato in (None, {}, {"purchase_units": []}, orden, orden | {"id": "AJENA"}):
            with self.subTest(dato=dato), patch.object(PayPalClient, "consultar", return_value=dato), self.assertRaises(PayPalError):
                PayPalClient().buscar_reembolso(pago)
