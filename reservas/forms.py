from django import forms
from barberos.forms import EstiloForm


class SeleccionForm(EstiloForm, forms.Form):
    servicio = forms.IntegerField(min_value=1)
    barbero = forms.IntegerField(min_value=1)
    inicio = forms.DateTimeField()


class ConfirmacionForm(forms.Form):
    seleccion = forms.CharField(widget=forms.HiddenInput)


class CancelacionForm(EstiloForm, forms.Form):
    motivo = forms.CharField(
        label="Motivo de la cancelación",
        max_length=180,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class EstadoCitaForm(EstiloForm, forms.Form):
    estado = forms.ChoiceField(label="Nuevo estado", choices=[])
    confirmar = forms.BooleanField(label="Confirmo el cambio de estado")

    def __init__(self, *args, opciones=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["estado"].choices = opciones


class FiltroCitasForm(EstiloForm, forms.Form):
    q = forms.CharField(
        label="Buscar cliente, servicio o barbero", max_length=100, required=False
    )
    desde = forms.DateField(
        required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    estado = forms.ChoiceField(required=False)
    barbero = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="Todos los barberos"
    )
    servicio = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="Todos los servicios"
    )

    def __init__(self, *args, administrador=False, **kwargs):
        from barberos.models import PerfilBarbero
        from servicios.models import Servicio
        from .models import Cita

        super().__init__(*args, **kwargs)
        self.fields["estado"].choices = [
            ("", "Todos los estados"),
            *Cita.Estado.choices,
        ]
        self.fields["servicio"].queryset = Servicio.objects.all()
        if administrador:
            self.fields["barbero"].queryset = PerfilBarbero.objects.select_related(
                "usuario"
            )
        else:
            self.fields.pop("barbero")

    def clean(self):
        datos = super().clean()
        if (
            datos.get("desde")
            and datos.get("hasta")
            and datos["desde"] > datos["hasta"]
        ):
            raise forms.ValidationError(
                "La fecha final debe ser igual o posterior a la inicial."
            )
        return datos
