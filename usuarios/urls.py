from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "usuarios"

urlpatterns = [
    path("registro/", views.registro, name="registro"),
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("redirigir/", views.redirigir_por_rol, name="redirigir_por_rol"),

    # Paneles por rol
    path("panel/cliente/", views.PanelClienteView.as_view(), name="panel_cliente"),
    path("panel/barbero/", views.PanelBarberoView.as_view(), name="panel_barbero"),
    path("panel/admin/", views.PanelAdminView.as_view(), name="panel_admin"),

    # Recuperación de contraseña
    path(
        "recuperar/",
        auth_views.PasswordResetView.as_view(
            template_name="usuarios/password_reset.html",
            email_template_name="usuarios/password_reset_email.txt",
            success_url=reverse_lazy("usuarios:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "recuperar/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="usuarios/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "recuperar/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="usuarios/password_reset_confirm.html",
            success_url=reverse_lazy("usuarios:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "recuperar/completo/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="usuarios/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]