from django.urls import path
from . import paneles, views

app_name = "reservas"
urlpatterns = [
    path("", views.lista, name="lista"),
    path("gestion/", paneles.gestion, name="gestion"),
    path("gestion/<uuid:pk>/", paneles.detalle, name="gestion_detalle"),
    path("gestion/<uuid:pk>/estado/", paneles.estado, name="estado"),
    path("resumen/", views.resumen, name="resumen"),
    path("confirmar/", views.confirmar, name="confirmar"),
    path("<uuid:pk>/", views.detalle, name="detalle"),
    path("<uuid:pk>/comprobante/", views.comprobante, name="comprobante"),
    path("<uuid:pk>/pagar/", views.pagar, name="pagar"),
    path("<uuid:pk>/retorno/", views.retorno, name="retorno"),
    path("<uuid:pk>/verificar/", views.verificar, name="verificar"),
    path("<uuid:pk>/cancelar-pago/", views.cancelar_pago, name="cancelar_pago"),
    path("<uuid:pk>/cancelar/", views.cancelar, name="cancelar"),
]
