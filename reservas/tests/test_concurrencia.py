from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import time, timedelta
from threading import Barrier
from unittest.mock import patch
import uuid
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase
from django.utils import timezone
from barberos.models import PerfilBarbero, Horario, Ocupacion
from servicios.models import Servicio
from usuarios.models import Usuario
from reservas.models import Cita, Pago
from reservas.servicios import (
    crear_cita,
    cancelar_cita,
    expirar_retenciones,
    registrar_latido,
    procesar_pago,
)
from barberos.tests.base import momento


class ConcurrenciaReservaTests(TransactionTestCase):
    def setUp(self):
        self.cliente = Usuario.objects.create_user(
            username="cliente-uno", rol="CLIENTE"
        )
        self.otro = Usuario.objects.create_user(username="cliente-dos", rol="CLIENTE")
        u = Usuario.objects.create_user(username="barbero-pagos", rol="BARBERO")
        self.barbero = PerfilBarbero.objects.create(usuario=u, especialidad="Cortes")
        self.servicio = Servicio.objects.create(
            nombre="Corte", precio="8.00", duracion_minutos=30
        )
        self.barbero.servicios.add(self.servicio)
        Horario.objects.create(
            barbero=self.barbero, dia=0, inicio=time(9), fin=time(17)
        )
        registrar_latido()

    def reservar(self, cliente=None, solicitud=None):
        return crear_cita(
            cliente or self.cliente,
            self.barbero.pk,
            self.servicio.pk,
            momento(9),
            solicitud or uuid.uuid4(),
            Decimal("8.00"),
        )

    def paralelo(self, tareas):
        barrera = Barrier(len(tareas))

        def ejecutar(tarea):
            close_old_connections()
            try:
                barrera.wait(timeout=15)
                return tarea()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=len(tareas)) as executor:
            return list(executor.map(ejecutar, tareas))

    def test_dos_clientes_mismo_horario_solo_una_reserva(self):
        def intentar(cliente):
            try:
                self.reservar(cliente)
                return "creada"
            except ValidationError:
                return "rechazada"

        resultados = self.paralelo(
            [lambda: intentar(self.cliente), lambda: intentar(self.otro)]
        )
        self.assertCountEqual(resultados, ["creada", "rechazada"])
        self.assertEqual(Cita.objects.count(), 1)

    def test_doble_confirmacion_misma_seleccion(self):
        solicitud = uuid.uuid4()
        ids = self.paralelo(
            [
                lambda: self.reservar(solicitud=solicitud).pk,
                lambda: self.reservar(solicitud=solicitud).pk,
            ]
        )
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Ocupacion.objects.filter(activa=True).count(), 1)

    def test_expiracion_y_nueva_reserva_en_paralelo(self):
        cita = self.reservar()
        Cita.objects.filter(pk=cita.pk).update(
            expira_en=timezone.now() - timedelta(seconds=1)
        )
        self.paralelo([expirar_retenciones, lambda: self.reservar(self.otro)])
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.EXPIRADA)
        self.assertEqual(Ocupacion.objects.filter(activa=True).count(), 1)

    def test_cancelaciones_repetidas_son_idempotentes(self):
        cita = self.reservar()
        self.paralelo(
            [
                lambda: cancelar_cita(cita.pk, self.cliente),
                lambda: cancelar_cita(cita.pk, self.cliente),
            ]
        )
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CANCELADA)
        self.assertEqual(cita.eventos.count(), 2)

    def test_dos_verificaciones_no_generan_dos_capturas(self):
        cita = self.reservar()
        Pago.objects.filter(cita=cita).update(
            orden_id="ORDEN-TEST", estado=Pago.Estado.CREADO
        )
        unidad = {
            "reference_id": str(cita.pk),
            "custom_id": str(cita.pk),
            "amount": {"value": "8.00", "currency_code": "USD"},
        }
        orden = {
            "id": "ORDEN-TEST",
            "intent": "CAPTURE",
            "status": "APPROVED",
            "purchase_units": [unidad],
        }
        import copy

        capturada = copy.deepcopy(orden)
        capturada["status"] = "COMPLETED"
        capturada["purchase_units"][0]["payments"] = {
            "captures": [
                {
                    "id": "CAPTURA-TEST",
                    "status": "COMPLETED",
                    "amount": {"value": "8.00", "currency_code": "USD"},
                }
            ]
        }
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            api = factory.return_value
            api.consultar.return_value = orden
            api.capturar.return_value = capturada
            self.paralelo(
                [lambda: procesar_pago(cita.pk), lambda: procesar_pago(cita.pk)]
            )
            api.capturar.assert_called_once()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CONFIRMADA)
