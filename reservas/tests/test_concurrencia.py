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
    cambiar_estado_operativo,
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

    def confirmar_para_atencion(self):
        cita = self.reservar()
        Pago.objects.filter(cita=cita).update(
            orden_id="ORDEN-ESTADOS", estado=Pago.Estado.CREADO
        )
        orden = {
            "id": "ORDEN-ESTADOS",
            "intent": "CAPTURE",
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "reference_id": str(cita.pk),
                    "custom_id": str(cita.pk),
                    "amount": {"value": "8.00", "currency_code": "USD"},
                    "payments": {
                        "captures": [
                            {
                                "id": "CAPTURA-ESTADOS",
                                "status": "COMPLETED",
                                "amount": {"value": "8.00", "currency_code": "USD"},
                            }
                        ]
                    },
                }
            ],
        }
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar.return_value = orden
            procesar_pago(cita.pk)
        return cita

    def test_cambios_operativos_repetidos_en_paralelo_registran_un_solo_evento(self):
        cita = self.confirmar_para_atencion()
        actor = self.barbero.usuario
        with patch("reservas.servicios.timezone", wraps=timezone) as reloj:
            reloj.now.return_value = momento(10)
            self.paralelo(
                [
                    lambda: cambiar_estado_operativo(
                        cita.pk, Cita.Estado.EN_ATENCION, actor
                    ),
                    lambda: cambiar_estado_operativo(
                        cita.pk, Cita.Estado.EN_ATENCION, actor
                    ),
                ]
            )
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.EN_ATENCION)
        self.assertEqual(cita.eventos.filter(nuevo=Cita.Estado.EN_ATENCION).count(), 1)

    def test_transiciones_incompatibles_en_paralelo_solo_aplican_una(self):
        cita = self.confirmar_para_atencion()
        actor = self.barbero.usuario

        def intentar(estado):
            try:
                cambiar_estado_operativo(cita.pk, estado, actor)
                return "aplicada"
            except ValidationError:
                return "rechazada"

        with patch("reservas.servicios.timezone", wraps=timezone) as reloj:
            reloj.now.return_value = momento(10)
            resultados = self.paralelo(
                [
                    lambda: intentar(Cita.Estado.EN_ATENCION),
                    lambda: intentar(Cita.Estado.NO_ASISTIO),
                ]
            )
        self.assertCountEqual(resultados, ["aplicada", "rechazada"])
        self.assertEqual(
            cita.eventos.filter(
                nuevo__in=[Cita.Estado.EN_ATENCION, Cita.Estado.NO_ASISTIO]
            ).count(),
            1,
        )

    def test_cancelaciones_pagadas_simultaneas_crean_una_sola_devolucion(self):
        from django.db import connection
        from reservas.models import SolicitudCancelacion
        cita = self.confirmar_para_atencion()
        def devolver(pago):
            self.assertFalse(connection.in_atomic_block)
            return {"id": "REF-PARALELO", "status": "PENDING",
                    "amount": {"value": "8.00", "currency_code": "USD"},
                    "links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURA-ESTADOS"}]}
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.reembolsar.side_effect = devolver
            self.paralelo([lambda: cancelar_cita(cita.pk, self.cliente, "Cambio de planes"),
                           lambda: cancelar_cita(cita.pk, self.cliente, "Otro motivo")])
            factory.return_value.reembolsar.assert_called_once()
        cita.refresh_from_db()
        self.assertEqual(SolicitudCancelacion.objects.filter(cita=cita).count(), 1)
        self.assertTrue(cita.ocupacion.activa)
        self.assertEqual(cita.pago.estado, "REEMBOLSO_PENDIENTE")
        self.assertEqual(cita.eventos.filter(motivo__startswith="Solicitud de cancelación:").count(), 1)

    def test_consultas_de_reembolso_simultaneas_no_duplican_confirmacion(self):
        from django.db import connection
        cita = self.confirmar_para_atencion()
        respuesta = {"id": "REF-PARALELO", "status": "PENDING",
                     "amount": {"value": "8.00", "currency_code": "USD"},
                     "links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURA-ESTADOS"}]}
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            api = factory.return_value
            api.reembolsar.return_value = respuesta
            cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
            def consultar(referencia):
                self.assertFalse(connection.in_atomic_block)
                return respuesta | {"status": "COMPLETED"}
            api.consultar_reembolso.side_effect = consultar
            self.paralelo([lambda: procesar_pago(cita.pk), lambda: procesar_pago(cita.pk)])
            api.consultar_reembolso.assert_called_once()
            api.reembolsar.assert_called_once()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertFalse(cita.ocupacion.activa)
        self.assertEqual(cita.eventos.filter(nuevo="CANCELADA").count(), 1)

    def test_cancelacion_pendiente_impide_otra_reserva_y_se_libera_tras_el_reembolso(self):
        cita = self.confirmar_para_atencion()
        respuesta = {"id": "REF-AGENDA", "status": "PENDING",
                     "amount": {"value": "8.00", "currency_code": "USD"},
                     "links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURA-ESTADOS"}]}
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.reembolsar.return_value = respuesta
            cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
            def intentar():
                try:
                    self.reservar(self.otro)
                except ValidationError:
                    return "ocupado"
                return "reservado"
            self.assertEqual(self.paralelo([intentar, intentar]), ["ocupado", "ocupado"])
            factory.return_value.consultar_reembolso.return_value = respuesta | {"status": "COMPLETED"}
            procesar_pago(cita.pk)
        nueva = self.reservar(self.otro)
        self.assertNotEqual(nueva.pk, cita.pk)
        self.assertTrue(nueva.ocupacion.activa)
