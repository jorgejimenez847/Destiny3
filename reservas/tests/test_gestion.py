from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from html import unescape
import re
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from reservas.consultas import citas_autorizadas, resumen_dashboard
from reservas.models import Cita, Pago
from reservas.servicios import cancelar_cita, cambiar_estado_operativo, procesar_pago
from servicios.models import Servicio
from .base import ReservaTestCase, momento


@contextmanager
def hora_operativa(fecha):
    with patch("reservas.servicios.timezone", wraps=timezone) as reloj:
        reloj.now.return_value = fecha
        yield


class GestionReservaTests(ReservaTestCase):
    def confirmar_pago(self, cita):
        pago = cita.pago
        pago.orden_id = "ORDEN-" + cita.pk.hex
        pago.estado = Pago.Estado.CREADO
        pago.save()
        captura = self.captura(importe=str(cita.precio))
        captura["id"] = "CAP-" + cita.pk.hex
        orden = self.orden(cita, "COMPLETED", captura)
        orden["id"] = pago.orden_id
        orden["purchase_units"][0]["amount"]["value"] = str(cita.precio)
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar.return_value = orden
            procesar_pago(cita.pk)
        cita.refresh_from_db()
        return cita

    def detalle(self, cita):
        return reverse("reservas:gestion_detalle", args=[cita.pk])

    def actualizar(self, cita, estado, confirmar="on"):
        return self.client.post(
            reverse("reservas:estado", args=[cita.pk]),
            {"estado": estado, "confirmar": confirmar},
        )

    def test_admin_propietario_del_panel_sin_staff_consulta_reservas(self):
        cita = self.reservar()
        self.client.force_login(self.admin)
        self.assertFalse(self.admin.is_staff)
        self.assertContains(
            self.client.get(reverse("reservas:gestion")), self.detalle(cita)
        )
        self.assertEqual(self.client.get(self.detalle(cita)).status_code, 200)

    def test_barbero_ve_solo_su_agenda_aunque_manipule_filtros(self):
        propia = self.reservar()
        self.turno(barbero=self.otro)
        ajena = self.reservar(barbero_id=self.otro.pk)
        self.client.force_login(self.usuario)
        respuesta = self.client.get(
            reverse("usuarios:panel_barbero"), {"estado": "", "barbero": self.otro.pk}
        )
        self.assertEqual(list(respuesta.context["citas"]), [propia])
        self.assertNotContains(respuesta, self.detalle(ajena))
        self.assertEqual(self.client.get(self.detalle(ajena)).status_code, 404)
        self.assertEqual(self.actualizar(ajena, "EN_ATENCION").status_code, 404)

    def test_barbero_sin_citas_tiene_estado_vacio(self):
        self.client.force_login(self.otro_usuario)
        self.assertContains(
            self.client.get(reverse("usuarios:panel_barbero")), "No hay citas"
        )

    def test_cliente_y_anonimo_no_acceden_a_la_gestion(self):
        cita = self.reservar()
        for usuario, codigo in ((self.cliente, 403), (None, 302)):
            if usuario:
                self.client.force_login(usuario)
            else:
                self.client.logout()
            self.assertEqual(
                self.client.get(reverse("reservas:gestion")).status_code, codigo
            )
            self.assertEqual(self.client.get(self.detalle(cita)).status_code, codigo)
            self.assertEqual(self.actualizar(cita, "EN_ATENCION").status_code, codigo)

    def test_barbero_no_accede_a_reservas_globales(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("reservas:gestion")).status_code, 403)

    def test_filtros_por_estado_fecha_barbero_y_servicio(self):
        una = self.confirmar_pago(self.reservar())
        self.reservar(inicio=momento(10))
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse("reservas:gestion"),
            {
                "estado": "CONFIRMADA",
                "desde": "2030-01-07",
                "hasta": "2030-01-07",
                "barbero": self.barbero.pk,
                "servicio": self.servicio.pk,
                "q": "Corte",
            },
        )
        self.assertEqual(list(respuesta.context["citas"]), [una])

    def test_filtros_incorrectos_muestran_error_sin_listar_datos(self):
        self.reservar()
        self.client.force_login(self.admin)
        for filtros in (
            {"desde": "no-fecha"},
            {"desde": "2030-01-08", "hasta": "2030-01-07"},
            {"estado": "INVENTADO"},
            {"barbero": "999999"},
        ):
            with self.subTest(filtros=filtros):
                respuesta = self.client.get(reverse("reservas:gestion"), filtros)
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["filtros"].errors)
                self.assertEqual(len(respuesta.context["citas"]), 0)

    def test_paginacion_conserva_filtros(self):
        for semana in range(21):
            self.reservar(inicio=momento(9) + timedelta(days=7 * semana))
        self.client.force_login(self.admin)
        url = reverse("reservas:gestion")
        respuesta = self.client.get(url, {"q": "Corte"})
        self.assertContains(respuesta, "q=Corte&amp;pagina=2")
        self.assertEqual(
            len(self.client.get(url, {"q": "Corte", "pagina": 2}).context["citas"]), 1
        )

    def test_no_se_puede_confirmar_pago_con_un_cambio_de_estado(self):
        cita = self.reservar()
        self.client.force_login(self.admin)
        self.assertEqual(self.actualizar(cita, "CONFIRMADA").status_code, 400)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "PENDIENTE")
        self.assertEqual(cita.pago.estado, "NUEVO")

    def test_rechaza_atencion_sin_pago_y_antes_del_horario(self):
        cita = self.reservar()
        self.client.force_login(self.usuario)
        with hora_operativa(momento(9)):
            self.assertEqual(self.actualizar(cita, "EN_ATENCION").status_code, 400)
        self.confirmar_pago(cita)
        self.assertEqual(self.actualizar(cita, "EN_ATENCION").status_code, 400)

    def test_barbero_atencion_completada_y_resolicitud_sin_duplicar(self):
        cita = self.confirmar_pago(self.reservar())
        self.client.force_login(self.usuario)
        with hora_operativa(momento(10)), patch(
            "reservas.paypal.requests.Session"
        ) as paypal:
            self.assertEqual(self.actualizar(cita, "EN_ATENCION").status_code, 302)
            cantidad = cita.eventos.count()
            cambiar_estado_operativo(cita.pk, "EN_ATENCION", self.usuario)
            self.assertEqual(cita.eventos.count(), cantidad)
            self.assertEqual(self.actualizar(cita, "COMPLETADA").status_code, 302)
            self.assertEqual(self.actualizar(cita, "EN_ATENCION").status_code, 400)
            paypal.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "COMPLETADA")
        self.assertEqual(cita.eventos.last().actor, self.usuario)
        self.assertTrue(cita.ocupacion.activa)

    def test_admin_puede_registrar_no_asistio_con_responsable(self):
        cita = self.confirmar_pago(self.reservar())
        self.client.force_login(self.admin)
        with hora_operativa(momento(10)):
            self.assertEqual(self.actualizar(cita, "NO_ASISTIO").status_code, 302)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "NO_ASISTIO")
        self.assertEqual(cita.eventos.last().actor, self.admin)

    def test_cambio_de_estado_necesita_confirmacion_y_csrf(self):
        cita = self.confirmar_pago(self.reservar())
        self.client.force_login(self.admin)
        with hora_operativa(momento(10)):
            self.assertEqual(self.actualizar(cita, "EN_ATENCION", "").status_code, 400)
        url = reverse("reservas:estado", args=[cita.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(
            cliente.post(url, {"estado": "EN_ATENCION", "confirmar": "on"}).status_code,
            403,
        )

    def test_servicios_de_gestion_rechazan_actor_inactivo_o_anonimo(self):
        cita = self.confirmar_pago(self.reservar())
        self.usuario.is_active = False
        for actor in (self.usuario, AnonymousUser()):
            with self.assertRaises(PermissionDenied):
                citas_autorizadas(actor)
            with self.assertRaises(PermissionDenied):
                cambiar_estado_operativo(cita.pk, "EN_ATENCION", actor)

    def test_dashboard_vacio_y_acceso_exclusivo_admin(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("usuarios:panel_admin"))
        self.assertEqual(respuesta.context["total_reservas"], 0)
        self.assertEqual(respuesta.context["importe_confirmado"], Decimal("0.00"))
        self.assertContains(respuesta, "Importes registrados en USD de pagos confirmados.")
        self.assertNotContains(respuesta, "Sandbox")
        self.assertNotContains(respuesta, "demostración")
        for actor in (self.usuario, self.cliente):
            self.client.force_login(actor)
            self.assertEqual(
                self.client.get(reverse("usuarios:panel_admin")).status_code, 403
            )

    def test_dashboard_calcula_estados_pagos_servicios_y_barberos(self):
        self.confirmar_pago(self.reservar())
        self.confirmar_pago(self.reservar(inicio=momento(10)))
        self.turno(barbero=self.otro)
        self.confirmar_pago(self.reservar(barbero_id=self.otro.pk))
        cancelar_cita(
            self.reservar(inicio=momento(11)).pk, self.cliente, "Cambio de planes"
        )
        self.reservar(inicio=momento(14))
        datos = resumen_dashboard()
        self.assertEqual(datos["total_reservas"], 5)
        self.assertEqual(dict(datos["reservas_por_estado"])["Confirmada"], 3)
        self.assertEqual(dict(datos["reservas_por_estado"])["Cancelada"], 1)
        self.assertEqual(datos["importe_confirmado"], Decimal("24.00"))
        self.assertEqual(datos["pagos_confirmados"], 3)
        self.assertEqual(list(datos["servicios_populares"])[0]["total"], 3)
        self.assertEqual(
            {b.pk: b.total for b in datos["citas_por_barbero"]},
            {self.barbero.pk: 2, self.otro.pk: 1},
        )

    def test_dashboard_no_cuenta_reembolsos_importes_invalidos_o_estados_incoherentes(
        self,
    ):
        cita = self.confirmar_pago(self.reservar())
        for cambio in (
            {"estado": "REEMBOLSADO"},
            {"estado": "REEMBOLSO_PENDIENTE"},
            {"moneda_capturada": "EUR"},
            {"importe_capturado": "0.01"},
            {"captura_id": None},
            {"reembolso_id": "REEMBOLSO-TEST"},
        ):
            original = {
                "estado": "COMPLETADO",
                "moneda_capturada": "USD",
                "importe_capturado": "8.00",
                "captura_id": "CAP-" + cita.pk.hex,
                "reembolso_id": None,
            }
            Pago.objects.filter(cita=cita).update(**(original | cambio))
            self.assertEqual(resumen_dashboard()["importe_confirmado"], Decimal("0.00"))
        Pago.objects.filter(cita=cita).update(**original)
        Cita.objects.filter(pk=cita.pk).update(estado="PAGO_FALLIDO")
        self.assertEqual(resumen_dashboard()["importe_confirmado"], Decimal("0.00"))

    def test_dashboard_usa_precio_historico_aunque_cambie_el_catalogo(self):
        self.confirmar_pago(self.reservar())
        self.servicio.precio = "99.00"
        self.servicio.save()
        self.barbero.activo = False
        self.barbero.save()
        datos = resumen_dashboard()
        self.assertEqual(datos["importe_confirmado"], Decimal("8.00"))
        self.assertEqual(list(datos["citas_por_barbero"])[0].total, 1)

    def test_cancelacion_exige_motivo_y_no_altera_reserva_invalida(self):
        cita = self.reservar()
        self.client.force_login(self.cliente)
        for motivo in ("", "   ", "a" * 181):
            respuesta = self.client.post(
                reverse("reservas:cancelar", args=[cita.pk]), {"motivo": motivo}
            )
            self.assertEqual(respuesta.status_code, 400)
            cita.refresh_from_db()
            self.assertEqual(cita.estado, "PENDIENTE")

    def test_cancelacion_guarda_fecha_motivo_y_responsable_real(self):
        cita = self.reservar()
        self.client.force_login(self.cliente)
        antes = timezone.now()
        url = reverse("reservas:cancelar", args=[cita.pk])
        with patch("reservas.paypal.requests.Session") as paypal:
            for _ in range(2):
                self.assertEqual(
                    self.client.post(
                        url, {"motivo": "No podré asistir", "actor": self.admin.pk}
                    ).status_code,
                    302,
                )
            paypal.assert_not_called()
        cita.refresh_from_db()
        evento = cita.eventos.last()
        self.assertEqual(cita.estado, "CANCELADA")
        self.assertFalse(cita.ocupacion.activa)
        self.assertEqual(cita.eventos.count(), 2)
        self.assertIn("No podré asistir", evento.motivo)
        self.assertEqual(evento.actor, self.cliente)
        self.assertGreaterEqual(evento.fecha, antes)

    def test_no_cancela_pagadas_ni_inicia_reembolso(self):
        cita = self.confirmar_pago(self.reservar())
        self.client.force_login(self.cliente)
        with patch("reservas.paypal.requests.Session") as paypal:
            self.assertEqual(
                self.client.post(
                    reverse("reservas:cancelar", args=[cita.pk]),
                    {"motivo": "Cambio de planes"},
                ).status_code,
                302,
            )
            paypal.assert_not_called()
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CONFIRMADA")
        self.assertEqual(cita.pago.estado, "COMPLETADO")
        self.assertTrue(cita.comprobante_disponible)

    def test_cancelacion_respeta_captura_en_proceso(self):
        cita = self.reservar()
        Pago.objects.filter(cita=cita).update(
            captura_solicitada_en=timezone.now(), estado="VERIFICANDO"
        )
        with self.assertRaises(ValidationError):
            cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "PENDIENTE")
        self.assertTrue(cita.ocupacion.activa)

    def test_cancelacion_fuera_de_tiempo_expira_sin_registrar_cancelacion(self):
        cita = self.reservar()
        Cita.objects.filter(pk=cita.pk).update(
            expira_en=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.cliente)
        respuesta = self.client.post(
            reverse("reservas:cancelar", args=[cita.pk]),
            {"motivo": "Cambio de planes"},
            follow=True,
        )
        self.assertContains(respuesta, "El plazo de pago venció")
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "EXPIRADA")
        self.assertFalse(cita.eventos.filter(nuevo="CANCELADA").exists())

    def test_no_cancela_cita_que_ya_comenzo_aunque_la_retencion_este_mal_fechada(self):
        cita = self.reservar()
        Cita.objects.filter(pk=cita.pk).update(expira_en=momento(11))
        with hora_operativa(momento(10)), self.assertRaises(ValidationError):
            cancelar_cita(cita.pk, self.cliente, "Cambio de planes")

    def test_historial_muestra_responsable_y_motivo_sin_exponer_otras_cuentas(self):
        cita = self.reservar()
        cancelar_cita(cita.pk, self.cliente, "Cambio de planes")
        self.client.force_login(self.cliente)
        respuesta = self.client.get(reverse("reservas:detalle", args=[cita.pk]))
        self.assertContains(respuesta, "Cambio de planes")
        self.assertContains(respuesta, self.cliente.username)

    def test_ediciones_desde_administracion_no_cambian_datos_historicos(self):
        cita = self.confirmar_pago(self.reservar())
        originales = (
            cita.cliente_nombre,
            cita.servicio_nombre,
            cita.duracion_minutos,
            cita.precio,
            cita.pago.captura_id,
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                reverse("usuarios:editar", args=[self.cliente.pk]),
                {
                    "username": "cliente",
                    "first_name": "Nombre nuevo",
                    "email": "cliente@example.com",
                    "is_active": "on",
                },
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(
                reverse("servicios:editar", args=[self.servicio.pk]),
                {
                    "nombre": "Servicio nuevo",
                    "precio": "99.00",
                    "duracion_minutos": 60,
                    "activo": "on",
                },
            ).status_code,
            302,
        )
        cita.refresh_from_db()
        self.assertEqual(
            (
                cita.cliente_nombre,
                cita.servicio_nombre,
                cita.duracion_minutos,
                cita.precio,
                cita.pago.captura_id,
            ),
            originales,
        )
        self.assertTrue(cita.comprobante_disponible)

    def test_paginacion_del_barbero_conserva_el_filtro_inicial_de_hoy(self):
        self.servicio.duracion_minutos = 10
        self.servicio.save()
        for indice in range(21):
            minutos = indice * 10
            if minutos >= 180:
                minutos += 60
            self.reservar(inicio=momento(9) + timedelta(minutes=minutos))
        ajena_a_la_fecha = self.reservar(inicio=momento(9) + timedelta(days=7))
        self.client.force_login(self.usuario)
        url = reverse("usuarios:panel_barbero")
        with patch("reservas.consultas.timezone", wraps=timezone) as reloj:
            reloj.localdate.return_value = momento(9).date()
            primera = self.client.get(url)
            href = re.search(r'href="([^"]*pagina=2)"', primera.content.decode()).group(
                1
            )
            segunda = self.client.get(url + unescape(href))
        self.assertEqual(len(segunda.context["citas"]), 1)
        self.assertNotContains(segunda, self.detalle(ajena_a_la_fecha))

    def test_conflicto_de_estado_recarga_la_cita_y_las_opciones(self):
        cita = self.confirmar_pago(self.reservar())
        self.client.force_login(self.admin)

        def cambio_concurrente(*args):
            Cita.objects.filter(pk=cita.pk).update(estado="EN_ATENCION")
            raise ValidationError("La cita cambió mientras guardabas.")

        with hora_operativa(momento(10)), patch(
            "reservas.paneles.cambiar_estado_operativo", side_effect=cambio_concurrente
        ):
            respuesta = self.actualizar(cita, "NO_ASISTIO")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.context["cita"].estado, "EN_ATENCION")
        self.assertEqual(
            list(respuesta.context["form"].fields["estado"].choices),
            [("COMPLETADA", "Completada")],
        )
