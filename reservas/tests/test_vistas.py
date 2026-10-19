from unittest.mock import patch
from django.core import signing
from django.test import Client
from django.urls import reverse
from reservas.models import Cita
from reservas.views import SALT
from .base import ReservaTestCase, momento


class VistasReservaTests(ReservaTestCase):
    def seleccion(self):
        self.client.force_login(self.cliente)
        return self.client.get(
            reverse("reservas:resumen"),
            {
                "servicio": self.servicio.pk,
                "barbero": self.barbero.pk,
                "inicio": momento(9).isoformat(),
            },
        )

    def test_resumen_no_retiene_y_confirmacion_si(self):
        r = self.seleccion()
        self.assertContains(r, "Revisa tu reserva")
        self.assertEqual(Cita.objects.count(), 0)
        token = r.context["form"].initial["seleccion"]
        r = self.client.post(reverse("reservas:confirmar"), {"seleccion": token})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Cita.objects.count(), 1)

    def test_confirmacion_doble_no_duplica(self):
        token = self.seleccion().context["form"].initial["seleccion"]
        for _ in range(2):
            self.client.post(reverse("reservas:confirmar"), {"seleccion": token})
        self.assertEqual(Cita.objects.count(), 1)

    def test_token_manipulado_o_de_otro_usuario_rechazado(self):
        token = self.seleccion().context["form"].initial["seleccion"]
        r = self.client.post(
            reverse("reservas:confirmar"), {"seleccion": token + "alterado"}
        )
        self.assertEqual(r.status_code, 302)
        datos = signing.loads(token, salt=SALT)
        datos["cliente"] = self.admin.pk
        r = self.client.post(
            reverse("reservas:confirmar"),
            {"seleccion": signing.dumps(datos, salt=SALT)},
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Cita.objects.exists())

    def test_precio_del_navegador_no_determina_importe(self):
        token = self.seleccion().context["form"].initial["seleccion"]
        self.client.post(
            reverse("reservas:confirmar"),
            {"seleccion": token, "precio": "0.01", "estado": "CONFIRMADA"},
        )
        cita = Cita.objects.get()
        self.assertEqual(str(cita.precio), "8.00")
        self.assertEqual(cita.estado, "PENDIENTE")

    def test_no_revela_reserva_de_otro_cliente(self):
        from usuarios.models import Usuario

        cita = self.reservar()
        otro = Usuario.objects.create_user(username="otra-persona", rol="CLIENTE")
        self.client.force_login(otro)
        for nombre, metodo in [
            ("detalle", self.client.get),
            ("pagar", self.client.post),
            ("verificar", self.client.post),
            ("cancelar", self.client.post),
        ]:
            with self.subTest(nombre=nombre):
                self.assertEqual(
                    metodo(reverse("reservas:" + nombre, args=[cita.pk])).status_code,
                    404,
                )

    def test_roles_no_cliente_y_anonimo(self):
        self.assertEqual(self.client.get(reverse("reservas:lista")).status_code, 302)
        for usuario in [self.admin, self.usuario]:
            self.client.force_login(usuario)
            self.assertEqual(
                self.client.get(reverse("reservas:lista")).status_code, 403
            )
            self.assertEqual(
                self.client.post(reverse("reservas:confirmar"), {}).status_code, 403
            )

    def test_mutaciones_solo_por_post_con_csrf(self):
        cita = self.reservar()
        self.client.force_login(self.cliente)
        for nombre in ["pagar", "cancelar", "verificar"]:
            self.assertEqual(
                self.client.get(
                    reverse("reservas:" + nombre, args=[cita.pk])
                ).status_code,
                405,
            )
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.cliente)
        self.assertEqual(
            c.post(reverse("reservas:cancelar", args=[cita.pk])).status_code, 403
        )

    def test_retorno_paypal_no_confirma_por_parametro_del_navegador(self):
        cita = self.con_orden()
        self.client.force_login(self.cliente)
        url = reverse("reservas:retorno", args=[cita.pk])
        self.assertEqual(self.client.get(url, {"token": "AJENA"}).status_code, 400)
        self.assertEqual(
            self.client.get(
                url, {"token": "ORDEN-TEST", "status": "COMPLETED"}
            ).status_code,
            302,
        )
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "PENDIENTE")

    def test_cancelar_pagina_no_modifica_hasta_confirmar(self):
        cita = self.reservar()
        self.client.force_login(self.cliente)
        self.assertContains(
            self.client.get(reverse("reservas:cancelar_pago", args=[cita.pk])),
            "Confirmar cancelación",
        )
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "PENDIENTE")
        self.client.post(reverse("reservas:cancelar", args=[cita.pk]))
        cita.refresh_from_db()
        self.assertEqual(cita.estado, "CANCELADA")

    def test_seleccion_invalida_y_lista_vacia(self):
        self.client.force_login(self.cliente)
        self.assertContains(
            self.client.get(reverse("reservas:lista")), "Todavía no tienes reservas"
        )
        self.assertEqual(
            self.client.get(
                reverse("reservas:resumen"), {"inicio": "incorrecto"}
            ).status_code,
            302,
        )

    def test_estado_confirmado_y_trazabilidad_en_pagina(self):
        cita = self.con_orden()
        from reservas.servicios import procesar_pago

        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda x: x
            factory.return_value.consultar.return_value = self.orden(
                cita, "COMPLETED", self.captura()
            )
            procesar_pago(cita.pk)
        self.client.force_login(self.cliente)
        self.assertContains(
            self.client.get(reverse("reservas:detalle", args=[cita.pk])),
            "Reserva confirmada",
        )

    def test_duracion_modificada_exige_revisar_resumen(self):
        token = self.seleccion().context["form"].initial["seleccion"]
        self.servicio.duracion_minutos = 50
        self.servicio.save()
        respuesta = self.client.post(
            reverse("reservas:confirmar"), {"seleccion": token}
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Cita.objects.exists())
