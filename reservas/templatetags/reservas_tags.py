from django import template

register = template.Library()

# Presentación de mensajes históricos, sin modificar los registros.
MENSAJES = {
    'Selección confirmada; horario retenido para pago Sandbox.':
        'Selección confirmada; horario retenido para el pago.',
    'No se pudo preparar la orden de prueba.':
        'No se pudo preparar la orden de pago.',
    'PayPal rechazó el pago de prueba.':
        'PayPal rechazó el pago.',
    'Verificando el resultado con PayPal Sandbox; no se duplicará el cobro.':
        'Verificando el resultado con PayPal; no se duplicará el cobro.',
    'Pago Sandbox verificado y capturado.':
        'Pago confirmado correctamente.',
    'El pago no puede confirmar esta reserva; se devolverá en Sandbox.':
        'El pago no puede confirmar esta reserva; se devolverá el importe.',
    'El pago de prueba fue rechazado.':
        'El pago fue rechazado.',
    'Falta aprobar la orden en PayPal Sandbox.':
        'Falta aprobar la orden en PayPal.',
    'PayPal todavía está procesando el resultado de prueba.':
        'PayPal todavía está procesando el pago.',
    'Pago de prueba devuelto; la cita no fue confirmada.':
        'Pago devuelto; la cita no fue confirmada.',
}


@register.filter
def texto_reserva(texto):
    return MENSAJES.get(texto, texto)


@register.filter
def etiqueta_estado(valor):
    from reservas.models import Cita
    return dict(Cita.Estado.choices).get(valor, valor)
