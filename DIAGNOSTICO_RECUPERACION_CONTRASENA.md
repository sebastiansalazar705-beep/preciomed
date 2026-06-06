# Diagnostico de recuperacion de contrasena

## Problema reportado

Algunos usuarios/clientes olvidaron su clave y no lograron recuperarla por correo electronico.

## Hallazgo principal

El flujo interno de codigos funcionaba, pero la configuracion SMTP de Render no estaba completa. En el panel de Render solo se observaron variables operativas como `PRECIOMED_DB_DIR`, `PRECIOMED_PASSWORD_HASH`, `PRECIOMED_SECRET_KEY` y `SCRAPER_JOB_TOKEN`; no aparecian configuradas las variables necesarias para enviar correo:

- `SMTP_HOST`
- `SMTP_PORT`
- `EMAIL_USER`
- `EMAIL_PASSWORD`
- `EMAIL_FROM`

Sin esas variables, la aplicacion podia crear un codigo de recuperacion en la base, pero no podia enviarlo al correo del usuario.

## Error de experiencia de usuario

Antes de la correccion, si el correo fallaba o SMTP no estaba configurado, la pantalla devolvia el mismo mensaje generico:

```text
Si el correo existe, enviaremos un codigo de seguridad.
```

Eso confundia al usuario, porque parecia que el correo habia sido enviado aunque realmente no salia del servidor.

## Cambios realizados

Archivo modificado:

- `app.py`

Cambios principales:

1. `send_security_code()` ahora soporta:
   - SMTP con STARTTLS para puertos como `587`.
   - SMTP SSL directo para puerto `465`.

2. `/recuperar` ahora muestra mensajes claros:
   - Correo invalido.
   - Usuario no encontrado o inactivo.
   - Error real al enviar correo.
   - Confirmacion solo cuando el correo se envio correctamente.

3. El codigo de recuperacion ya no se imprime en logs de produccion cuando SMTP falla.
   - En local puede imprimirse para pruebas.
   - En Render no se imprime para evitar exponer codigos sensibles.

4. Los errores de envio quedan registrados en `activity_logs` para que el administrador pueda revisarlos en `/usuarios`.

## Flujo esperado despues de la correccion

1. Usuario entra a `/recuperar`.
2. Escribe su correo.
3. Si el correo no existe o el usuario esta inactivo, se muestra:

```text
No encontramos un usuario activo con ese correo.
```

4. Si el correo existe, se genera un codigo de 6 digitos.
5. El codigo se guarda en `password_reset_codes` con fecha de expiracion.
6. La app intenta enviar el correo por SMTP.
7. Si SMTP funciona, se muestra confirmacion.
8. Si SMTP falla, se informa que no se pudo enviar el correo y se registra el error.
9. El codigo solo se marca como usado despues de cambiar la contrasena exitosamente.

## Variables que debes configurar en Render

Para Gmail:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=tu_correo@gmail.com
EMAIL_PASSWORD=tu_contrasena_de_aplicacion
EMAIL_FROM=tu_correo@gmail.com
```

Importante:

- `EMAIL_PASSWORD` no debe ser la contrasena normal de Gmail.
- Debe ser una contrasena de aplicacion generada desde la cuenta de Google.
- No subas estas variables a GitHub.

## Pruebas realizadas

Se verifico por codigo que:

- La aplicacion compila.
- El codigo se genera y se guarda en la base.
- El correo se busca sin problemas de mayusculas/minusculas.
- El codigo se valida antes de cambiar contrasena.
- La contrasena se cambia.
- El codigo se marca como usado solo despues del cambio exitoso.
- El login funciona con la nueva contrasena en la prueba local.

## Pendiente operativo

Configurar SMTP real en Render. Sin esas variables, ningun sistema puede enviar correos reales desde el servidor.
