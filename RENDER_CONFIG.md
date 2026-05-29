# Configuracion segura en Render

## Variables obligatorias

- `PRECIOMED_SECRET_KEY`: secreto de sesion. Debe generarse en Render y no subirse al repositorio.
- `PRECIOMED_USERNAME`: usuario administrador inicial.
- `PRECIOMED_ADMIN_EMAIL`: correo administrador inicial.
- `PRECIOMED_PASSWORD_HASH`: hash bcrypt de la contrasena inicial del administrador.
- `ADMIN_EMAILS`: lista separada por comas de correos con rol administrador.
- `SCRAPER_JOB_TOKEN`: token largo y aleatorio para proteger `/cron/actualizar-precios`.

## Variables recomendadas

- `PRECIOMED_DB_DIR`: directorio donde se guarda `prices.sqlite3`. En local no hace falta configurarla. En Render con disco persistente usa `/var/data`.
- `MAX_USERS`
- `SESSION_HOURS`
- `REMEMBER_SESSION_DAYS`
- `MAX_LOGIN_ATTEMPTS`
- `LOGIN_LOCK_MINUTES`
- `RESET_CODE_MINUTES`
- `RESET_MAX_ATTEMPTS`
- `SMTP_HOST`
- `SMTP_PORT`
- `EMAIL_USER`
- `EMAIL_PASSWORD`
- `EMAIL_FROM`
- `SCRAPER_REQUEST_TIMEOUT`
- `SCRAPER_MAX_WORKERS`

Para crear `PRECIOMED_PASSWORD_HASH`:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'tu-contrasena-segura', bcrypt.gensalt()).decode())"
```

## Persistencia de datos

Render usa filesystem efimero por defecto: los cambios en archivos locales se pierden al reiniciar o redeplegar el servicio. Para conservar usuarios, logs y precios en SQLite, configura una de estas opciones antes de produccion:

- Disco persistente montado sobre `/var/data` en el web service y variable `PRECIOMED_DB_DIR=/var/data`.
- Migracion a una base externa como Render Postgres.

No montes el disco directamente sobre `data/`: esa carpeta tambien contiene los CSV del repositorio (`products.csv`, `product_sources.csv`, `pharmacies.csv`) y un montaje podria ocultarlos. La aplicacion separa los CSV del archivo SQLite mediante `PRECIOMED_DB_DIR`.

No ejecutes `run_scraper.py` desde un Render Cron Job separado si la app sigue usando SQLite local: los cron jobs no pueden acceder al disco persistente del web service. Usa el endpoint protegido del web service o migra a Postgres.

## Actualizacion automatica de precios

La aplicacion expone un endpoint protegido:

`GET /cron/actualizar-precios?token=<SCRAPER_JOB_TOKEN>`

Configura un Render Cron Job para llamar esa URL cada hora. No publiques el token en frontend, logs ni repositorio. Si `SCRAPER_JOB_TOKEN` no existe, el endpoint rechaza la ejecucion.

Para SQLite en Render, usa almacenamiento persistente si quieres conservar precios, usuarios y logs entre despliegues. No borres `data/prices.sqlite3` durante despliegues y crea respaldos antes de cambios de esquema.

## Datos personales

El registro exige autorizacion de tratamiento de datos personales y guarda fecha/hora junto con la version legal `ley-1581-2012-v1`. La politica visible esta en `/tratamiento-datos` e incluye referencia a la Ley 1581 de 2012 de Colombia.
