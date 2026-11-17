from unittest.mock import patch
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from barberos.models import PerfilBarbero
from servicios.models import Servicio
from usuarios.models import Usuario


class AdministracionPropiaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user(username="admin", rol="ADMIN")
        cls.cliente = Usuario.objects.create_user(
            username="cliente", email="cliente@example.com"
        )
        cls.barbero = Usuario.objects.create_user(
            username="barbero", rol="BARBERO", email="barbero@example.com"
        )
        cls.servicio = Servicio.objects.create(
            nombre="Corte", precio="8.00", duracion_minutos=30
        )
        cls.perfil = PerfilBarbero.objects.create(
            usuario=cls.barbero, especialidad="Cortes"
        )
        cls.perfil.servicios.add(cls.servicio)

    def setUp(self):
        self.client.force_login(self.admin)

    def cuenta_nueva(self, **cambios):
        return {
            "username": "nuevo",
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "nuevo@example.com",
            "telefono": "6000-0000",
            "rol": "BARBERO",
            "password1": "Clave-gestion-12345",
            "password2": "Clave-gestion-12345",
            **cambios,
        }

    def test_admin_sin_staff_usa_todas_las_pantallas_propias(self):
        for nombre in (
            "usuarios:gestion",
            "usuarios:crear",
            "servicios:gestion",
            "servicios:crear",
            "barberos:gestion",
        ):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)

    def test_clientes_y_barberos_no_pueden_listar_ni_modificar(self):
        urls = [
            reverse("usuarios:gestion"),
            reverse("usuarios:crear"),
            reverse("usuarios:editar", args=[self.cliente.pk]),
            reverse("servicios:gestion"),
            reverse("servicios:crear"),
            reverse("servicios:editar", args=[self.servicio.pk]),
            reverse("barberos:gestion"),
        ]
        for usuario in (self.cliente, self.barbero):
            self.client.force_login(usuario)
            for url in urls:
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("usuarios:gestion")).status_code, 302)
        self.assertEqual(self.client.get(reverse("servicios:gestion")).status_code, 302)

    def test_crea_barbero_sin_privilegios_administrativos_y_luego_su_perfil(self):
        respuesta = self.client.post(
            reverse("usuarios:crear"),
            self.cuenta_nueva(is_staff="on", is_superuser="on"),
        )
        self.assertEqual(respuesta.status_code, 302)
        usuario = Usuario.objects.get(username="nuevo")
        self.assertEqual(usuario.rol, "BARBERO")
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertTrue(usuario.check_password("Clave-gestion-12345"))
        self.assertEqual(
            self.client.post(
                reverse("barberos:crear"),
                {
                    "usuario": usuario.pk,
                    "especialidad": "Barba",
                    "servicios": [self.servicio.pk],
                    "activo": "on",
                },
            ).status_code,
            302,
        )
        self.assertTrue(
            PerfilBarbero.objects.filter(
                usuario=usuario, servicios=self.servicio
            ).exists()
        )

    def test_no_crea_admin_ni_acepta_contrasenas_invalidas(self):
        for cambios in (
            {"rol": "ADMIN"},
            {"password2": "otra"},
            {"password1": "123", "password2": "123"},
        ):
            with self.subTest(cambios=cambios):
                respuesta = self.client.post(
                    reverse("usuarios:crear"), self.cuenta_nueva(**cambios)
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["form"].errors)
                self.assertFalse(Usuario.objects.filter(username="nuevo").exists())

    def test_editar_conserva_password_rol_y_permisos(self):
        password = self.cliente.password
        respuesta = self.client.post(
            reverse("usuarios:editar", args=[self.cliente.pk]),
            {
                "username": "cliente",
                "first_name": "Ana",
                "last_name": "Pérez",
                "email": "cliente@example.com",
                "telefono": "6000-1234",
                "rol": "ADMIN",
                "is_staff": "on",
                "is_superuser": "on",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.password, password)
        self.assertEqual(self.cliente.rol, "CLIENTE")
        self.assertFalse(self.cliente.is_staff)
        self.assertFalse(self.cliente.is_superuser)
        self.assertFalse(self.cliente.is_active)
        self.assertEqual(self.cliente.telefono, "6000-1234")

    def test_no_edita_cuentas_admin_desde_gestion_de_clientes(self):
        url = reverse("usuarios:editar", args=[self.admin.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {}).status_code, 404)

    def test_correo_duplicado_se_rechaza_sin_modificar_cuenta(self):
        respuesta = self.client.post(
            reverse("usuarios:editar", args=[self.cliente.pk]),
            {
                "username": "cliente",
                "email": "BARBERO@example.com",
                "is_active": "on",
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("email", respuesta.context["form"].errors)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.email, "cliente@example.com")

    def test_busca_clientes_y_filtra_rol_y_estado(self):
        respuesta = self.client.get(
            reverse("usuarios:gestion"),
            {"q": "cliente", "rol": "CLIENTE", "activo": "si"},
        )
        self.assertEqual(list(respuesta.context["usuarios"]), [self.cliente])
        respuesta = self.client.get(reverse("usuarios:gestion"), {"rol": "ADMIN"})
        self.assertTrue(respuesta.context["filtros"].errors)
        self.assertEqual(len(respuesta.context["usuarios"]), 0)

    def test_crea_y_edita_servicio_con_validacion(self):
        respuesta = self.client.post(
            reverse("servicios:crear"),
            {
                "nombre": "Barba",
                "descripcion": "Perfilado",
                "precio": "5.00",
                "duracion_minutos": "20",
                "activo": "on",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        servicio = Servicio.objects.get(nombre="Barba")
        respuesta = self.client.post(
            reverse("servicios:editar", args=[servicio.pk]),
            {
                "nombre": "Barba",
                "descripcion": "Perfilado",
                "precio": "6.00",
                "duracion_minutos": "25",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        servicio.refresh_from_db()
        self.assertFalse(servicio.activo)
        self.assertEqual(servicio.duracion_minutos, 25)
        self.assertNotContains(self.client.get(reverse("servicios:lista")), "Perfilado")

    def test_servicio_rechaza_duracion_y_precio_invalidos(self):
        for cambios in ({"duracion_minutos": "0"}, {"precio": "0"}, {"precio": "-5"}):
            datos = {
                "nombre": "Servicio inválido",
                "duracion_minutos": "30",
                "precio": "5",
                **cambios,
            }
            respuesta = self.client.post(reverse("servicios:crear"), datos)
            self.assertTrue(respuesta.context["form"].errors)
            self.assertFalse(
                Servicio.objects.filter(nombre="Servicio inválido").exists()
            )

    def test_filtros_de_servicios_y_barberos(self):
        respuesta = self.client.get(
            reverse("servicios:gestion"), {"q": "Corte", "activo": "si"}
        )
        self.assertEqual(list(respuesta.context["servicios"]), [self.servicio])
        respuesta = self.client.get(
            reverse("barberos:gestion"),
            {"q": "Cortes", "activo": "si", "servicio": self.servicio.pk},
        )
        self.assertEqual(list(respuesta.context["perfiles"]), [self.perfil])
        respuesta = self.client.get(
            reverse("barberos:gestion"), {"servicio": "no-valido"}
        )
        self.assertTrue(respuesta.context["filtros"].errors)
        self.assertEqual(len(respuesta.context["perfiles"]), 0)

    def test_conflicto_al_guardar_cuenta_se_muestra_sin_error_500(self):
        with patch("usuarios.gestion.AltaUsuarioForm.save", side_effect=IntegrityError):
            respuesta = self.client.post(reverse("usuarios:crear"), self.cuenta_nueva())
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].non_field_errors())
        self.assertFalse(Usuario.objects.filter(username="nuevo").exists())
