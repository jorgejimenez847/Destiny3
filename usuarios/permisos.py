from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


class RolRequeridoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Para vistas basadas en clases.
    Sin sesión -> redirige al login. Con rol incorrecto -> 403.
    Uso: class MiVista(RolRequeridoMixin, TemplateView):
             roles_permitidos = [Usuario.Rol.BARBERO]
    """
    roles_permitidos = []

    def test_func(self):
        return self.request.user.rol in self.roles_permitidos


def rol_requerido(*roles):
    """Para vistas basadas en funciones.
    Uso: @rol_requerido(Usuario.Rol.ADMIN)
    """
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.rol not in roles:
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador