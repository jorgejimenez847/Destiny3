from concurrent.futures import ThreadPoolExecutor
from datetime import time
from threading import Barrier
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connections, transaction
from django.test import TransactionTestCase
from barberos.models import Horario, Ocupacion, PerfilBarbero
from servicios.models import Servicio
from usuarios.models import Usuario
from .base import momento

class ConcurrenciaPostgresTests(TransactionTestCase):
    def setUp(self):
        u=Usuario.objects.create_user(username="concurrente",rol="BARBERO")
        self.barbero=PerfilBarbero.objects.create(usuario=u,especialidad="Cortes")
        self.servicio=Servicio.objects.create(nombre="Corte",precio=8,duracion_minutos=30)
        self.barbero.servicios.add(self.servicio)
        Horario.objects.create(barbero=self.barbero,dia=0,inicio=time(9),fin=time(17))

    def competir(self, *, bulk=False):
        barrera=Barrier(2)
        def escribir(numero):
            close_old_connections()
            try:
                b=PerfilBarbero.objects.get(pk=self.barbero.pk)
                servicio=Servicio.objects.get(pk=self.servicio.pk)
                barrera.wait(timeout=15)
                try:
                    with transaction.atomic():
                        ocupacion=Ocupacion(barbero=b,servicio=servicio,inicio=momento(9),fin=momento(9,30))
                        if bulk:
                            Ocupacion.objects.bulk_create([ocupacion])
                        else:
                            ocupacion.save()
                    return "guardada"
                except (ValidationError,IntegrityError):
                    return "rechazada"
                except OperationalError as exc:
                    # SQL directo sin orden de bloqueos puede causar deadlock en GiST.
                    # PostgreSQL aborta una transacción: nunca se persisten las dos.
                    if bulk and getattr(exc.__cause__, "pgcode", None) == "40P01":
                        return "rechazada"
                    raise
            finally:
                connections["default"].close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados=list(executor.map(escribir,[1,2]))
        self.assertCountEqual(resultados,["guardada","rechazada"])
        self.assertEqual(Ocupacion.objects.count(),1)

    def test_dos_solicitudes_simultaneas_por_modelo(self):
        self.competir()

    def test_exclusion_postgres_con_dos_escrituras_directas_simultaneas(self):
        self.competir(bulk=True)


    def competir_agenda(self, tipos):
        from barberos.models import Bloqueo
        barrera=Barrier(2)
        def escribir(tipo):
            close_old_connections()
            try:
                barrera.wait(timeout=15)
                try:
                    if tipo == "horario":
                        Horario.objects.create(barbero_id=self.barbero.pk,dia=1,inicio=time(9),fin=time(12))
                    elif tipo == "bloqueo":
                        Bloqueo.objects.create(barbero_id=self.barbero.pk,inicio=momento(9),fin=momento(10),motivo="AUSENCIA")
                    else:
                        Ocupacion.objects.create(barbero_id=self.barbero.pk,servicio_id=self.servicio.pk,
                            inicio=momento(9),fin=momento(9,30))
                    return "guardada"
                except ValidationError:
                    return "rechazada"
            finally:
                connections["default"].close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados=list(executor.map(escribir,tipos))
        self.assertCountEqual(resultados,["guardada","rechazada"])

    def test_dos_horarios_superpuestos_simultaneos(self):
        self.competir_agenda(["horario","horario"])

    def test_bloqueo_y_ocupacion_simultaneos_no_pueden_coexistir(self):
        self.competir_agenda(["bloqueo","ocupacion"])
