# PrecioMed

PrecioMed es una aplicacion web para comparar precios publicados de medicamentos en Farmatodo, Cruz Verde y Colsubsidio.

La version principal usada para organizar este repositorio fue `upload-preciomed`, porque era la carpeta mas actualizada.

## Funcionalidades

- Login con correo y contrasena cifrada con bcrypt.
- Registro de usuarios con nombre completo, correo y confirmacion de contrasena.
- Cookie de sesion firmada con clave secreta.
- Cambio de contrasena desde el perfil.
- Recuperacion de contrasena con codigo temporal por correo.
- Bloqueo basico por intentos fallidos de login.
- Roles de usuario: `admin` y `cliente`.
- Dashboard administrativo separado del dashboard de clientes.
- Autorizacion de tratamiento de datos personales en registro, con referencia a la Ley 1581 de 2012 de Colombia.
- Interfaz moderna con menu lateral, tarjetas, buscador y vista responsive.
- Dashboard de medicamentos.
- Filtros por medicamento, farmacia, precio minimo y precio maximo.
- Comparacion por medicamento entre farmacias.
- Validacion de coincidencia del producto encontrado contra la URL esperada.
- Vista imprimible desde el boton `Imprimir vista`.
- Actualizacion manual de precios desde el boton `Actualizar precios`.
- Endpoint protegido para actualizacion automatica de precios desde Render Cron.
- Base de datos SQLite.

## Usuario inicial

Para desarrollo local:

```text
Correo: admin@preciomed.local
Contrasena: define PRECIOMED_DEV_PASSWORD en tu entorno local.
```

En Render se recomienda configurar variables de entorno:

```text
PRECIOMED_USERNAME=admin
PRECIOMED_ADMIN_EMAIL=admin@preciomed.local
ADMIN_EMAILS=admin@preciomed.local,admin2@preciomed.local,admin3@preciomed.local
PRECIOMED_PASSWORD_HASH=<hash bcrypt de tu contrasena>
PRECIOMED_SECRET_KEY=<clave larga aleatoria>
SCRAPER_JOB_TOKEN=<token largo aleatorio para tareas automaticas>
PRECIOMED_DB_DIR=/var/data  # Solo en Render si configuras disco persistente.
MAX_USERS=100000
SESSION_HOURS=8
REMEMBER_SESSION_DAYS=30
MAX_LOGIN_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15
RESET_CODE_MINUTES=15
RESET_MAX_ATTEMPTS=5
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=tu_correo@gmail.com
EMAIL_PASSWORD=tu_password_de_aplicacion
EMAIL_FROM=tu_correo@gmail.com
```

En Render `PRECIOMED_PASSWORD_HASH` y `PRECIOMED_SECRET_KEY` son obligatorios.
Consulta `RENDER_CONFIG.md` antes de desplegar.
Usa `MAX_USERS=0` si quieres permitir registros ilimitados.

## Seguridad y recuperacion de cuenta

La aplicacion incluye:

- Sesiones firmadas con expiracion.
- Contrasenas cifradas con bcrypt.
- Cambio de contrasena en `/perfil`.
- Recuperacion de contrasena desde `/recuperar`.
- Codigos temporales en la tabla `password_reset_codes`.
- Intentos maximos por codigo con `RESET_MAX_ATTEMPTS`.
- Bloqueo temporal de login con `MAX_LOGIN_ATTEMPTS` y `LOGIN_LOCK_MINUTES`.

## Roles y permisos

PrecioMed separa usuarios en:

- `admin`: acceso completo al panel administrativo.
- `cliente`: acceso al dashboard de medicamentos, perfil y recuperacion de cuenta.

Los clientes no pueden entrar a:

- `/admin`
- `/usuarios`
- `/actualizar`

Los correos administradores se configuran con:

```text
ADMIN_EMAILS=admin@preciomed.local,admin2@preciomed.local,admin3@preciomed.local
```

Si una persona se registra con uno de esos correos, la app le asigna rol `admin`. Los demas usuarios quedan como `cliente`.

Paneles principales:

```text
/          Dashboard de medicamentos
/perfil    Perfil y cambio de contrasena
/admin     Panel administrativo
/usuarios  Usuarios y logs
```

Flujo de recuperacion:

1. El usuario entra a `/recuperar`.
2. Escribe su correo.
3. Si el correo existe, se crea un codigo de 6 digitos.
4. El codigo vence segun `RESET_CODE_MINUTES`.
5. El usuario valida el codigo en `/recuperar/codigo`.
6. Crea una nueva contrasena en `/recuperar/nueva`.
7. El codigo queda marcado como usado y no se puede reutilizar.

Para enviar correos reales configura SMTP en Render. Con Gmail debes crear una `contrasena de aplicacion`, no usar tu contrasena normal.

Si SMTP no esta configurado, la app no se rompe: registra el intento y muestra un error claro al usuario. En desarrollo local puede imprimir el codigo en consola para pruebas, pero en Render no imprime codigos de recuperacion para evitar exponer datos sensibles en logs.

## Instalar dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ejecutar localmente

```powershell
python start.py
```

Luego abre:

```text
http://127.0.0.1:5000
```

Tambien puedes usar Uvicorn directamente:

```powershell
uvicorn app:app --host 0.0.0.0 --port 5000
```

## Actualizar precios

Desde la app, entra con login y usa el boton:

```text
Actualizar precios
```

O desde terminal:

```powershell
python run_scraper.py
```

Para automatizar en Render, configura un Cron Job que llame el endpoint protegido:

```text
/cron/actualizar-precios?token=<SCRAPER_JOB_TOKEN>
```

## Exportar datos a CSV

```powershell
python export_prices.py
```

El archivo queda en:

```text
data/latest_prices.csv
```

## Estructura

```text
.
├── app.py
├── config.py
├── database.py
├── export_prices.py
├── run_scraper.py
├── start.py
├── requirements.txt
├── render.yaml
├── data/
│   ├── products.csv
│   ├── product_sources.csv
│   ├── pharmacies.csv
│   └── prices.sqlite3
└── scrapers/
    ├── base.py
    ├── product_page.py
    ├── farmatodo.py
    ├── cruz_verde.py
    └── colsubsidio.py
```

## Guia para aprender el codigo

La explicacion completa del proyecto, la interfaz, el login, el registro de inicios y el limite de usuarios esta en:

```text
GUIA_BASICA.md
```

## Limpieza realizada

Los archivos duplicados, temporales, logs y versiones antiguas fueron movidos a:

```text
backup_antiguo/
```

No se borro informacion importante sin respaldo.

## Render

En Render usa:

```text
Build Command:
pip install -r requirements.txt

Start Command:
uvicorn app:app --host 0.0.0.0 --port $PORT
```

El archivo `render.yaml` ya incluye esa configuracion.
Antes de redeplegar una instancia con usuarios reales, configura persistencia para
`prices.sqlite3` o migra a una base externa. En local la base queda en
`data/prices.sqlite3`. En Render con disco persistente monta el disco en
`/var/data` y configura `PRECIOMED_DB_DIR=/var/data`. El filesystem por defecto
de Render es efimero y puede perder cambios locales al reiniciar o redeplegar.

## Nota academica

PrecioMed compara precios publicados por farmacias. No recomienda automedicacion ni reemplaza la orientacion de un profesional de salud.
