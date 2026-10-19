from django.urls import reverse
from barberos.models import Horario
from .base import AgendaTestCase

class PermisosTests(AgendaTestCase):
    def test_anonimo_redirigido(self):
        for nombre in ["gestion","crear","mi_perfil"]:
            self.assertEqual(self.client.get(reverse(f"barberos:{nombre}")).status_code,302)

    def test_cliente_y_barbero_no_administran_por_get_ni_post(self):
        rutas=[reverse("barberos:gestion"),reverse("barberos:crear"),
               reverse("barberos:editar",args=[self.barbero.pk]),
               reverse("barberos:horario_crear",args=[self.barbero.pk]),
               reverse("barberos:bloqueo_crear",args=[self.barbero.pk])]
        for usuario in [self.cliente,self.usuario]:
            self.client.force_login(usuario)
            for url in rutas:
                for metodo in [self.client.get,self.client.post]:
                    with self.subTest(usuario=usuario,url=url,metodo=metodo.__name__):
                        self.assertEqual(metodo(url).status_code,403)

    def test_barbero_solo_consulta_su_perfil(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("barberos:detalle",args=[self.barbero.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse("barberos:detalle",args=[self.otro.pk])).status_code,403)
        self.assertRedirects(self.client.get(reverse("barberos:mi_perfil")),reverse("barberos:detalle",args=[self.barbero.pk]))

    def test_cliente_no_lee_agendas_privadas(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("barberos:detalle",args=[self.barbero.pk])).status_code,403)

    def test_barbero_sin_perfil_tiene_estado_vacio(self):
        from usuarios.models import Usuario
        u=Usuario.objects.create_user(username="sinperfil",rol="BARBERO")
        self.client.force_login(u)
        self.assertContains(self.client.get(reverse("barberos:mi_perfil")),"todavía no está configurado")

    def test_admin_ve_gestion_y_detalle_vacio(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("barberos:gestion")),"Barberos y horarios")
        self.assertContains(self.client.get(reverse("barberos:detalle",args=[self.barbero.pk])),"No hay horarios registrados")

    def test_admin_crea_edita_y_elimina_con_confirmacion(self):
        self.client.force_login(self.admin)
        url=reverse("barberos:horario_crear",args=[self.barbero.pk])
        r=self.client.post(url,{"dia":0,"inicio":"09:00","fin":"17:00"})
        self.assertEqual(r.status_code,302)
        h=Horario.objects.get()
        url=reverse("barberos:horario_editar",args=[self.barbero.pk,h.pk])
        self.assertEqual(self.client.post(url,{"dia":1,"inicio":"10:00","fin":"16:00"}).status_code,302)
        h.refresh_from_db()
        self.assertEqual(h.dia,1)
        url=reverse("barberos:horario_eliminar",args=[self.barbero.pk,h.pk])
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertTrue(Horario.objects.filter(pk=h.pk).exists())
        self.assertEqual(self.client.post(url).status_code,302)
        self.assertFalse(Horario.objects.filter(pk=h.pk).exists())

    def test_no_puede_alterar_parentesco_por_url_o_post(self):
        h=self.turno()
        self.client.force_login(self.admin)
        url=reverse("barberos:horario_editar",args=[self.otro.pk,h.pk])
        self.assertEqual(self.client.post(url,{}).status_code,404)
        url=reverse("barberos:horario_crear",args=[self.barbero.pk])
        self.client.post(url,{"barbero":self.otro.pk,"dia":1,"inicio":"09:00","fin":"10:00"})
        self.assertFalse(self.otro.horario_set.exists())

    def test_formulario_invalido_muestra_error(self):
        self.client.force_login(self.admin)
        r=self.client.post(reverse("barberos:horario_crear",args=[self.barbero.pk]),{"dia":0,"inicio":"17:00","fin":"09:00"})
        self.assertEqual(r.status_code,200)
        self.assertContains(r,"La salida debe ser posterior")
        self.assertFalse(Horario.objects.exists())

    def test_post_sin_csrf_rechazado(self):
        from django.test import Client
        c=Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        self.assertEqual(c.post(reverse("barberos:crear"),{}).status_code,403)


    def test_admin_django_no_bypassea_rol_barbero(self):
        self.usuario.is_staff=True
        self.usuario.is_superuser=True
        self.usuario.save()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("admin:barberos_perfilbarbero_changelist")).status_code,403)


    def test_admin_crea_perfil_y_rechaza_usuario_cliente(self):
        from usuarios.models import Usuario
        from barberos.models import PerfilBarbero
        nuevo=Usuario.objects.create_user(username="nuevobarbero",rol="BARBERO")
        self.client.force_login(self.admin)
        url=reverse("barberos:crear")
        r=self.client.post(url,{"usuario":nuevo.pk,"especialidad":"Cortes","servicios":[self.servicio.pk],"activo":"on"})
        self.assertEqual(r.status_code,302)
        self.assertTrue(PerfilBarbero.objects.filter(usuario=nuevo,servicios=self.servicio).exists())
        r=self.client.post(url,{"usuario":self.cliente.pk,"especialidad":"Cortes","activo":"on"})
        self.assertEqual(r.status_code,200)
        self.assertFalse(PerfilBarbero.objects.filter(usuario=self.cliente).exists())

    def test_editar_perfil_no_permite_cambiar_propietario_y_desactiva(self):
        from barberos.models import PerfilBarbero
        self.client.force_login(self.admin)
        r=self.client.post(reverse("barberos:editar",args=[self.barbero.pk]),
            {"usuario":self.otro_usuario.pk,"especialidad":"Barba","servicios":[self.servicio.pk]})
        self.assertEqual(r.status_code,302)
        perfil=PerfilBarbero.objects.get(pk=self.barbero.pk)
        self.assertEqual(perfil.usuario_id,self.usuario.pk)
        self.assertFalse(perfil.activo)

    def test_admin_crud_bloqueo_con_fechas_locales(self):
        from barberos.models import Bloqueo
        self.client.force_login(self.admin)
        datos={"inicio":"2030-01-07T10:00","fin":"2030-01-07T11:00","motivo":"AUSENCIA"}
        r=self.client.post(reverse("barberos:bloqueo_crear",args=[self.barbero.pk]),datos)
        self.assertEqual(r.status_code,302)
        b=Bloqueo.objects.get()
        datos["fin"]="2030-01-07T11:30"
        self.assertEqual(self.client.post(reverse("barberos:bloqueo_editar",args=[self.barbero.pk,b.pk]),datos).status_code,302)
        b.refresh_from_db()
        self.assertEqual(b.fin.minute,30)
        self.assertEqual(self.client.post(reverse("barberos:bloqueo_eliminar",args=[self.barbero.pk,b.pk])).status_code,302)
        self.assertFalse(Bloqueo.objects.exists())
