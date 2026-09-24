from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Usuario

CLAVE = "Clave-segura-123"


def crear_usuario(username, rol=Usuario.Rol.CLIENTE):
    return Usuario.objects.create_user(
        username=username, email=f"{username}@test.com", password=CLAVE, rol=rol
    )


class AutenticacionTests(TestCase):
    def test_registro_crea_cliente(self):
        r = self.client.post(reverse("usuarios:registro"), {
            "username": "ana", "first_name": "Ana", "last_name": "Pérez",
            "email": "ana@test.com", "telefono": "6000-0000",
            "password1": CLAVE, "password2": CLAVE,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Usuario.objects.get(username="ana").rol, Usuario.Rol.CLIENTE)

    def test_registro_no_permite_elegir_rol(self):
        self.client.post(reverse("usuarios:registro"), {
            "username": "mal", "first_name": "M", "last_name": "L",
            "email": "mal@test.com", "rol": "ADMIN",
            "password1": CLAVE, "password2": CLAVE,
        })
        self.assertEqual(Usuario.objects.get(username="mal").rol, Usuario.Rol.CLIENTE)

    def test_email_duplicado_rechazado(self):
        crear_usuario("x")
        r = self.client.post(reverse("usuarios:registro"), {
            "username": "y", "first_name": "Y", "last_name": "Y",
            "email": "x@test.com", "password1": CLAVE, "password2": CLAVE,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="y").exists())

    def test_login_correcto(self):
        crear_usuario("u")
        r = self.client.post(reverse("usuarios:login"), {"username": "u", "password": CLAVE})
        self.assertEqual(r.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_login_con_clave_incorrecta(self):
        crear_usuario("u")
        r = self.client.post(reverse("usuarios:login"), {"username": "u", "password": "otra"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout(self):
        crear_usuario("u")
        self.client.login(username="u", password=CLAVE)
        self.client.post(reverse("usuarios:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_recuperacion_envia_correo(self):
        crear_usuario("u")
        self.client.post(reverse("usuarios:password_reset"), {"email": "u@test.com"})
        self.assertEqual(len(mail.outbox), 1)


class RolesTests(TestCase):
    def test_redireccion_segun_rol(self):
        casos = {
            Usuario.Rol.CLIENTE: "usuarios:panel_cliente",
            Usuario.Rol.BARBERO: "usuarios:panel_barbero",
            Usuario.Rol.ADMIN: "usuarios:panel_admin",
        }
        for rol, destino in casos.items():
            with self.subTest(rol=rol):
                usuario = crear_usuario(f"u_{rol.lower()}", rol)
                self.client.force_login(usuario)
                r = self.client.get(reverse("usuarios:redirigir_por_rol"))
                self.assertRedirects(r, reverse(destino), fetch_redirect_response=False)

    def test_cada_rol_accede_a_su_panel(self):
        casos = {
            Usuario.Rol.CLIENTE: "usuarios:panel_cliente",
            Usuario.Rol.BARBERO: "usuarios:panel_barbero",
            Usuario.Rol.ADMIN: "usuarios:panel_admin",
        }
        for rol, panel in casos.items():
            with self.subTest(rol=rol):
                self.client.force_login(crear_usuario(f"p_{rol.lower()}", rol))
                self.assertEqual(self.client.get(reverse(panel)).status_code, 200)

    def test_rol_incorrecto_recibe_403(self):
        cliente = crear_usuario("cli", Usuario.Rol.CLIENTE)
        self.client.force_login(cliente)
        self.assertEqual(self.client.get(reverse("usuarios:panel_admin")).status_code, 403)
        self.assertEqual(self.client.get(reverse("usuarios:panel_barbero")).status_code, 403)

    def test_barbero_no_entra_al_panel_admin(self):
        self.client.force_login(crear_usuario("bar", Usuario.Rol.BARBERO))
        self.assertEqual(self.client.get(reverse("usuarios:panel_admin")).status_code, 403)

    def test_anonimo_es_enviado_al_login(self):
        r = self.client.get(reverse("usuarios:panel_cliente"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("usuarios:login"), r.url)