from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.views.generic import TemplateView

from .forms import LoginForm, RegistroForm
from .models import Usuario
from .permisos import RolRequeridoMixin


def registro(request):
    if request.user.is_authenticated:
        return redirect("usuarios:redirigir_por_rol")
    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "¡Cuenta creada correctamente!")
        return redirect("usuarios:redirigir_por_rol")
    return render(request, "usuarios/registro.html", {"form": form})


class CustomLoginView(LoginView):
    template_name = "usuarios/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def redirigir_por_rol(request):
    """Envía al usuario a la pantalla que le corresponde según su rol."""
    destinos = {
        Usuario.Rol.CLIENTE: "usuarios:panel_cliente",
        Usuario.Rol.BARBERO: "usuarios:panel_barbero",
        Usuario.Rol.ADMIN: "usuarios:panel_admin",
    }
    return redirect(destinos.get(request.user.rol, "home"))


class PanelClienteView(RolRequeridoMixin, TemplateView):
    template_name = "usuarios/panel_cliente.html"
    roles_permitidos = [Usuario.Rol.CLIENTE]


class PanelBarberoView(RolRequeridoMixin, TemplateView):
    template_name = "usuarios/panel_barbero.html"
    roles_permitidos = [Usuario.Rol.BARBERO]


class PanelAdminView(RolRequeridoMixin, TemplateView):
    template_name = "usuarios/panel_admin.html"
    roles_permitidos = [Usuario.Rol.ADMIN]