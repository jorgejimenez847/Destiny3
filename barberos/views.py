from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from usuarios.models import Usuario
from usuarios.permisos import rol_requerido
from .forms import BloqueoForm, HorarioForm, PerfilForm
from .models import Bloqueo, Horario, PerfilBarbero


@rol_requerido(Usuario.Rol.ADMIN)
def gestion(request):
    perfiles = PerfilBarbero.objects.select_related("usuario").prefetch_related("servicios")
    return render(request, "barberos/gestion.html", {"perfiles": perfiles})


@rol_requerido(Usuario.Rol.ADMIN)
@require_http_methods(["GET", "POST"])
def perfil_form(request, pk=None):
    perfil = get_object_or_404(PerfilBarbero, pk=pk) if pk else PerfilBarbero()
    form = PerfilForm(request.POST if request.method == "POST" else None, instance=perfil)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                perfil = form.save()
        except (ValidationError, IntegrityError):
            form.add_error(None, "No se pudo guardar. Verifica el usuario y vuelve a intentarlo.")
        else:
            messages.success(request, "Perfil guardado correctamente.")
            return redirect("barberos:detalle", pk=perfil.pk)
    return render(request, "barberos/form.html", {"form": form, "titulo": "Editar perfil" if pk else "Nuevo perfil de barbero", "volver": "barberos:gestion"})


@login_required
def detalle(request, pk):
    perfil = get_object_or_404(PerfilBarbero.objects.select_related("usuario"), pk=pk)
    if request.user.rol != Usuario.Rol.ADMIN and not (
        request.user.rol == Usuario.Rol.BARBERO and perfil.usuario_id == request.user.pk):
        raise PermissionDenied
    return render(request, "barberos/detalle.html", {"perfil": perfil,
        "horarios": perfil.horario_set.all(), "bloqueos": perfil.bloqueo_set.all(),
        "gestiona": request.user.rol == Usuario.Rol.ADMIN})


@rol_requerido(Usuario.Rol.BARBERO)
def mi_perfil(request):
    perfil = PerfilBarbero.objects.filter(usuario=request.user).first()
    if perfil:
        return redirect("barberos:detalle", pk=perfil.pk)
    return render(request, "barberos/sin_perfil.html")


@rol_requerido(Usuario.Rol.ADMIN)
@require_http_methods(["GET", "POST"])
def agenda_form(request, pk, tipo, item=None):
    perfil = get_object_or_404(PerfilBarbero, pk=pk)
    modelo, formulario, etiqueta = (Horario, HorarioForm, "horario") if tipo == "horario" else (Bloqueo, BloqueoForm, "bloqueo")
    instancia = get_object_or_404(modelo, pk=item, barbero=perfil) if item else modelo(barbero=perfil)
    form = formulario(request.POST if request.method == "POST" else None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        except IntegrityError:
            form.add_error(None, "La agenda cambió mientras guardabas. Revisa los datos y vuelve a intentar.")
        else:
            messages.success(request, f"{etiqueta.capitalize()} guardado correctamente.")
            return redirect("barberos:detalle", pk=perfil.pk)
    return render(request, "barberos/form.html", {"form": form,
        "titulo": ("Editar " if item else "Añadir ") + etiqueta, "perfil": perfil})


@rol_requerido(Usuario.Rol.ADMIN)
@require_http_methods(["GET", "POST"])
def agenda_eliminar(request, pk, tipo, item):
    perfil = get_object_or_404(PerfilBarbero, pk=pk)
    modelo = Horario if tipo == "horario" else Bloqueo
    instancia = get_object_or_404(modelo, pk=item, barbero=perfil)
    if request.method == "POST":
        try:
            with transaction.atomic():
                PerfilBarbero.objects.select_for_update().get(pk=perfil.pk)
                instancia.delete()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Registro eliminado correctamente.")
        return redirect("barberos:detalle", pk=perfil.pk)
    return render(request, "barberos/confirmar.html", {"objeto": instancia, "perfil": perfil})


@require_http_methods(["GET"])
def disponibilidad(request):
    from .forms import DisponibilidadForm
    from .disponibilidad import calcular_disponibilidad
    from servicios.models import Servicio
    form=DisponibilidadForm(request.GET if request.GET else None)
    franjas=None
    if form.is_bound and form.is_valid():
        try:
            franjas=calcular_disponibilidad(form.cleaned_data["barbero"],
                form.cleaned_data["servicio"],form.cleaned_data["fecha"])
        except ValidationError as exc:
            form.add_error(None,"; ".join(exc.messages))
    perfiles=PerfilBarbero.objects.filter(activo=True,usuario__is_active=True,usuario__rol="BARBERO").select_related("usuario").prefetch_related("servicios")
    opciones=[{"id":p.pk,"nombre":str(p),"servicios":[s.pk for s in p.servicios.all() if s.activo]} for p in perfiles]
    return render(request,"barberos/disponibilidad.html",{"form":form,"franjas":franjas,"opciones_barberos":opciones,
        "hay_barberos":PerfilBarbero.objects.filter(activo=True,usuario__is_active=True,usuario__rol="BARBERO").exists(),
        "hay_servicios":Servicio.objects.filter(activo=True).exists()})
