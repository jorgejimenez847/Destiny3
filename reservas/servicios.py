"""Reservas y transiciones. Orden de bloqueos: perfil, cita y pago."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from barberos.models import Ocupacion, PerfilBarbero
from servicios.models import Servicio
from .models import Cita, EstadoProcesador, EventoCita, Pago
from .paypal import PayPalClient, PayPalError, enlace_aprobacion

PENDIENTE = Cita.Estado.PENDIENTE


def registrar_latido():
    EstadoProcesador.objects.update_or_create(
        pk=1, defaults={"ultimo_latido": timezone.now()}
    )


def comprobar_procesador():
    limite = timezone.now() - timedelta(seconds=settings.PROCESADOR_MAX_LATIDO_SEGUNDOS)
    if not EstadoProcesador.objects.filter(pk=1, ultimo_latido__gte=limite).exists():
        raise ValidationError(
            "Las reservas están temporalmente pausadas. El administrador debe iniciar el procesador de retenciones."
        )


def _bloquear(cita_id):
    barbero_id = Cita.objects.values_list("barbero_id", flat=True).get(pk=cita_id)
    PerfilBarbero.objects.select_for_update().get(pk=barbero_id)
    cita = Cita.objects.select_for_update().select_related("ocupacion").get(pk=cita_id)
    pago = Pago.objects.select_for_update().get(cita=cita)
    return cita, pago


def _transicionar(cita, nuevo, motivo, actor=None):
    permitidas = {
        PENDIENTE: {
            Cita.Estado.CONFIRMADA,
            Cita.Estado.CANCELADA,
            Cita.Estado.EXPIRADA,
            Cita.Estado.PAGO_FALLIDO,
        },
        Cita.Estado.CONFIRMADA: {Cita.Estado.EN_ATENCION, Cita.Estado.NO_ASISTIO},
        Cita.Estado.EN_ATENCION: {Cita.Estado.COMPLETADA},
    }
    if nuevo == cita.estado:
        return
    if nuevo not in permitidas.get(cita.estado, set()):
        raise ValidationError("Esta transición de estado no está permitida.")
    anterior = cita.estado
    cita.estado = nuevo
    cita.save(update_fields=["estado", "actualizada_en"])
    EventoCita.objects.create(
        cita=cita, anterior=anterior, nuevo=nuevo, motivo=motivo, actor=actor
    )
    if nuevo in [Cita.Estado.CANCELADA, Cita.Estado.EXPIRADA, Cita.Estado.PAGO_FALLIDO]:
        Ocupacion.objects.filter(pk=cita.ocupacion_id).update(activa=False)


def _expirar(cita, pago):
    # Una captura incierta no se libera: el procesador la reconcilia con PayPal.
    if (
        cita.estado == PENDIENTE
        and cita.expira_en <= timezone.now()
        and pago.captura_solicitada_en is None
    ):
        _transicionar(
            cita, Cita.Estado.EXPIRADA, "Venció la retención sin una captura iniciada."
        )
        pago.estado = Pago.Estado.CERRADO
        pago.procesando_hasta = None
        pago.save()
        return True
    return False


def expirar_retenciones(barbero_id=None):
    consulta = Cita.objects.filter(
        estado=PENDIENTE,
        expira_en__lte=timezone.now(),
        pago__captura_solicitada_en__isnull=True,
    )
    if barbero_id is not None:
        consulta = consulta.filter(barbero_id=barbero_id)
    total = 0
    for pk in list(consulta.values_list("pk", flat=True)):
        with transaction.atomic():
            cita, pago = _bloquear(pk)
            total += int(_expirar(cita, pago))
    return total


@transaction.atomic
def crear_cita(
    cliente,
    barbero_id,
    servicio_id,
    inicio,
    solicitud_id,
    precio_esperado,
    *,
    duracion_esperada=None
):
    if not cliente.is_active or cliente.rol != "CLIENTE":
        raise PermissionDenied
    comprobar_procesador()
    barbero = PerfilBarbero.objects.select_for_update().get(pk=barbero_id)
    existente = Cita.objects.filter(solicitud_id=solicitud_id).first()
    if existente:
        if (
            existente.cliente_id != cliente.pk
            or existente.barbero_id != barbero_id
            or existente.servicio_id != servicio_id
            or existente.inicio != inicio
        ):
            raise ValidationError("La selección ya fue utilizada para otra reserva.")
        return existente
    expirar_retenciones(barbero_id)
    servicio = Servicio.objects.get(pk=servicio_id)
    if servicio.precio != precio_esperado:
        raise ValidationError(
            "El precio cambió. Revisa nuevamente el resumen antes de reservar."
        )
    if duracion_esperada is not None and servicio.duracion_minutos != duracion_esperada:
        raise ValidationError(
            "La duración cambió. Revisa nuevamente el resumen antes de reservar."
        )
    fin = inicio + timedelta(minutes=servicio.duracion_minutos)
    ocupacion = Ocupacion.objects.create(
        barbero=barbero,
        servicio=servicio,
        inicio=inicio,
        fin=fin,
        referencia="Retención de reserva",
    )
    cita = Cita.objects.create(
        cliente=cliente,
        barbero=barbero,
        servicio=servicio,
        ocupacion=ocupacion,
        solicitud_id=solicitud_id,
        servicio_nombre=servicio.nombre,
        barbero_nombre=str(barbero),
        inicio=inicio,
        fin=fin,
        duracion_minutos=servicio.duracion_minutos,
        precio=servicio.precio,
        expira_en=min(
            timezone.now() + timedelta(minutes=settings.RETENCION_MINUTOS), inicio
        ),
    )
    Pago.objects.create(cita=cita)
    EventoCita.objects.create(
        cita=cita,
        nuevo=PENDIENTE,
        motivo="Selección confirmada; horario retenido para pago Sandbox.",
        actor=cliente,
    )
    return cita


@transaction.atomic
def cancelar_cita(cita_id, actor):
    cita, pago = _bloquear(cita_id)
    if actor.rol != "CLIENTE" or cita.cliente_id != actor.pk:
        raise PermissionDenied
    _expirar(cita, pago)
    if cita.estado in [Cita.Estado.CANCELADA, Cita.Estado.EXPIRADA]:
        return cita
    if cita.estado != PENDIENTE:
        raise ValidationError(
            "Solo se puede cancelar una reserva pendiente de pago en esta fase."
        )
    if pago.captura_solicitada_en is not None:
        raise ValidationError(
            "El pago está en verificación. Espera su resultado antes de cancelar."
        )
    _transicionar(
        cita, Cita.Estado.CANCELADA, "El cliente canceló antes de la captura.", actor
    )
    pago.estado = Pago.Estado.CERRADO
    pago.save()
    return cita


@transaction.atomic
def cambiar_estado_operativo(cita_id, nuevo, actor):
    cita, pago = _bloquear(cita_id)
    autorizado = actor.rol == "ADMIN" or (
        actor.rol == "BARBERO" and cita.barbero.usuario_id == actor.pk
    )
    if not autorizado or nuevo not in [
        Cita.Estado.EN_ATENCION,
        Cita.Estado.COMPLETADA,
        Cita.Estado.NO_ASISTIO,
    ]:
        raise PermissionDenied
    if pago.estado != Pago.Estado.COMPLETADO or timezone.now() < cita.inicio:
        raise ValidationError("La cita debe estar pagada y haber llegado a su hora.")
    _transicionar(cita, nuevo, "Actualización del estado de atención.", actor)
    return cita


def _revision(pago, detalle):
    pago.estado = Pago.Estado.VERIFICANDO
    pago.detalle = detalle
    pago.procesando_hasta = None
    pago.proxima_revision = timezone.now() + timedelta(seconds=30)
    pago.save()


def preparar_orden(cita_id, actor):
    expirar_retenciones(
        Cita.objects.values_list("barbero_id", flat=True).get(pk=cita_id)
    )
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if cita.cliente_id != actor.pk or actor.rol != "CLIENTE":
            raise PermissionDenied
        _expirar(cita, pago)
        if cita.estado != PENDIENTE or cita.expira_en <= timezone.now():
            raise ValidationError("Esta reserva ya no permite iniciar un pago.")
        if pago.captura_solicitada_en is not None:
            raise ValidationError(
                "El pago ya está en verificación. No inicies otro intento."
            )
        if pago.orden_id and pago.aprobacion_url:
            return pago.aprobacion_url
        if pago.procesando_hasta and pago.procesando_hasta > timezone.now():
            raise ValidationError("La orden se está preparando. Espera unos segundos.")
        pago.estado = Pago.Estado.CREANDO
        pago.procesando_hasta = timezone.now() + timedelta(seconds=120)
        pago.save()
    try:
        orden = PayPalClient().crear(cita, pago)
        orden_id = PayPalClient._id(orden.get("id"))
        url = enlace_aprobacion(orden)
        _verificar_orden(cita, pago, orden, comprobar_id=False)
    except PayPalError as exc:
        with transaction.atomic():
            cita, pago = _bloquear(cita_id)
            pago.procesando_hasta = None
            pago.estado = Pago.Estado.NUEVO if exc.recuperable else Pago.Estado.FALLIDO
            pago.detalle = "No se pudo preparar la orden de prueba."
            pago.save()
            if not exc.recuperable and cita.estado == PENDIENTE:
                _transicionar(cita, Cita.Estado.PAGO_FALLIDO, pago.detalle)
        raise ValidationError(str(exc)) from None
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        pago.orden_id = orden_id
        pago.aprobacion_url = url
        pago.receptor_id = (
            orden["purchase_units"][0].get("payee", {}).get("merchant_id", "")
        )
        pago.estado = (
            Pago.Estado.CREADO if cita.estado == PENDIENTE else Pago.Estado.CERRADO
        )
        pago.procesando_hasta = None
        pago.proxima_revision = timezone.now() + timedelta(seconds=5)
        pago.save()
        _expirar(cita, pago)
        finalizada = cita.estado != PENDIENTE
    if finalizada:
        raise ValidationError(
            "La retención terminó mientras se preparaba la orden. No continúes al pago."
        )
    return url


def _verificar_orden(cita, pago, orden, comprobar_id=True):
    try:
        unidades = orden["purchase_units"]
        unidad = unidades[0]
        identidad = (
            len(unidades) == 1
            and orden.get("intent") == "CAPTURE"
            and (not comprobar_id or orden.get("id") == pago.orden_id)
            and unidad.get("reference_id") == str(cita.pk)
            and unidad.get("custom_id") == str(cita.pk)
            and (
                not pago.receptor_id
                or unidad.get("payee", {}).get("merchant_id") == pago.receptor_id
            )
        )
        importe = (
            unidad["amount"]["currency_code"] == "USD"
            and Decimal(unidad["amount"]["value"]) == cita.precio
        )
    except (KeyError, IndexError, TypeError, AttributeError, InvalidOperation):
        identidad, importe = False, False
    if not identidad:
        raise PayPalError(
            "La orden no coincide con esta reserva. El servidor revisará el pago.",
            codigo="DATOS",
        )
    if not importe:
        raise PayPalError(
            "El importe o la moneda no coinciden con la reserva.", codigo="IMPORTE"
        )


def _captura(orden):
    try:
        capturas = orden["purchase_units"][0].get("payments", {}).get("captures", [])
        return (
            capturas[0]
            if len(capturas) == 1 and isinstance(capturas[0], dict)
            else None
        )
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def procesar_pago(cita_id):
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if pago.estado in [Pago.Estado.COMPLETADO, Pago.Estado.REEMBOLSADO]:
            return cita
        if pago.estado == Pago.Estado.REEMBOLSO_PENDIENTE:
            reembolsar = True
        else:
            reembolsar = False
        if pago.procesando_hasta and pago.procesando_hasta > timezone.now():
            return cita
        if not pago.orden_id:
            return cita
        _expirar(cita, pago)
        if not reembolsar:
            pago.procesando_hasta = timezone.now() + timedelta(seconds=120)
            pago.save()
    if reembolsar:
        return _reembolsar(cita_id)
    orden = None
    try:
        api = PayPalClient()
        orden = api.consultar(pago.orden_id)
        _verificar_orden(cita, pago, orden)
        captura = _captura(orden)
        if orden.get("status") == "APPROVED" and captura is None:
            with transaction.atomic():
                cita, pago = _bloquear(cita_id)
                _expirar(cita, pago)
                if cita.estado != PENDIENTE or not cita.ocupacion.activa:
                    pago.procesando_hasta = None
                    if pago.captura_solicitada_en is None:
                        pago.estado = Pago.Estado.CERRADO
                        pago.proxima_revision = None
                    pago.save()
                    return cita
                ahora = timezone.now()
                if pago.captura_solicitada_en is None and ahora >= cita.expira_en:
                    _expirar(cita, pago)
                    return cita
                pago.captura_solicitada_en = pago.captura_solicitada_en or ahora
                pago.estado = Pago.Estado.VERIFICANDO
                pago.save()
            orden = api.capturar(pago)
            _verificar_orden(cita, pago, orden)
        return _aplicar_resultado(cita_id, orden)
    except PayPalError as exc:
        if exc.codigo == "IMPORTE" and orden and _captura(orden):
            return _aplicar_resultado(cita_id, orden)
        with transaction.atomic():
            cita, pago = _bloquear(cita_id)
            if not exc.recuperable and (
                pago.captura_solicitada_en is None
                or exc.codigo == "INSTRUMENT_DECLINED"
            ):
                pago.estado = Pago.Estado.FALLIDO
                pago.detalle = "PayPal rechazó el pago de prueba."
                pago.procesando_hasta = None
                pago.save()
                if cita.estado == PENDIENTE:
                    _transicionar(cita, Cita.Estado.PAGO_FALLIDO, pago.detalle)
            else:
                _revision(
                    pago,
                    "Verificando el resultado con PayPal Sandbox; no se duplicará el cobro.",
                )
        return cita
    except IntegrityError:
        with transaction.atomic():
            cita, pago = _bloquear(cita_id)
            _revision(
                pago,
                "La referencia del pago necesita revisión; no se confirmará dos veces.",
            )
        return cita


def _aplicar_resultado(cita_id, orden):
    requiere_reembolso = False
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        captura = _captura(orden)
        if (
            cita.estado != PENDIENTE
            and pago.captura_solicitada_en is None
            and not (captura and captura.get("status") == "COMPLETED")
        ):
            pago.estado = Pago.Estado.CERRADO
            pago.procesando_hasta = None
            pago.proxima_revision = None
            pago.save()
            return cita
        if captura and captura.get("status") == "COMPLETED":
            try:
                importe = Decimal(captura["amount"]["value"])
                moneda = captura["amount"]["currency_code"]
                captura_id = PayPalClient._id(captura.get("id"))
                if not importe.is_finite() or not Decimal("0") < importe <= Decimal(
                    "999999.99"
                ):
                    raise ValueError("Importe inválido")
            except (KeyError, TypeError, ValueError, InvalidOperation, PayPalError):
                _revision(pago, "La respuesta necesita verificación adicional.")
                return cita
            pago.captura_id = captura_id
            pago.importe_capturado = importe
            pago.moneda_capturada = moneda
            pago.procesando_hasta = None
            vigente = (
                cita.estado == PENDIENTE
                and cita.ocupacion.activa
                and (
                    cita.expira_en > timezone.now()
                    or (
                        pago.captura_solicitada_en is not None
                        and pago.captura_solicitada_en <= cita.expira_en
                    )
                )
            )
            if importe == cita.precio and moneda == "USD" and vigente:
                pago.estado = Pago.Estado.COMPLETADO
                pago.detalle = "Pago Sandbox verificado y capturado."
                pago.save()
                _transicionar(cita, Cita.Estado.CONFIRMADA, pago.detalle)
            elif (
                cita.estado == Cita.Estado.CONFIRMADA
                and pago.estado == Pago.Estado.COMPLETADO
            ):
                return cita
            else:
                pago.estado = Pago.Estado.REEMBOLSO_PENDIENTE
                pago.detalle = (
                    "El pago no puede confirmar esta reserva; se devolverá en Sandbox."
                )
                pago.save()
                if cita.estado == PENDIENTE:
                    _transicionar(cita, Cita.Estado.PAGO_FALLIDO, pago.detalle)
                requiere_reembolso = True
        elif (
            captura
            and captura.get("status") in ["DECLINED", "DENIED", "FAILED"]
            or orden.get("status") == "VOIDED"
        ):
            pago.estado = Pago.Estado.FALLIDO
            pago.procesando_hasta = None
            pago.detalle = "El pago de prueba fue rechazado."
            pago.save()
            if cita.estado == PENDIENTE:
                _transicionar(cita, Cita.Estado.PAGO_FALLIDO, pago.detalle)
        elif (
            orden.get("status") in ["CREATED", "PAYER_ACTION_REQUIRED", "SAVED"]
            and pago.captura_solicitada_en is None
        ):
            pago.estado = Pago.Estado.CREADO
            pago.procesando_hasta = None
            pago.proxima_revision = timezone.now() + timedelta(seconds=15)
            pago.detalle = "Falta aprobar la orden en PayPal Sandbox."
            pago.save()
        else:
            _revision(pago, "PayPal todavía está procesando el resultado de prueba.")
    if requiere_reembolso:
        return _reembolsar(cita_id)
    return cita


def _reembolsar(cita_id):
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if pago.estado != Pago.Estado.REEMBOLSO_PENDIENTE or (
            pago.procesando_hasta and pago.procesando_hasta > timezone.now()
        ):
            return cita
        pago.procesando_hasta = timezone.now() + timedelta(seconds=120)
        pago.save()
    try:
        resultado = PayPalClient().reembolsar(pago)
        completo = resultado.get("status") == "COMPLETED"
        referencia = PayPalClient._id(resultado.get("id")) if completo else None
    except PayPalError:
        resultado, completo = {}, False
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if pago.estado == Pago.Estado.REEMBOLSADO:
            return cita
        pago.procesando_hasta = None
        pago.proxima_revision = timezone.now() + timedelta(seconds=30)
        if completo:
            pago.estado = Pago.Estado.REEMBOLSADO
            pago.reembolso_id = referencia
            pago.detalle = "Pago de prueba devuelto; la cita no fue confirmada."
            EventoCita.objects.create(
                cita=cita, anterior=cita.estado, nuevo=cita.estado, motivo=pago.detalle
            )
        pago.save()
    return cita


def ejecutar_ciclo():
    registrar_latido()
    total = expirar_retenciones()
    ahora = timezone.now()
    pagos = Pago.objects.filter(orden_id__isnull=False).exclude(
        estado__in=[
            Pago.Estado.COMPLETADO,
            Pago.Estado.REEMBOLSADO,
            Pago.Estado.FALLIDO,
            Pago.Estado.CERRADO,
        ]
    )
    ids = list(
        pagos.filter(proxima_revision__lte=ahora).values_list("cita_id", flat=True)
    )
    for pk in ids:
        registrar_latido()
        procesar_pago(pk)
    registrar_latido()
    return total
