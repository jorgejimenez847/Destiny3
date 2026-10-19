# Demostración

## Preparar

Activa el entorno, inicia PostgreSQL, aplica migraciones y ejecuta los comandos demo y Tailwind según README. Configura PayPal Sandbox y comprueba que tienes una cuenta Personal compradora. Inicia el sitio con `python scripts/iniciar.py`.

## Recorrido

1. Inicio → Registro/Login → Servicios. Muestra precio y duración.
2. Administrador → Gestionar barberos. Revisa especialidad, servicios, turnos, descansos y bloqueos. Intenta guardar un horario invertido o superpuesto.
3. Cliente → Disponibilidad. Compara servicios de distinta duración y consulta el día bloqueado. Selecciona un intervalo libre.
4. Revisa el resumen y confirma. Abre el mismo horario en otra sesión de cliente: ya no debe ofrecerse.
5. Continúa a PayPal Sandbox, aprueba con la cuenta compradora y vuelve al sitio. Verifica que la cita cambie a Confirmada y que aparezca su referencia de captura.
6. En otra reserva pendiente, cancela y comprueba que el horario se libera. Para mostrar expiración automática, deja vencer una retención con el procesador activo.
7. Comprueba que otro cliente no puede consultar esa reserva y que un barbero no puede administrar perfiles ajenos.

No se usan pagos Live. Una respuesta de pago incierta mantiene el horario protegido; el procesador consulta y reintenta sin duplicar cobros. Los pagos tardíos incompatibles se devuelven en Sandbox.

## Evidencia técnica

```powershell
python manage.py test --noinput
python manage.py test reservas.tests.test_concurrencia --noinput
python manage.py makemigrations --check --dry-run
git status --short --branch
```

Las pruebas simuladas de PayPal son distintas de una aprobación y captura real en Sandbox. El resultado comprobado de cada una se registra en VALIDACION.md.
