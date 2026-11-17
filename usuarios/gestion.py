from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .forms import AltaUsuarioForm, FiltroUsuariosForm, UsuarioGestionForm
from .models import Usuario
from .permisos import rol_requerido


def _guardar_cuenta(form):
    try:
        with transaction.atomic():
            form.save()
    except IntegrityError:
        form.add_error(
            None, "La cuenta cambió mientras guardabas. Revisa el nombre de usuario."
        )
        return False
    return True


@rol_requerido("ADMIN")
@require_GET
def lista(request):
    form = FiltroUsuariosForm(request.GET)
    consulta = Usuario.objects.filter(rol__in=["CLIENTE", "BARBERO"]).order_by(
        "username"
    )
    if form.is_valid():
        datos = form.cleaned_data
        if datos["q"]:
            consulta = consulta.filter(
                Q(username__icontains=datos["q"])
                | Q(first_name__icontains=datos["q"])
                | Q(last_name__icontains=datos["q"])
                | Q(email__icontains=datos["q"])
                | Q(telefono__icontains=datos["q"])
            )
        if datos["rol"]:
            consulta = consulta.filter(rol=datos["rol"])
        if datos["activo"]:
            consulta = consulta.filter(is_active=datos["activo"] == "si")
    else:
        consulta = consulta.none()
    pagina = Paginator(consulta, 20).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)
    return render(
        request,
        "usuarios/gestion.html",
        {
            "usuarios": pagina,
            "pagina": pagina,
            "filtros": form,
            "parametros": parametros.urlencode(),
        },
    )


@rol_requerido("ADMIN")
@require_http_methods(["GET", "POST"])
def crear(request):
    rol = request.GET.get("rol", "CLIENTE")
    form = AltaUsuarioForm(
        request.POST if request.method == "POST" else None, initial={"rol": rol}
    )
    if request.method == "POST" and form.is_valid() and _guardar_cuenta(form):
        messages.success(request, "Cuenta creada correctamente.")
        return redirect("usuarios:gestion")
    return render(
        request,
        "gestion/form.html",
        {"form": form, "titulo": "Nueva cuenta", "volver": "usuarios:gestion"},
    )


@rol_requerido("ADMIN")
@require_http_methods(["GET", "POST"])
def editar(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk, rol__in=["CLIENTE", "BARBERO"])
    form = UsuarioGestionForm(
        request.POST if request.method == "POST" else None, instance=usuario
    )
    if request.method == "POST" and form.is_valid() and _guardar_cuenta(form):
        messages.success(request, "Cuenta actualizada correctamente.")
        return redirect("usuarios:gestion")
    return render(
        request,
        "gestion/form.html",
        {
            "form": form,
            "titulo": f"Editar cuenta: {usuario.username}",
            "volver": "usuarios:gestion",
        },
    )
