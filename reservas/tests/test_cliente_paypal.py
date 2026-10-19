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
