"""Comprobantes privados generados a partir de los datos de la reserva."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


fuentes = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Reserva", str(fuentes / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("ReservaBold", str(fuentes / "VeraBd.ttf")))

ZINC = colors.HexColor("#18181b")
GRIS = colors.HexColor("#52525b")
AMBAR = colors.HexColor("#f59e0b")


def _pagina(canvas, documento):
    ancho, alto = A4
    canvas.saveState()
    canvas.setFillColor(ZINC)
    canvas.rect(0, alto - 112, ancho, 112, fill=1, stroke=0)
    canvas.setFillColor(AMBAR)
    canvas.rect(0, alto - 116, ancho, 4, fill=1, stroke=0)
    canvas.setFont("ReservaBold", 19)
    canvas.drawString(42, alto - 37, "DESTINY 3")
    canvas.setFillColor(colors.white)
    canvas.setFont("Reserva", 9)
    canvas.drawString(42, alto - 55, "BARBERÍA")
    canvas.setFont("ReservaBold", 21)
    canvas.drawString(42, alto - 89, "Comprobante de reserva")
    canvas.setStrokeColor(colors.HexColor("#e4e4e7"))
    canvas.line(42, 65, ancho - 42, 65)
    canvas.setFillColor(GRIS)
    canvas.setFont("Reserva", 8)
    canvas.drawRightString(ancho - 42, 49, str(documento.page))
    canvas.restoreState()


def generar_pdf(cita):
    if not cita.comprobante_disponible:
        raise ValueError("La reserva no tiene un pago confirmado.")
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=42, rightMargin=42,
        topMargin=140, bottomMargin=84,
        title="Comprobante de reserva", author="Destiny 3",
    )
    normal = ParagraphStyle("Normal", fontName="Reserva", fontSize=10, leading=15, textColor=ZINC)
    etiqueta = ParagraphStyle("Etiqueta", parent=normal, fontSize=9, textColor=GRIS)
    destacado = ParagraphStyle("Destacado", parent=normal, fontName="ReservaBold", fontSize=13, leading=19)
    numero = ParagraphStyle("Numero", parent=normal, fontSize=9, leading=14)

    def parrafo(texto, estilo=normal):
        return Paragraph(escape(str(texto)), estilo)

    inicio = timezone.localtime(cita.inicio)
    fin = timezone.localtime(cita.fin)
    emision = timezone.localtime(cita.fecha_comprobante)
    contenido = [
        parrafo("PAGO CONFIRMADO", destacado),
        Spacer(1, 12),
        parrafo("Número de comprobante", etiqueta),
        parrafo(cita.numero_comprobante, numero),
        Spacer(1, 9),
        parrafo(f"Fecha de emisión: {emision:%d/%m/%Y %H:%M} (Panamá)", etiqueta),
        Spacer(1, 22),
    ]
    datos = [
        ("Cliente", cita.cliente_nombre),
        ("Servicio", cita.servicio_nombre),
        ("Barbero", cita.barbero_nombre),
        ("Fecha de la cita", inicio.strftime("%d/%m/%Y")),
        ("Horario", f"{inicio:%H:%M} - {fin:%H:%M} (Panamá, UTC-5)"),
        ("Duración", f"{cita.duracion_minutos} minutos"),
        ("Medio de pago", "PayPal"),
        ("Estado del pago", "Confirmado"),
        ("Transacción", cita.pago.captura_id),
    ]
    tabla = Table(
        [[parrafo(nombre, etiqueta), parrafo(valor)] for nombre, valor in datos],
        colWidths=[125, documento.width - 125], hAlign="LEFT",
    )
    tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e4e4e7")),
    ]))
    contenido.extend([tabla, Spacer(1, 22)])
    total = Table(
        [[parrafo("TOTAL", destacado), parrafo(f"{cita.moneda} {cita.precio:.2f}", destacado)]],
        colWidths=[documento.width - 140, 140],
    )
    total.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
        ("BOX", (0, 0), (-1, -1), 0.75, AMBAR),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ]))
    contenido.extend([total, Spacer(1, 18), parrafo("Gracias por elegir nuestra barbería.", etiqueta)])
    documento.build(contenido, onFirstPage=_pagina, onLaterPages=_pagina)
    return buffer.getvalue()
