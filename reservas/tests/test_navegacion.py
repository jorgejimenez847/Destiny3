from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from django.test import Client
from django.urls import resolve, reverse

from barberos.models import Bloqueo, Horario
from reservas.models import Cita
from unittest.mock import patch
from .base import ReservaTestCase, momento


class Enlaces(HTMLParser):
    def __init__(self):
        super().__init__()
        self.destinos = []

    def handle_starttag(self, tag, atributos):
        atributos = dict(atributos)
        if tag == "a" and atributos.get("href"):
            self.destinos.append(("GET", atributos["href"]))
        if tag == "form":
            self.destinos.append(
                (atributos.get("method", "get").upper(), atributos.get("action", ""))
            )


class NavegacionTests(ReservaTestCase):
    def revisar(self, nombre, argumentos=(), parametros=None):
        url = reverse(nombre, args=argumentos)
        respuesta = self.client.get(url, parametros or {}, follow=True)
        self.assertEqual(respuesta.status_code, 200, (nombre, respuesta.redirect_chain))
        if respuesta.get("Content-Type", "").startswith("text/html"):
            parser = Enlaces()
            parser.feed(respuesta.content.decode())
            actual = respuesta.request["PATH_INFO"]
            for metodo, destino in parser.destinos:
                ruta = urlsplit(urljoin("http://testserver" + actual, destino))
                if ruta.netloc == "testserver":
                    with self.subTest(origen=nombre, destino=destino):
                        resolve(ruta.path)
                        if metodo == "GET":
                            llegada = self.client.get(
                                ruta.path + ("?" + ruta.query if ruta.query else ""),
                                follow=True,
                            )
                            self.assertEqual(
                                llegada.status_code, 200, (nombre, destino)
                            )
        return respuesta

    def test_rutas_publicas_y_recuperacion_de_contrasena(self):
        for nombre in (
            "home",
            "servicios:lista",
            "barberos:disponibilidad",
            "usuarios:login",
            "usuarios:registro",
            "usuarios:password_reset",
            "usuarios:password_reset_done",
            "usuarios:password_reset_complete",
        ):
            with self.subTest(nombre=nombre):
                self.revisar(nombre)
        self.assertEqual(
            self.client.get(
                reverse(
                    "usuarios:password_reset_confirm", args=["invalido", "invalido"]
                )
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/admin/", follow=True).status_code, 200)
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)

    def test_inventario_de_administracion_y_formularios_de_agenda(self):
        cita = self.reservar()
        bloqueo = Bloqueo.objects.create(
            barbero=self.barbero,
            inicio=momento(9) + timedelta(days=1),
            fin=momento(10) + timedelta(days=1),
            motivo="AUSENCIA",
        )
        turno = Horario.objects.filter(barbero=self.barbero).first()
        self.client.force_login(self.admin)
        for nombre, argumentos in (
            ("usuarios:panel_admin", ()),
            ("usuarios:gestion", ()),
            ("usuarios:crear", ()),
            ("usuarios:editar", (self.cliente.pk,)),
            ("servicios:gestion", ()),
            ("servicios:crear", ()),
            ("servicios:editar", (self.servicio.pk,)),
            ("barberos:gestion", ()),
            ("barberos:crear", ()),
            ("barberos:detalle", (self.barbero.pk,)),
            ("barberos:editar", (self.barbero.pk,)),
            ("barberos:horario_crear", (self.barbero.pk,)),
            ("barberos:horario_editar", (self.barbero.pk, turno.pk)),
            ("barberos:horario_eliminar", (self.barbero.pk, turno.pk)),
            ("barberos:bloqueo_crear", (self.barbero.pk,)),
            ("barberos:bloqueo_editar", (self.barbero.pk, bloqueo.pk)),
            ("barberos:bloqueo_eliminar", (self.barbero.pk, bloqueo.pk)),
            ("reservas:gestion", ()),
            ("reservas:gestion_detalle", (cita.pk,)),
        ):
            with self.subTest(nombre=nombre):
                self.revisar(nombre, argumentos)

    def test_panel_barbero_y_cliente_con_datos_asignados(self):
        cita = self.reservar()
        self.client.force_login(self.usuario)
        for nombre, argumentos in (
            ("usuarios:panel_barbero", ()),
            ("barberos:mi_perfil", ()),
            ("barberos:detalle", (self.barbero.pk,)),
            ("reservas:gestion_detalle", (cita.pk,)),
        ):
            self.revisar(nombre, argumentos)
        self.client.force_login(self.cliente)
        for nombre, argumentos in (
            ("usuarios:panel_cliente", ()),
            ("reservas:lista", ()),
            ("reservas:detalle", (cita.pk,)),
            ("reservas:cancelar_pago", (cita.pk,)),
        ):
            self.revisar(nombre, argumentos)

    def test_reserva_pago_pdf_cancelacion_e_historial_mediante_endpoints_reales(self):
        self.client.force_login(self.cliente)
        datos = {
            "servicio": self.servicio.pk,
            "barbero": self.barbero.pk,
            "inicio": momento(9).isoformat(),
        }
        self.revisar(
            "barberos:disponibilidad",
            parametros={
                "servicio": self.servicio.pk,
                "barbero": self.barbero.pk,
                "fecha": "2030-01-07",
            },
        )
        resumen = self.revisar("reservas:resumen", parametros=datos)
        self.assertEqual(
            self.client.post(
                reverse("reservas:confirmar"),
                {"seleccion": resumen.context["form"].initial["seleccion"]},
            ).status_code,
            302,
        )
        cita = Cita.objects.get()
        self.assertEqual(cita.estado, "PENDIENTE")
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            api = factory.return_value
            api.crear.return_value = self.orden(cita, "CREATED")
            respuesta = self.client.post(reverse("reservas:pagar", args=[cita.pk]))
            self.assertEqual(respuesta.status_code, 302)
            self.assertTrue(respuesta.url.startswith("https://www.sandbox.paypal.com/"))
            self.revisar("reservas:retorno", (cita.pk,), {"token": "ORDEN-TEST"})
            api.consultar.return_value = self.orden(cita, "APPROVED")
            api.capturar.return_value = self.orden(cita, "COMPLETED", self.captura())
            self.assertEqual(
                self.client.post(
                    reverse("reservas:verificar", args=[cita.pk]), follow=True
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(
                    reverse("reservas:comprobante", args=[cita.pk])
                ).status_code,
                200,
            )
            api.reembolsar.return_value = self.reembolso()
            respuesta = self.client.post(
                reverse("reservas:cancelar", args=[cita.pk]),
                {"motivo": "Cambio de planes"},
                follow=True,
            )
            self.assertContains(respuesta, "Reembolso confirmado. Reserva cancelada.")
            api.crear.assert_called_once()
            api.capturar.assert_called_once()
            api.reembolsar.assert_called_once()
        self.assertContains(self.revisar("reservas:lista"), "Cancelada")
        cita.refresh_from_db()
        self.assertFalse(cita.ocupacion.activa)

    def test_formularios_invalidos_no_producen_errores_500_y_mutaciones_exigen_post(
        self,
    ):
        cita = self.reservar()
        self.client.force_login(self.admin)
        for nombre, argumentos in (
            ("usuarios:crear", ()),
            ("usuarios:editar", (self.cliente.pk,)),
            ("servicios:crear", ()),
            ("servicios:editar", (self.servicio.pk,)),
            ("barberos:crear", ()),
            ("barberos:horario_crear", (self.barbero.pk,)),
            ("barberos:bloqueo_crear", (self.barbero.pk,)),
        ):
            with self.subTest(nombre=nombre):
                respuesta = self.client.post(reverse(nombre, args=argumentos), {})
                self.assertIn(respuesta.status_code, (200, 400))
        self.client.force_login(self.cliente)
        for nombre in ("reservas:pagar", "reservas:verificar", "reservas:cancelar"):
            self.assertEqual(
                self.client.get(reverse(nombre, args=[cita.pk])).status_code, 405
            )
        self.assertEqual(
            self.client.get(reverse("reservas:confirmar")).status_code, 405
        )
        self.assertEqual(self.client.get(reverse("usuarios:logout")).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.cliente)
        self.assertEqual(
            cliente.post(
                reverse("reservas:cancelar", args=[cita.pk]),
                {"motivo": "Cambio de planes"},
            ).status_code,
            403,
        )
