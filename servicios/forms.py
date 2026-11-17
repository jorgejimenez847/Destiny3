from django import forms
from barberos.forms import EstiloForm
from .models import Servicio


class ServicioForm(EstiloForm, forms.ModelForm):
    class Meta:
        model = Servicio
        fields = ["nombre", "descripcion", "duracion_minutos", "precio", "activo"]
        labels = {"precio": "Precio (USD)", "duracion_minutos": "Duración (minutos)"}
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}


class FiltroServiciosForm(EstiloForm, forms.Form):
    q = forms.CharField(label="Buscar servicio", max_length=100, required=False)
    activo = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=[("", "Todos los servicios"), ("si", "Activos"), ("no", "Inactivos")],
    )
