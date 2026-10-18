from datetime import timedelta
from io import StringIO
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch
from barberos.models import Bloqueo, Horario, Ocupacion, PerfilBarbero
from usuarios.models import Usuario

@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DemoTests(TestCase):
    def test_comandos_repetibles_sin_reescribir_contrasenas(self):
        # Valor solo generado en memoria para la prueba, nunca usado en el sitio.
        import secrets
        clave=secrets.token_urlsafe(24)
        with patch("usuarios.management.commands.crear_datos_demo.config",return_value=clave):
            call_command("crear_datos_demo",stdout=StringIO())
            usuario=Usuario.objects.get(username="barbero_demo")
            original=usuario.password
            call_command("crear_datos_demo",stdout=StringIO())
        usuario.refresh_from_db()
        self.assertEqual(usuario.password,original)
        fecha=timezone.localdate()+timedelta(days=1)
        if fecha.weekday()==6: fecha+=timedelta(days=1)
        call_command("crear_agenda_demo",fecha=fecha,stdout=StringIO())
        conteo=(PerfilBarbero.objects.count(),Horario.objects.count(),Bloqueo.objects.count(),Ocupacion.objects.count())
        self.assertEqual(conteo,(1,6,2,1))
        call_command("crear_agenda_demo",fecha=fecha,stdout=StringIO())
        self.assertEqual((PerfilBarbero.objects.count(),Horario.objects.count(),Bloqueo.objects.count(),Ocupacion.objects.count()),conteo)
