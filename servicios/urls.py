from django.urls import path

from . import views

app_name = "servicios"

urlpatterns = [
    path("gestion/", views.gestion, name="gestion"),
    path("gestion/nuevo/", views.editar, name="crear"),
    path("gestion/<int:pk>/", views.editar, name="editar"),
    path("", views.ServicioListView.as_view(), name="lista"),
]
