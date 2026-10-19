"""Cliente REST de PayPal Sandbox. No registra credenciales ni respuestas completas."""

import re
from urllib.parse import urlparse
import requests
from django.conf import settings

API = "https://api-m.sandbox.paypal.com"


class PayPalError(Exception):
    def __init__(
        self,
        mensaje="PayPal Sandbox no está disponible. Inténtalo nuevamente.",
        *,
        recuperable=True,
        codigo="CONEXION",
    ):
        super().__init__(mensaje)
        self.recuperable = recuperable
        self.codigo = codigo


class PayPalClient:
    def __init__(self):
        if settings.PAYPAL_MODE != "sandbox":
            raise PayPalError(
                "Esta aplicación solo permite PayPal Sandbox.",
                recuperable=False,
                codigo="CONFIGURACION",
            )
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
            raise PayPalError(
                "Falta configurar PayPal Sandbox en el servidor.",
                recuperable=False,
                codigo="CONFIGURACION",
            )
        self.session = requests.Session()
        self.token = None

    def _solicitar(self, method, path, *, data=None, request_id=None):
        try:
            if self.token is None:
                respuesta = self.session.post(
                    API + "/v1/oauth2/token",
                    auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                    data={"grant_type": "client_credentials"},
                    timeout=(5, 15),
                    allow_redirects=False,
                )
                if respuesta.status_code != 200:
                    raise PayPalError(
                        "No se pudo autenticar con PayPal Sandbox.",
                        recuperable=respuesta.status_code >= 500
                        or respuesta.status_code == 429,
                        codigo="AUTENTICACION",
                    )
                self.token = respuesta.json().get("access_token")
                if not self.token:
                    raise PayPalError()
            headers = {
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
            if request_id:
                headers["PayPal-Request-Id"] = str(request_id)
            respuesta = self.session.request(
                method,
                API + path,
                json=data,
                headers=headers,
                timeout=(5, 15),
                allow_redirects=False,
            )
            if not 200 <= respuesta.status_code < 300:
                codigo = "RESPUESTA"
                try:
                    issues = [
                        d.get("issue") for d in respuesta.json().get("details", [])
                    ]
                except (ValueError, AttributeError, TypeError):
                    issues = []
                for conocido in [
                    "ORDER_NOT_APPROVED",
                    "INSTRUMENT_DECLINED",
                    "ORDER_ALREADY_CAPTURED",
                    "ORDER_ALREADY_COMPLETED",
                ]:
                    if conocido in issues:
                        codigo = conocido
                raise PayPalError(
                    "PayPal Sandbox no pudo completar la operación.",
                    recuperable=respuesta.status_code >= 500
                    or respuesta.status_code in [409, 429]
                    or codigo
                    in [
                        "ORDER_ALREADY_CAPTURED",
                        "ORDER_ALREADY_COMPLETED",
                        "ORDER_NOT_APPROVED",
                    ],
                    codigo=codigo,
                )
            resultado = respuesta.json()
            if not isinstance(resultado, dict):
                raise PayPalError()
            return resultado
        except (requests.RequestException, ValueError, TypeError):
            raise PayPalError() from None

    @staticmethod
    def _id(valor):
        if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,40}", valor):
            raise PayPalError(
                "La referencia del pago no es válida.",
                recuperable=False,
                codigo="REFERENCIA",
            )
        return valor

    def crear(self, cita, pago):
        base = settings.PAYPAL_RETURN_BASE
        return self._solicitar(
            "POST",
            "/v2/checkout/orders",
            request_id=pago.solicitud_crear,
            data={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": str(cita.pk),
                        "custom_id": str(cita.pk),
                        "description": "Destiny 3 - reserva de prueba",
                        "amount": {
                            "currency_code": "USD",
                            "value": format(cita.precio, ".2f"),
                        },
                    }
                ],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "brand_name": "Destiny 3 Sandbox",
                            "shipping_preference": "NO_SHIPPING",
                            "user_action": "PAY_NOW",
                            "return_url": f"{base}/reservas/{cita.pk}/retorno/",
                            "cancel_url": f"{base}/reservas/{cita.pk}/cancelar-pago/",
                        }
                    }
                },
            },
        )

    def consultar(self, orden_id):
        return self._solicitar("GET", "/v2/checkout/orders/" + self._id(orden_id))

    def capturar(self, pago):
        return self._solicitar(
            "POST",
            "/v2/checkout/orders/" + self._id(pago.orden_id) + "/capture",
            data={},
            request_id=pago.solicitud_capturar,
        )

    def reembolsar(self, pago):
        return self._solicitar(
            "POST",
            "/v2/payments/captures/" + self._id(pago.captura_id) + "/refund",
            data={},
            request_id=pago.solicitud_reembolsar,
        )


def enlace_aprobacion(orden):
    for link in orden.get("links", []):
        if link.get("rel") in ["approve", "payer-action"]:
            url = link.get("href", "")
            parsed = urlparse(url)
            if (
                parsed.scheme == "https"
                and parsed.hostname in ["www.sandbox.paypal.com", "sandbox.paypal.com"]
                and not parsed.username
                and not parsed.password
            ):
                return url
    raise PayPalError("PayPal no devolvió un enlace de aprobación Sandbox válido.")
