from django import forms
from barberos.forms import EstiloForm


class SeleccionForm(EstiloForm, forms.Form):
    servicio = forms.IntegerField(min_value=1)
    barbero = forms.IntegerField(min_value=1)
    inicio = forms.DateTimeField()


class ConfirmacionForm(forms.Form):
    seleccion = forms.CharField(widget=forms.HiddenInput)
