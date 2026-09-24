"""
URL configuration for config project.
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("cuentas/", include("usuarios.urls")),
]

# Recarga automática del navegador (solo desarrollo)
if settings.DEBUG:
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
    ]