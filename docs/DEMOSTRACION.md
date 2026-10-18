# Guion de demostración del Parcial 2

## Preparación

1. Activa dsw8408 y abre la raíz con manage.py.
2. Docker Desktop en ejecución y PostgreSQL disponible. Ejecuta check, migrate, tailwind build y las pruebas según README.
3. Ejecuta crear_datos_demo y crear_agenda_demo. Conserva la fecha que imprime el comando y las credenciales locales; las contraseñas existentes no cambian.
4. Inicia Django y el watcher Tailwind en terminales separadas. Abre 127.0.0.1:8000.

## Recorrido de 6–8 minutos

- **Fase 1**: muestra el catálogo con precios y duración. Login de cada rol y recuperación por consola. La suite original verifica registro, login/logout y recuperación.
- **Fase 2 / M03**: administrador → Gestionar barberos → perfil demo. Muestra especialidad, servicios y activo/inactivo.
- **Fase 2 / M05**: añade un turno en un día libre o edita uno sin ocupación. Intenta fin anterior al inicio. Muestra el descanso y la validación de superposición.
- **Fase 2 / M06**: enseña ausencia parcial y un día completo bloqueado. Añade un bloqueo en un hueco sin ocupación; comprueba el mensaje de éxito.
- **Fase 3 / M07**: consulta disponibilidad con servicio/barbero/fecha. Compara 30 y 50 minutos. Explica que los huecos se recalculan y no son una lista de horas guardadas.
- **Fase 3 / M08**: muestra que no aparece el intervalo ocupado demo y que no se permiten cambios de agenda que lo invaliden. Ejecuta las pruebas de concurrencia para evidenciar que PostgreSQL impide dos intervalos simultáneos superpuestos.
- **Permisos**: barbero → Mi perfil, consulta propia. Intenta /barberos/gestion/ con esa sesión: 403 con diseño del sitio.

La consulta no crea reservas ni cobra. El flujo completo, bloqueo temporal, PayPal y estados quedan expresamente para Fase 4.

## Evidencia técnica

```powershell
python manage.py test barberos.tests.test_concurrencia --noinput
python manage.py makemigrations --check --dry-run
git status --short --branch
```

Las pruebas de concurrencia usan dos conexiones independientes y barrera de sincronización, no llamadas secuenciales. La exclusión PostgreSQL sigue rechazando un conflicto al omitir validación Python; la escritura normal también bloquea por barbero.
