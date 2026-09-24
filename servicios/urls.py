from django.urls import path

from . import views

app_name = "servicios"

urlpatterns = [
    path("", views.ServicioListView.as_view(), name="lista"),
]