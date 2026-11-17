from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from barberos.forms import EstiloForm
from .models import Usuario

User = get_user_model()


class RegistroForm(UserCreationForm):
    email = forms.EmailField(label="Correo electrónico", required=True)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "telefono")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.rol = Usuario.Rol.CLIENTE  # el registro público siempre crea Clientes
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    pass


class CorreoUnicoMixin:
    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if (
            Usuario.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return email


class AltaUsuarioForm(EstiloForm, CorreoUnicoMixin, UserCreationForm):
    email = forms.EmailField(label="Correo electrónico")
    rol = forms.ChoiceField(choices=[("CLIENTE", "Cliente"), ("BARBERO", "Barbero")])

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "email", "telefono", "rol"]


class UsuarioGestionForm(EstiloForm, CorreoUnicoMixin, forms.ModelForm):
    email = forms.EmailField(label="Correo electrónico")

    class Meta:
        model = Usuario
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "telefono",
            "is_active",
        ]
        labels = {"is_active": "Cuenta activa"}


class FiltroUsuariosForm(EstiloForm, forms.Form):
    q = forms.CharField(
        label="Buscar nombre, usuario, correo o teléfono",
        required=False,
        max_length=100,
    )
    rol = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Todos los roles"),
            ("CLIENTE", "Cliente"),
            ("BARBERO", "Barbero"),
        ],
    )
    activo = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=[("", "Todas las cuentas"), ("si", "Activas"), ("no", "Inactivas")],
    )
