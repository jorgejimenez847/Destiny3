from datetime import timedelta
from importlib import import_module
from io import BytesIO
import uuid
from unittest.mock import patch

from django.apps import apps
from django.db import connection
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from barberos.models import Ocupacion
from reservas.models import Cita, EventoCita, Pago
from reservas.servicios import procesar_pago
from usuarios.models import Usuario
from .base import ReservaTestCase, momento


class ComprobanteTests(ReservaTestCase):
    def setUp(self):
        super().setUp()
        self.cliente.first_name = "Ana María"
        self.cliente.last_name = "Pérez"
        self.cliente.save()
        self.client.force_login(self.cliente)

    def confirmada(self):
        cita = self.con_orden()
        with patch("reservas.servicios.PayPalClient") as factory:
            factory._id.side_effect = lambda valor: valor
            factory.return_value.consultar.return_value = self.orden(cita, "COMPLETED", self.captura())
            procesar_pago(cita.pk)
        return Cita.objects.select_related("pago").get(pk=cita.pk)

    def url(self, cita):
        return reverse("reservas:comprobante", args=[cita.pk])

    def texto_pdf(self, respuesta):
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertTrue(respuesta.content.startswith(b"%PDF-"))
        lector = PdfReader(BytesIO(respuesta.content), strict=True)
        return lector, "\n".join(pagina.extract_text() for pagina in lector.pages)

    def sin_cambios(self, cita):
        return (
            Cita.objects.values().get(pk=cita.pk),
            Pago.objects.values().get(cita=cita),
            list(EventoCita.objects.filter(cita=cita).values()),
            list(Ocupacion.objects.values()),
        )

    def test_pdf_valido_con_datos_completos_y_descarga_privada(self):
        cita = self.confirmada()
        respuesta = self.client.get(self.url(cita))
        lector, texto = self.texto_pdf(respuesta)
        self.assertEqual(len(lector.pages), 1)
        for valor in (
            "DESTINY 3", "Comprobante de reserva", cita.numero_comprobante,
            "Ana María Pérez", cita.servicio_nombre, cita.barbero_nombre,
            "07/01/2030", "09:00 - 09:30", "30 minutos", "USD 8.00",
            "Confirmado", "CAPTURA-TEST", "Fecha de emisión", "No es una factura fiscal",
        ):
            with self.subTest(valor=valor):
                self.assertIn(valor, texto)
        for aviso in ("demostración", "Sandbox", "Sin dinero real"):
            self.assertNotIn(aviso, texto)
        self.assertEqual(lector.metadata.title, "Comprobante de reserva")
        self.assertIn(f'attachment; filename="comprobante-{cita.numero_comprobante}.pdf"', respuesta["Content-Disposition"])
        self.assertIn("private", respuesta["Cache-Control"])
        self.assertIn("no-store", respuesta["Cache-Control"])
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")

    def test_descargas_repetidas_no_mutan_reserva_pago_ni_eventos(self):
        cita = self.confirmada()
        antes = self.sin_cambios(cita)
        with patch("reservas.paypal.requests.Session") as paypal:
            primera = self.texto_pdf(self.client.get(self.url(cita)))[1]
            segunda = self.texto_pdf(self.client.get(self.url(cita)))[1]
        paypal.assert_not_called()
        self.assertEqual(primera, segunda)
        self.assertEqual(antes, self.sin_cambios(cita))
        self.assertEqual(cita.numero_comprobante, f"D3-{cita.pk.hex.upper()}")

    def test_solo_cliente_propietario_puede_descargar(self):
        cita = self.confirmada()
        otro_cliente = Usuario.objects.create_user(username="otra_persona")
        self.client.force_login(otro_cliente)
        self.assertEqual(self.client.get(self.url(cita)).status_code, 404)
        for usuario in (self.admin, self.usuario):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.url(cita)).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url(cita)).status_code, 302)

    def test_identificador_inexistente_no_revela_datos(self):
        self.assertEqual(self.client.get(reverse("reservas:comprobante", args=[uuid.uuid4()])).status_code, 404)

    def test_descarga_solo_acepta_get(self):
        cita = self.confirmada()
        self.assertEqual(self.client.post(self.url(cita)).status_code, 405)

    def test_pendiente_sin_captura_no_tiene_comprobante(self):
        cita = self.reservar()
        self.assertEqual(self.client.get(self.url(cita)).status_code, 409)
        self.assertNotContains(self.client.get(reverse("reservas:detalle", args=[cita.pk])), "Descargar comprobante")
        self.assertNotContains(self.client.get(reverse("reservas:lista")), "Descargar comprobante")

    def test_estados_no_confirmados_rechazan_pdf_y_ocultan_botones(self):
        cita = self.confirmada()
        for estado in ("PENDIENTE", "CANCELADA", "EXPIRADA", "PAGO_FALLIDO"):
            Cita.objects.filter(pk=cita.pk).update(estado=estado)
            with self.subTest(estado=estado):
                self.assertEqual(self.client.get(self.url(cita)).status_code, 409)
                self.assertNotContains(self.client.get(reverse("reservas:detalle", args=[cita.pk])), "Descargar comprobante")
                self.assertNotContains(self.client.get(reverse("reservas:lista")), "Descargar comprobante")

    def test_pago_sin_verificar_o_reembolsado_no_tiene_pdf(self):
        cita = self.confirmada()
        for estado in Pago.Estado.values:
            if estado == Pago.Estado.COMPLETADO:
                continue
            Pago.objects.filter(cita=cita).update(estado=estado)
            with self.subTest(estado=estado):
                self.assertEqual(self.client.get(self.url(cita)).status_code, 409)
                self.assertNotContains(self.client.get(reverse("reservas:lista")), "Descargar comprobante")

    def test_estado_confirmado_no_basta_sin_importe_moneda_y_referencia_verificados(self):
        cita = self.confirmada()
        pago_original = {"captura_id": cita.pago.captura_id, "importe_capturado": cita.precio,
                         "moneda_capturada": "USD", "reembolso_id": None}
        for cambio in ({"captura_id": None}, {"importe_capturado": None},
                       {"importe_capturado": "0.01"}, {"moneda_capturada": "EUR"},
                       {"reembolso_id": "REEMBOLSO-TEST"}):
            Pago.objects.filter(cita=cita).update(**(pago_original | cambio))
            with self.subTest(cambio=cambio):
                self.assertEqual(self.client.get(self.url(cita)).status_code, 409)

    def test_confirmada_muestra_boton_en_detalle_y_lista(self):
        cita = self.confirmada()
        for url in (reverse("reservas:detalle", args=[cita.pk]), reverse("reservas:lista")):
            respuesta = self.client.get(url)
            self.assertContains(respuesta, "Descargar comprobante")
            self.assertContains(respuesta, self.url(cita))

    def test_comprobante_sigue_disponible_despues_de_la_atencion(self):
        cita = self.confirmada()
        for estado in ("EN_ATENCION", "COMPLETADA", "NO_ASISTIO"):
            Cita.objects.filter(pk=cita.pk).update(estado=estado)
            with self.subTest(estado=estado):
                self.assertEqual(self.client.get(self.url(cita)).status_code, 200)

    def test_cambios_en_catalogo_y_perfiles_no_alteran_el_comprobante(self):
        cita = self.confirmada()
        original = self.texto_pdf(self.client.get(self.url(cita)))[1]
        self.servicio.nombre = "Servicio nuevo"
        self.servicio.precio = "99.00"
        self.servicio.duracion_minutos = 90
        self.servicio.save()
        self.usuario.first_name = "Otro nombre de barbero"
        self.usuario.save()
        self.cliente.first_name = "Otro nombre de cliente"
        self.cliente.save()
        self.assertEqual(self.texto_pdf(self.client.get(self.url(cita)))[1], original)

    def test_fecha_de_emision_es_la_confirmacion_y_no_la_descarga(self):
        cita = self.confirmada()
        fecha = timezone.now() - timedelta(days=30)
        EventoCita.objects.filter(cita=cita, nuevo="CONFIRMADA").update(fecha=fecha)
        texto = self.texto_pdf(self.client.get(self.url(cita)))[1]
        self.assertIn(timezone.localtime(fecha).strftime("%d/%m/%Y %H:%M"), texto)

    def test_datos_con_acentos_y_etiquetas_se_imprimen_como_texto(self):
        self.cliente.first_name = "José <b>Ñúñez</b> & María"
        self.cliente.last_name = "Álvarez"
        self.cliente.save()
        cita = self.confirmada()
        texto = self.texto_pdf(self.client.get(self.url(cita)))[1]
        self.assertIn("José <b>Ñúñez</b> & María Álvarez", texto)

    def test_nombres_largos_no_impiden_generar_pdf(self):
        self.cliente.first_name = "María " * 24
        self.cliente.last_name = "Pérez " * 24
        self.cliente.save()
        cita = self.confirmada()
        texto = self.texto_pdf(self.client.get(self.url(cita)))[1]
        self.assertIn("USD 8.00", texto)
        self.assertIn("Transacción", texto)
        self.assertIn("CAPTURA-TEST", texto)

    def test_error_pdf_no_modifica_confirmacion_y_permite_reintentar(self):
        with patch("reservas.comprobantes.generar_pdf", side_effect=RuntimeError("Error PDF")):
            cita = self.confirmada()
            antes = self.sin_cambios(cita)
            respuesta = self.client.get(self.url(cita))
            self.assertContains(respuesta, "Tu reserva y tu pago siguen confirmados", status_code=503)
        self.assertEqual(self.sin_cambios(cita), antes)
        self.assertEqual(self.client.get(self.url(cita)).status_code, 200)

    def test_reservas_anteriores_son_accesibles_mediante_paginacion(self):
        antigua = self.confirmada()
        for semana in range(1, 21):
            self.reservar(inicio=momento(9) + timedelta(days=7 * semana))
        primera = self.client.get(reverse("reservas:lista"))
        self.assertContains(primera, "Reservas anteriores")
        self.assertNotContains(primera, self.url(antigua))
        segunda = self.client.get(reverse("reservas:lista"), {"pagina": 2})
        self.assertContains(segunda, self.url(antigua))
        self.assertContains(segunda, "Descargar comprobante")
        self.assertEqual(len(segunda.context["citas"]), 1)

    def test_migracion_conserva_nombre_disponible_sin_sobrescribirlo_despues(self):
        cita = self.confirmada()
        Cita.objects.filter(pk=cita.pk).update(cliente_nombre="")
        migracion = import_module("reservas.migrations.0003_comprobantes")
        with connection.schema_editor() as editor:
            migracion.conservar_nombre_cliente(apps, editor)
        cita.refresh_from_db()
        self.assertEqual(cita.cliente_nombre, "Ana María Pérez")
        self.cliente.first_name = "Otro nombre"
        self.cliente.save()
        with connection.schema_editor() as editor:
            migracion.conservar_nombre_cliente(apps, editor)
        cita.refresh_from_db()
        self.assertEqual(cita.cliente_nombre, "Ana María Pérez")
        self.assertTrue(cita.comprobante_disponible)

    def test_mensajes_historicos_cambian_solo_en_la_presentacion(self):
        cita = self.confirmada()
        anterior = "Pago Sandbox verificado y capturado."
        Pago.objects.filter(cita=cita).update(detalle=anterior)
        EventoCita.objects.filter(cita=cita, nuevo="CONFIRMADA").update(motivo=anterior)
        respuesta = self.client.get(reverse("reservas:detalle", args=[cita.pk]))
        self.assertContains(respuesta, "Pago confirmado correctamente.")
        self.assertNotContains(respuesta, anterior)
        self.assertEqual(Pago.objects.get(cita=cita).detalle, anterior)
        self.assertEqual(EventoCita.objects.get(cita=cita, nuevo="CONFIRMADA").motivo, anterior)

    def test_texto_desconocido_del_historial_se_escapa(self):
        plantilla = Template("{% load reservas_tags %}{{ texto|texto_reserva }}")
        self.assertEqual(plantilla.render(Context({"texto": "<script>alert(1)</script>"})),
                         "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_textos_de_pago_profesionales(self):
        cita = self.reservar()
        respuesta = self.client.get(reverse("reservas:detalle", args=[cita.pk]))
        self.assertContains(respuesta, "Pagar con PayPal")
        self.assertNotContains(respuesta, "Entorno de demostración")
        self.assertNotContains(respuesta, "Sin dinero real")
        self.assertNotContains(respuesta, "Pagar con PayPal Sandbox")
        self.assertNotContains(respuesta, "Total de prueba")
        self.assertNotContains(respuesta, "Desarrollo de Software VIII")
