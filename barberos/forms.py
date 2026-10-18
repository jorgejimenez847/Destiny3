from django import forms
from .models import Bloqueo, Horario, PerfilBarbero

CAMPO = "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100 focus:border-amber-400"

class EstiloForm:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = CAMPO
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "h-5 w-5 accent-amber-500"

class PerfilForm(EstiloForm, forms.ModelForm):
    class Meta:
        model = PerfilBarbero
        fields = ["usuario", "especialidad", "descripcion", "servicios", "activo"]
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3}),
                   "servicios": forms.SelectMultiple(attrs={"size": 5})}
        help_texts = {"servicios": "Selecciona uno o varios servicios (Ctrl o Cmd para seleccionar varios).",
                      "activo": "Solo los perfiles activos de usuarios activos aparecerán en disponibilidad."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["usuario"].disabled = True
        self.fields["usuario"].queryset = self.fields["usuario"].queryset.filter(rol="BARBERO")

class HorarioForm(EstiloForm, forms.ModelForm):
    class Meta:
        model = Horario
        fields = ["dia", "inicio", "fin", "descanso_inicio", "descanso_fin"]
        widgets = {name: forms.TimeInput(format="%H:%M", attrs={"type": "time"})
                   for name in ["inicio", "fin", "descanso_inicio", "descanso_fin"]}
        help_texts = {"dia": "Puedes añadir varios turnos por día si no se superponen.",
                      "descanso_inicio": "Opcional. Completa ambas horas para descontar el descanso."}

class BloqueoForm(EstiloForm, forms.ModelForm):
    class Meta:
        model = Bloqueo
        fields = ["inicio", "fin", "motivo", "nota"]
        widgets = {name: forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})
                   for name in ["inicio", "fin"]}
        help_texts = {"inicio": "Hora de Panamá. Para un día completo, comienza a las 00:00.",
                      "fin": "Para bloquear un día completo, termina a las 00:00 del día siguiente. También puedes bloquear varios días."}
