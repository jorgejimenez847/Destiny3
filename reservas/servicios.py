"""Reservas y transiciones. Orden de bloqueos: perfil, cita y pago."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from barberos.models import Ocupacion, PerfilBarbero
from servicios.models import Servicio
from .models import Cita, EstadoProcesador, EventoCita, Pago, SolicitudCancelacion
from .paypal import API, PayPalClient, PayPalError, enlace_aprobacion

PENDIENTE = Cita.Estado.PENDIENTE
TRANSICIONES_OPERATIVAS = {
    Cita.Estado.CONFIRMADA: (Cita.Estado.EN_ATENCION, Cita.Estado.NO_ASISTIO),
    Cita.Estado.EN_ATENCION: (Cita.Estado.COMPLETADA,),
}


def _puede_atender(cita, actor):
    return (
        actor.is_authenticated
        and actor.is_active
        and (
            actor.rol == "ADMIN"
            or (actor.rol == "BARBERO" and cita.barbero.usuario_id == actor.pk)
        )
    )


def estados_operativos_permitidos(cita, actor):
    if not _puede_atender(cita, actor):
        return []
    if (
        cita.cancelacion_pendiente
        or cita.pago.estado != Pago.Estado.COMPLETADO
        or timezone.now() < cita.inicio
    ):
        return []
    return [
        (estado, Cita.Estado(estado).label)
        for estado in TRANSICIONES_OPERATIVAS.get(cita.estado, ())
    ]


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
    cita.pago = pago
    pago.cita = cita
    return cita, pago


def _transicionar(cita, nuevo, motivo, actor=None):
    permitidas = {
        PENDIENTE: {
            Cita.Estado.CONFIRMADA,
            Cita.Estado.CANCELADA,
            Cita.Estado.EXPIRADA,
            Cita.Estado.PAGO_FALLIDO,
        },
        **TRANSICIONES_OPERATIVAS,
        Cita.Estado.CONFIRMADA: (
            *TRANSICIONES_OPERATIVAS[Cita.Estado.CONFIRMADA],
            Cita.Estado.CANCELADA,
        ),
    }
    if nuevo == Cita.Estado.CANCELADA and cita.estado == Cita.Estado.CONFIRMADA:
        solicitud = getattr(cita, "cancelacion", None)
        if (
            cita.pago.estado != Pago.Estado.REEMBOLSADO
            or not solicitud
            or not solicitud.finalizada_en
        ):
            raise ValidationError("La cancelación requiere un reembolso confirmado.")
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
        pago.detalle = pago.detalle_actual
        pago.procesando_hasta = None
        pago.proxima_revision = None
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
    duracion_esperada=None,
):
    if not cliente.is_active or cliente.rol != "CLIENTE":
        raise PermissionDenied
    comprobar_procesador()
    try:
        barbero = PerfilBarbero.objects.select_for_update().get(pk=barbero_id)
    except PerfilBarbero.DoesNotExist:
        raise ValidationError(
            "El barbero ya no está disponible. Consulta los horarios nuevamente."
        ) from None
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
    try:
        servicio = Servicio.objects.get(pk=servicio_id)
    except Servicio.DoesNotExist:
        raise ValidationError(
            "El servicio ya no está disponible. Consulta el catálogo nuevamente."
        ) from None
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
        cliente_nombre=cliente.get_full_name().strip() or cliente.username,
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
        motivo="Selección confirmada; horario retenido para el pago.",
        actor=cliente,
    )
    return cita


def cancelar_cita(cita_id, actor, motivo=None):
    ahora = timezone.now()
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if (
            not actor.is_authenticated
            or not actor.is_active
            or actor.rol != "CLIENTE"
            or cita.cliente_id != actor.pk
        ):
            raise PermissionDenied
        solicitud = getattr(cita, "cancelacion", None)
        if solicitud:
            # Los reintentos conservan la solicitud aceptada y su plazo original.
            return cita
        _expirar(cita, pago)
        if cita.estado in [Cita.Estado.CANCELADA, Cita.Estado.EXPIRADA]:
            return cita
        pagada = cita.estado == Cita.Estado.CONFIRMADA
        if cita.estado not in [PENDIENTE, Cita.Estado.CONFIRMADA]:
            raise ValidationError("Esta reserva no permite una cancelación.")
        if pagada:
            if cita.inicio - ahora < timedelta(hours=24):
                raise ValidationError(
                    "Las reservas pagadas requieren al menos 24 horas de anticipación para cancelarse."
                )
            if (
                pago.estado != Pago.Estado.COMPLETADO
                or not pago.captura_verificada
                or pago.reembolso_id
                or pago.reembolso_iniciado_en is not None
                or (pago.procesando_hasta and pago.procesando_hasta > ahora)
                or not cita.ocupacion.activa
            ):
                raise ValidationError(
                    "El pago necesita revisión antes de solicitar la cancelación."
                )
            try:
                PayPalClient._id(pago.orden_id)
                PayPalClient._id(pago.captura_id)
            except PayPalError:
                raise ValidationError(
                    "La referencia del pago necesita revisión."
                ) from None
        elif (
            pago.captura_solicitada_en is not None
            or pago.captura_id
            or pago.importe_capturado is not None
            or pago.estado
            not in [
                Pago.Estado.NUEVO,
                Pago.Estado.CREANDO,
                Pago.Estado.CREADO,
                Pago.Estado.VERIFICANDO,
            ]
        ):
            raise ValidationError(
                "El pago está en verificación. Espera su resultado antes de cancelar."
            )
        elif ahora >= cita.inicio:
            raise ValidationError("No se puede cancelar una cita que ya comenzó.")
        motivo = "Solicitud del cliente." if motivo is None and not pagada else motivo
        if (
            not isinstance(motivo, str)
            or not motivo.strip()
            or len(motivo.strip()) > 180
        ):
            raise ValidationError(
                "Indica un motivo de cancelación de hasta 180 caracteres."
            )
        motivo = motivo.strip()
        if not pagada:
            _transicionar(
                cita, Cita.Estado.CANCELADA, f"Cancelación del cliente: {motivo}", actor
            )
            pago.estado = Pago.Estado.CERRADO
            pago.detalle = pago.detalle_actual
            pago.procesando_hasta = None
            pago.proxima_revision = None
            pago.save()
            return cita
        SolicitudCancelacion.objects.create(
            cita=cita, solicitante=actor, motivo=motivo, solicitada_en=ahora
        )
        pago.estado = Pago.Estado.REEMBOLSO_PENDIENTE
        pago.detalle = (
            "Cancelación solicitada. El reembolso está pendiente de confirmación."
        )
        pago.procesando_hasta = None
        pago.proxima_revision = ahora
        pago.save()
        EventoCita.objects.create(
            cita=cita,
            anterior=cita.estado,
            nuevo=cita.estado,
            motivo=f"Solicitud de cancelación: {motivo}",
            actor=actor,
        )
    return _reembolsar(cita_id)


@transaction.atomic
def cambiar_estado_operativo(cita_id, nuevo, actor):
    cita, pago = _bloquear(cita_id)
    autorizado = _puede_atender(cita, actor)
    if not autorizado or nuevo not in [
        Cita.Estado.EN_ATENCION,
        Cita.Estado.COMPLETADA,
        Cita.Estado.NO_ASISTIO,
    ]:
        raise PermissionDenied
    if (
        cita.cancelacion_pendiente
        or pago.estado != Pago.Estado.COMPLETADO
        or timezone.now() < cita.inicio
    ):
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
            if cita.estado != PENDIENTE:
                pago.estado = Pago.Estado.CERRADO
                pago.detalle = pago.detalle_actual
                pago.proxima_revision = None
            else:
                pago.estado = (
                    Pago.Estado.NUEVO if exc.recuperable else Pago.Estado.FALLIDO
                )
                pago.detalle = "No se pudo preparar la orden de pago."
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
        if not pago.orden_id and not reembolsar:
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
            if pago.estado in [
                Pago.Estado.COMPLETADO,
                Pago.Estado.REEMBOLSADO,
                Pago.Estado.REEMBOLSO_PENDIENTE,
            ]:
                return cita
            if not exc.recuperable and (
                pago.captura_solicitada_en is None
                or exc.codigo == "INSTRUMENT_DECLINED"
            ):
                pago.estado = Pago.Estado.FALLIDO
                pago.detalle = "PayPal rechazó el pago."
                pago.procesando_hasta = None
                pago.save()
                if cita.estado == PENDIENTE:
                    _transicionar(cita, Cita.Estado.PAGO_FALLIDO, pago.detalle)
            else:
                _revision(
                    pago,
                    "Verificando el resultado con PayPal; no se duplicará el cobro.",
                )
        return cita
    except IntegrityError:
        with transaction.atomic():
            cita, pago = _bloquear(cita_id)
            if pago.estado in [
                Pago.Estado.COMPLETADO,
                Pago.Estado.REEMBOLSADO,
                Pago.Estado.REEMBOLSO_PENDIENTE,
            ]:
                return cita
            _revision(
                pago,
                "La referencia del pago necesita revisión; no se confirmará dos veces.",
            )
        return cita


def _aplicar_resultado(cita_id, orden):
    requiere_reembolso = False
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if pago.estado in [
            Pago.Estado.COMPLETADO,
            Pago.Estado.REEMBOLSADO,
            Pago.Estado.REEMBOLSO_PENDIENTE,
        ]:
            return cita
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
                pago.detalle = "Pago confirmado correctamente."
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
                    "El pago no puede confirmar esta reserva; se devolverá el importe."
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
            pago.detalle = "El pago fue rechazado."
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
            pago.detalle = "Falta aprobar la orden en PayPal."
            pago.save()
        else:
            _revision(pago, "PayPal todavía está procesando el pago.")
    if requiere_reembolso:
        return _reembolsar(cita_id)
    return cita


def _datos_reembolso(resultado, pago):
    try:
        referencia = PayPalClient._id(resultado["id"])
        estado = resultado["status"]
        importe = Decimal(resultado["amount"]["value"])
        moneda = resultado["amount"]["currency_code"]
        captura_urls = {
            base + "/v2/payments/captures/" + pago.captura_id
            for base in (API, "https://api.sandbox.paypal.com")
        }
        vinculada = any(
            isinstance(link, dict)
            and link.get("rel") == "up"
            and link.get("href") in captura_urls
            for link in resultado.get("links", [])
        )
        if (
            estado not in ["COMPLETED", "PENDING", "FAILED", "CANCELLED"]
            or not importe.is_finite()
            or importe <= 0
            or importe != pago.importe_capturado
            or moneda != pago.moneda_capturada
            or not vinculada
            or (pago.reembolso_id and pago.reembolso_id != referencia)
        ):
            raise PayPalError()
        return referencia, estado
    except (KeyError, TypeError, AttributeError, InvalidOperation, ValueError):
        raise PayPalError() from None


@transaction.atomic
def _guardar_reembolso(cita_id, intento, datos, error):
    cita, pago = _bloquear(cita_id)
    if (
        pago.estado != Pago.Estado.REEMBOLSO_PENDIENTE
        or pago.procesando_hasta != intento
    ):
        return cita
    anterior = (pago.reembolso_id, pago.reembolso_estado, pago.detalle)
    pago.procesando_hasta = None
    pago.proxima_revision = timezone.now() + timedelta(seconds=30)
    pago.detalle = error
    if datos:
        pago.reembolso_id, pago.reembolso_estado = datos
        if pago.reembolso_estado == "COMPLETED":
            pago.estado = Pago.Estado.REEMBOLSADO
            pago.reembolso_finalizado_en = timezone.now()
            pago.proxima_revision = None
            solicitud = getattr(cita, "cancelacion", None)
            pago.detalle = (
                "Reembolso confirmado. Reserva cancelada."
                if solicitud
                else "Pago devuelto; la cita no fue confirmada."
            )
            pago.save()
            if solicitud:
                solicitud.finalizada_en = pago.reembolso_finalizado_en
                solicitud.save(update_fields=["finalizada_en"])
                _transicionar(
                    cita, Cita.Estado.CANCELADA, pago.detalle, solicitud.solicitante
                )
            else:
                EventoCita.objects.create(
                    cita=cita,
                    anterior=cita.estado,
                    nuevo=cita.estado,
                    motivo=pago.detalle,
                )
            return cita
        pago.detalle = (
            "PayPal está procesando el reembolso."
            if pago.reembolso_estado == "PENDING"
            else "El reembolso no se completó. Contacta con la barbería para revisar la devolución."
        )
    pago.save()
    if anterior != (pago.reembolso_id, pago.reembolso_estado, pago.detalle):
        EventoCita.objects.create(
            cita=cita, anterior=cita.estado, nuevo=cita.estado, motivo=pago.detalle
        )
    return cita


def _reembolsar(cita_id):
    with transaction.atomic():
        cita, pago = _bloquear(cita_id)
        if pago.estado != Pago.Estado.REEMBOLSO_PENDIENTE or (
            pago.procesando_hasta and pago.procesando_hasta > timezone.now()
        ):
            return cita
        reintento = pago.reembolso_iniciado_en is not None
        intento = timezone.now() + timedelta(seconds=120)
        pago.procesando_hasta = intento
        pago.reembolso_iniciado_en = pago.reembolso_iniciado_en or timezone.now()
        pago.save()
    datos = None
    error = "No se pudo confirmar el reembolso. Lo volveremos a comprobar."
    try:
        api = PayPalClient()
        if pago.reembolso_id:
            resultado = api.consultar_reembolso(pago.reembolso_id)
        else:
            resultado = api.buscar_reembolso(pago) if reintento else None
            if resultado is None:
                resultado = api.reembolsar(pago)
        datos = _datos_reembolso(resultado, pago)
    except PayPalError:
        pass
    try:
        return _guardar_reembolso(cita_id, intento, datos, error)
    except IntegrityError:
        return _guardar_reembolso(
            cita_id,
            intento,
            None,
            "La referencia del reembolso necesita revisión. La cancelación sigue pendiente.",
        )


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
