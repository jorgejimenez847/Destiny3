from django.urls import path
from . import views

app_name = "barberos"
urlpatterns = [
    path("disponibilidad/", views.disponibilidad, name="disponibilidad"),
    path("gestion/", views.gestion, name="gestion"),
    path("nuevo/", views.perfil_form, name="crear"),
    path("mi-perfil/", views.mi_perfil, name="mi_perfil"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.perfil_form, name="editar"),
]
for tipo in ["horario", "bloqueo"]:
    urlpatterns += [
        path(f"<int:pk>/{tipo}/nuevo/", views.agenda_form, {"tipo": tipo}, name=f"{tipo}_crear"),
        path(f"<int:pk>/{tipo}/<int:item>/editar/", views.agenda_form, {"tipo": tipo}, name=f"{tipo}_editar"),
        path(f"<int:pk>/{tipo}/<int:item>/eliminar/", views.agenda_eliminar, {"tipo": tipo}, name=f"{tipo}_eliminar"),
    ]
