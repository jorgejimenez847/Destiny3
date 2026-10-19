from datetime import date, datetime, time, timedelta
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from barberos.models import Bloqueo, Horario, Ocupacion, PerfilBarbero
from servicios.models import Servicio
from usuarios.models import Usuario


class Command(BaseCommand):
    help = "Añade perfil, horario y ejemplos de ausencia/ocupación al barbero_demo, conservando su configuración."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", type=date.fromisoformat, help="Fecha futura ISO para el ejemplo; por defecto, próximo día de lunes a sábado.")

    @transaction.atomic
    def handle(self, *args, **options):
        usuario=Usuario.objects.filter(username="barbero_demo",rol="BARBERO").first()
        servicio=Servicio.objects.filter(nombre="Corte de cabello",activo=True,duracion_minutos=30).first()
        if not usuario or not servicio:
            raise CommandError("Ejecuta primero crear_datos_demo. Se requiere Corte de cabello activo de 30 minutos y barbero_demo con rol Barbero.")
        fecha=options["fecha"] or timezone.localdate()+timedelta(days=1)
        if fecha <= timezone.localdate():
            raise CommandError("La fecha de demostración debe ser futura.")
        if options["fecha"] is None and fecha.weekday()==6:
            fecha+=timedelta(days=1)
        perfil,creado=PerfilBarbero.objects.get_or_create(usuario=usuario,defaults={"especialidad":"Corte clásico y arreglo de barba",
            "descripcion":"Atención personalizada, cortes clásicos y acabados de barba."})
        if creado:
            perfil.servicios.set(Servicio.objects.filter(activo=True))
            for dia in range(6):
                Horario.objects.create(barbero=perfil,dia=dia,inicio=time(9),fin=time(17),
                    descanso_inicio=time(12),descanso_fin=time(13))
        def dt(d,h,m=0):
            return timezone.make_aware(datetime.combine(d,time(h,m)),timezone.get_default_timezone())
        # Los ejemplos se añaden solo si caben en la agenda existente; nunca se reemplazan datos.
        if not Bloqueo.objects.filter(barbero=perfil,inicio=dt(fecha,10),fin=dt(fecha,11)).exists():
            try:
                Bloqueo.objects.create(barbero=perfil,inicio=dt(fecha,10),fin=dt(fecha,11),
                    motivo="AUSENCIA",nota="Demostración: ausencia parcial")
            except ValidationError:
                self.stdout.write("Se conserva la agenda: no se añadió el bloqueo parcial por conflicto.")
        siguiente=fecha+timedelta(days=1)
        if not Bloqueo.objects.filter(barbero=perfil,inicio=dt(siguiente,0),fin=dt(siguiente+timedelta(days=1),0)).exists():
            try:
                Bloqueo.objects.create(barbero=perfil,inicio=dt(siguiente,0),fin=dt(siguiente+timedelta(days=1),0),
                    motivo="FERIADO",nota="Demostración: día completo no disponible")
            except ValidationError:
                self.stdout.write("Se conserva la agenda: no se añadió el día completo por conflicto.")
        inicio,fin=dt(fecha,9),dt(fecha,9,30)
        if not Ocupacion.objects.filter(barbero=perfil,inicio=inicio,fin=fin).exists():
            try:
                Ocupacion.objects.create(barbero=perfil,servicio=servicio,inicio=inicio,fin=fin,
                    referencia="DEMO: intervalo ocupado, sin reserva ni pago")
            except ValidationError:
                self.stdout.write("Se conserva la agenda: no se añadió el intervalo ocupado por conflicto.")
        self.stdout.write(self.style.SUCCESS(f"Agenda demo preparada para {fecha.isoformat()}. Consulta Corte de cabello con barbero_demo: 09:00 ocupado, 10:00–11:00 ausencia, 12:00–13:00 descanso; el día siguiente está bloqueado si no hubo conflictos."))
