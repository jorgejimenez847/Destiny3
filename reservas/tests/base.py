import uuid
from decimal import Decimal
from barberos.tests.base import AgendaTestCase, momento
from reservas.models import Pago
from reservas.servicios import crear_cita, registrar_latido


class ReservaTestCase(AgendaTestCase):
    def setUp(self):
        self.turno()
        registrar_latido()

    def reservar(self, **kwargs):
        datos = dict(
            cliente=self.cliente,
            barbero_id=self.barbero.pk,
            servicio_id=self.servicio.pk,
            inicio=momento(9),
            solicitud_id=uuid.uuid4(),
            precio_esperado=Decimal("8.00"),
        )
        datos.update(kwargs)
        return crear_cita(**datos)

    def orden(self, cita, estado="APPROVED", captura=None):
        unidad = {
            "reference_id": str(cita.pk),
            "custom_id": str(cita.pk),
            "amount": {"value": "8.00", "currency_code": "USD"},
            "payee": {"merchant_id": "RECEPTOR-TEST"},
        }
        if captura:
            unidad["payments"] = {"captures": [captura]}
        return {
            "id": "ORDEN-TEST",
            "intent": "CAPTURE",
            "status": estado,
            "purchase_units": [unidad],
            "links": [
                {
                    "rel": "payer-action",
                    "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDEN-TEST",
                }
            ],
        }

    def captura(self, estado="COMPLETED", importe="8.00", moneda="USD"):
        return {
            "id": "CAPTURA-TEST",
            "status": estado,
            "amount": {"value": importe, "currency_code": moneda},
        }

    def con_orden(self):
        cita = self.reservar()
        pago = cita.pago
        pago.orden_id = "ORDEN-TEST"
        pago.estado = Pago.Estado.CREADO
        pago.receptor_id = "RECEPTOR-TEST"
        pago.save()
        return cita
