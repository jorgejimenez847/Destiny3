from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse

from barberos.models import PerfilBarbero
from reservas.models import Cita, EventoCita, Pago
from usuarios.models import Usuario


class AdministradorTests(TestCase):
    modelos = (PerfilBarbero, Cita, Pago, EventoCita)

    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            username="administrador", password="Clave-pruebas-123"
        )
        cls.cliente = Usuario.objects.create_user(username="cliente")
        cls.barbero = Usuario.objects.create_user(username="barbero", rol="BARBERO")

    def url_lista(self, modelo):
        return reverse(f"admin:{modelo._meta.app_label}_{modelo._meta.model_name}_changelist")

    def test_anonimo_puede_abrir_login_y_es_redirigido_desde_admin(self):
        login = reverse("admin:login")
        self.assertEqual(self.client.get(login).status_code, 200)
        respuesta = self.client.get(reverse("admin:index"))
        self.assertRedirects(respuesta, f"{login}?next=/admin/")

    def test_comprobaciones_de_modelos_rechazan_anonimos(self):
        request = RequestFactory().get("/admin/login/")
        request.user = AnonymousUser()
        for modelo in self.modelos:
            with self.subTest(modelo=modelo.__name__):
                gestor = admin.site._registry[modelo]
                self.assertFalse(gestor.has_module_permission(request))
                self.assertFalse(gestor.has_view_permission(request))
                self.assertFalse(gestor.has_add_permission(request))
                self.assertFalse(gestor.has_change_permission(request))
                self.assertFalse(gestor.has_delete_permission(request))

    def test_administrador_autorizado_inicia_sesion_y_consulta_modelos(self):
        respuesta = self.client.post(reverse("admin:login"), {
            "username": self.admin.username, "password": "Clave-pruebas-123", "next": "/admin/",
        })
        self.assertRedirects(respuesta, reverse("admin:index"))
        for modelo in self.modelos:
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(self.client.get(self.url_lista(modelo)).status_code, 200)

    def test_clientes_y_barberos_no_pueden_entrar_al_administrador(self):
        for usuario in (self.cliente, self.barbero):
            self.client.force_login(usuario)
            for url in [reverse("admin:index"), *map(self.url_lista, self.modelos)]:
                with self.subTest(rol=usuario.rol, url=url):
                    respuesta = self.client.get(url)
                    self.assertEqual(respuesta.status_code, 302)
                    self.assertTrue(respuesta.url.startswith(reverse("admin:login")))

    def test_staff_y_superusuario_no_bypassean_rol_en_modelos_protegidos(self):
        for usuario in (self.cliente, self.barbero):
            usuario.is_staff = usuario.is_superuser = True
            usuario.save()
            self.client.force_login(usuario)
            for modelo in self.modelos:
                with self.subTest(rol=usuario.rol, modelo=modelo.__name__):
                    self.assertEqual(self.client.get(self.url_lista(modelo)).status_code, 403)

    def test_rol_admin_sin_staff_no_accede(self):
        usuario = Usuario.objects.create_user(username="admin_sin_staff", rol="ADMIN")
        self.client.force_login(usuario)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_admin_inactivo_no_accede(self):
        self.admin.is_active = False
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_rol_admin_conserva_permisos_django(self):
        usuario = Usuario.objects.create_user(username="staff", rol="ADMIN", is_staff=True)
        self.client.force_login(usuario)
        url = self.url_lista(PerfilBarbero)
        self.assertEqual(self.client.get(url).status_code, 403)
        permiso = Permission.objects.get(
            content_type__app_label="barberos", codename="view_perfilbarbero"
        )
        usuario.user_permissions.add(permiso)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:barberos_perfilbarbero_add")).status_code, 403)

    def test_reservas_siguen_siendo_de_solo_consulta_incluso_para_admin(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        for modelo in (Cita, Pago, EventoCita):
            gestor = admin.site._registry[modelo]
            with self.subTest(modelo=modelo.__name__):
                self.assertTrue(gestor.has_view_permission(request))
                self.assertFalse(gestor.has_add_permission(request))
                self.assertFalse(gestor.has_change_permission(request))
                self.assertFalse(gestor.has_delete_permission(request))

    def test_perfiles_permiten_gestion_pero_no_borrado(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        gestor = admin.site._registry[PerfilBarbero]
        self.assertTrue(gestor.has_add_permission(request))
        self.assertTrue(gestor.has_change_permission(request))
        self.assertFalse(gestor.has_delete_permission(request))

    def test_createsuperuser_asigna_rol_admin(self):
        with patch.dict("os.environ", {"DJANGO_SUPERUSER_PASSWORD": "Clave-pruebas-456"}):
            call_command("createsuperuser", username="nuevo_admin", email="", interactive=False, stdout=StringIO())
        usuario = Usuario.objects.get(username="nuevo_admin")
        self.assertEqual(usuario.rol, "ADMIN")
        self.assertTrue(usuario.is_staff)
        self.assertTrue(usuario.is_superuser)
        self.assertTrue(usuario.check_password("Clave-pruebas-456"))

    def test_superusuario_rechaza_rol_incompatible(self):
        with self.assertRaisesMessage(ValueError, "rol Administrador"):
            Usuario.objects.create_superuser(username="incompatible", rol="BARBERO")

    def test_usuario_normal_sigue_siendo_cliente(self):
        self.assertEqual(self.cliente.rol, "CLIENTE")
        self.assertFalse(self.cliente.is_staff)
        self.assertFalse(self.cliente.is_superuser)
