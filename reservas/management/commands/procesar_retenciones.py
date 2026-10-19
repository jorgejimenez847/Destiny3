import time
from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections
from reservas.paypal import PayPalError
from reservas.servicios import ejecutar_ciclo


class Command(BaseCommand):
    help = "Libera retenciones vencidas y verifica pagos Sandbox, sin depender de visitas al sitio."

    def add_arguments(self, parser):
        parser.add_argument("--una-vez", action="store_true")

    def handle(self, *args, **options):
        self.stdout.write("Procesador de retenciones y pagos Sandbox iniciado.")
        try:
            while True:
                close_old_connections()
                try:
                    total = ejecutar_ciclo()
                    if total:
                        self.stdout.write(f"Retenciones liberadas: {total}")
                except (DatabaseError, PayPalError):
                    self.stderr.write(
                        "No se completó el ciclo. Se reintentará sin liberar pagos inciertos."
                    )
                    if options["una_vez"]:
                        raise
                if options["una_vez"]:
                    break
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Procesador detenido.")
