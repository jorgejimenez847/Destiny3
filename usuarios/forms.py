from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

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