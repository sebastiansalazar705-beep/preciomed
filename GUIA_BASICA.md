# Guia basica de PrecioMed

Esta guia explica como funciona PrecioMed y donde debes tocar el codigo cuando quieras aprender, corregir o cambiar la interfaz.

## Que hace la plataforma

PrecioMed compara precios publicados de medicamentos en varias farmacias.

El flujo principal es:

```text
Fuentes de farmacias
        |
Scraper en Python
        |
Base de datos SQLite
        |
Backend FastAPI
        |
Interfaz web en HTML/CSS
```

La app permite:

- Iniciar sesion.
- Registrar usuarios hasta un limite maximo.
- Ver medicamentos por farmacia.
- Comparar precios cuando el mismo medicamento existe en varias farmacias.
- Filtrar por medicamento, farmacia y precio.
- Imprimir la vista principal.
- Actualizar precios.
- Registrar inicios de aplicacion e intentos de login.

## Mapa de carpetas

```text
.
├── app.py
├── config.py
├── database.py
├── run_scraper.py
├── export_prices.py
├── start.py
├── requirements.txt
├── render.yaml
├── Procfile
├── data/
│   ├── products.csv
│   ├── product_sources.csv
│   ├── pharmacies.csv
│   ├── prices.sqlite3
│   └── latest_prices.csv
├── scrapers/
│   ├── base.py
│   ├── product_page.py
│   ├── farmatodo.py
│   ├── cruz_verde.py
│   └── colsubsidio.py
└── backup_antiguo/
    └── raiz_anterior/
```

La carpeta `upload-preciomed` fue usada como base principal porque era la version mas actualizada. La version antigua se movio a `backup_antiguo/raiz_anterior`.

## Archivos importantes

`app.py`

Es el archivo principal de la plataforma web. Contiene:

- Rutas de FastAPI.
- Login.
- Registro de usuarios.
- Dashboard.
- Filtros.
- Vista de usuarios.
- HTML y CSS de la interfaz.

`start.py`

Archivo sencillo para iniciar la aplicacion localmente.

```powershell
python start.py
```

`database.py`

Maneja la base de datos SQLite. Crea tablas y contiene funciones para:

- Farmacias.
- Productos.
- Observaciones de precios.
- Usuarios.
- Registros de actividad en `activity_logs`.

`config.py`

Contiene configuracion general:

- Ubicacion de archivos.
- Ruta de la base de datos.
- Intervalo del scraper.
- `MAX_USERS`, el maximo de usuarios permitidos.

`run_scraper.py`

Ejecuta el scraper y guarda precios en la base de datos.

`scrapers/product_page.py`

Es el scraper principal. Lee URLs de productos, extrae precios y valida si el producto encontrado coincide con el esperado.

`data/products.csv`

Lista de medicamentos buscados.

`data/product_sources.csv`

Lista de URLs exactas por farmacia y medicamento.

`data/prices.sqlite3`

Base de datos SQLite donde se guardan precios, usuarios y logs.

`data/latest_prices.csv`

Archivo exportado para abrir los datos en Excel.

## Como ejecutar la app

1. Abre PowerShell en la carpeta del proyecto:

```powershell
cd "C:\Users\USER\Documents\Codex\2026-04-29\preciomed-github"
```

2. Crea entorno virtual:

```powershell
python -m venv .venv
```

3. Activalo:

```powershell
.\.venv\Scripts\Activate.ps1
```

4. Instala dependencias:

```powershell
pip install -r requirements.txt
```

5. Ejecuta:

```powershell
python start.py
```

6. Abre:

```text
http://127.0.0.1:5000
```

Correo inicial:

```text
admin@preciomed.local
```

Contrasena inicial:

```text
preciomed123
```

## Como se conecta frontend y backend

Este proyecto no usa React separado. La interfaz se genera dentro de `app.py`.

FastAPI recibe una solicitud, consulta datos en SQLite usando `database.py`, arma HTML y devuelve la pagina al navegador.

Ejemplo:

```text
Navegador entra a /
        |
FastAPI ejecuta home()
        |
home() llama fetch_latest_prices()
        |
database.py consulta SQLite
        |
app.py arma tablas HTML
        |
El navegador muestra el dashboard
```

## Como se guardan los datos

La base de datos esta en:

```text
data/prices.sqlite3
```

Tablas principales:

`pharmacies`

Guarda farmacias.

`products`

Guarda medicamentos buscados.

`price_observations`

Guarda cada precio encontrado, con:

- Medicamento.
- Farmacia.
- Precio.
- Precio anterior.
- Descuento.
- URL.
- Fecha de consulta.
- Validacion del producto.

`users`

Guarda usuarios registrados.

`activity_logs`

Guarda actividad importante: inicio de aplicacion, login exitoso, login fallido y registro de usuarios.

## Como funciona el login

El login esta en `app.py`.

Rutas importantes:

```text
GET  /login
POST /login
GET  /logout
GET  /registro
POST /registro
```

El registro solicita:

- Nombre completo.
- Correo electronico.
- Contrasena.
- Confirmacion de contrasena.

La app valida:

- Que el correo tenga formato valido.
- Que el correo no este repetido.
- Que la contrasena y su confirmacion coincidan.
- Que la contrasena tenga minimo 8 caracteres, una mayuscula, una minuscula y un numero.
- Que no se supere `MAX_USERS`.

Cuando un usuario inicia sesion:

1. El usuario escribe correo y contrasena.
2. Se busca el correo en la tabla `users`.
3. Se valida que el usuario este activo.
4. Se compara la contrasena usando bcrypt.
5. Si es correcta, se crea una cookie firmada.
6. Esa cookie permite entrar al dashboard.

La cookie se llama:

```text
preciomed_session
```

## Seguridad basica

La seguridad actual es basica y suficiente para un prototipo universitario:

- Las contrasenas no se guardan en texto plano.
- Se guardan como hash bcrypt.
- La sesion usa una cookie firmada con `PRECIOMED_SECRET_KEY`.
- Las rutas principales piden login.
- El scraper no permite editar datos desde la web, solo actualizar precios.

Para produccion real se recomienda:

- Usar claves fuertes en Render.
- Usar HTTPS.
- Definir una clave secreta fuerte en Render.
- Separar roles de usuario.

## Registro de inicios

El registro de actividad se guarda en la tabla:

```text
activity_logs
```

Guarda:

- Fecha y hora.
- Usuario, si aplica.
- IP o identificador del equipo.
- Estado: `exitoso` o `error`.
- Mensaje.

Se registra:

- Cuando la aplicacion inicia.
- Cuando un login es exitoso.
- Cuando un login falla.
- Cuando se registra un usuario.

Puedes verlo desde:

```text
/usuarios
```

Despues de iniciar sesion.

## Limite maximo de usuarios

El limite esta en `config.py`:

```python
MAX_USERS = int(os.environ.get("MAX_USERS", "100000"))
```

Por defecto permite 100000 usuarios, que para este proyecto funciona como un limite practicamente ilimitado.
Si quieres que sea ilimitado de verdad, usa:

```text
MAX_USERS=0
```

Si se intenta registrar un usuario cuando ya se alcanzo el limite, la app muestra:

```text
Se alcanzó el número máximo de usuarios permitidos.
```

Para cambiar el limite localmente, modifica `config.py`.

Para cambiarlo en Render, crea o modifica la variable:

```text
MAX_USERS
```

Ejemplos:

```text
MAX_USERS=5
MAX_USERS=10
MAX_USERS=20
MAX_USERS=0
```

Para saber cuantos usuarios hay, entra a:

```text
/usuarios
```

Tambien puedes consultar SQLite con DB Browser for SQLite mirando la tabla `users`.

## Como modificar la interfaz

La interfaz esta principalmente en:

```text
app.py
```

Dentro de `app.py`, busca la funcion:

```python
def layout(...)
```

Ahi esta el HTML general y el CSS.

### Cambiar colores

Busca en `layout()`:

```css
:root {
    --bg: #f4f7fb;
    --surface: #ffffff;
    --brand: #0f766e;
    --brand-dark: #115e59;
}
```

Ejemplo, para cambiar el color principal:

```css
--brand: #2563eb;
--brand-dark: #1d4ed8;
```

### Cambiar botones

Busca:

```css
button, .button {
    background: var(--brand);
}
```

Tambien puedes cambiar los textos de botones en las rutas:

```python
<button type="submit">Filtrar</button>
<a class="button" href="/actualizar">Actualizar precios</a>
<button onclick="window.print()">Imprimir vista</button>
```

### Cambiar textos

Busca los textos directamente en `app.py`.

Ejemplo:

```python
<h1>Dashboard de medicamentos</h1>
```

Puedes cambiarlo por:

```python
<h1>Panel principal PrecioMed</h1>
```

### Cambiar tablas

Las tablas principales estan dentro de la funcion:

```python
def home(...)
```

Busca:

```html
<table>
```

Ahi puedes agregar o quitar columnas.

Si agregas una columna en `<thead>`, tambien debes agregar el dato correspondiente en cada `<tr>`.

### Cambiar tarjetas

Las tarjetas de resumen estan en:

```python
summary = f"""
```

Ejemplo:

```html
<div class="panel">Medicamentos<strong>{len(comparisons)}</strong></div>
```

Puedes agregar una nueva tarjeta copiando esa linea.

### Cambiar formularios

El formulario de filtros esta en:

```python
filters = f"""
```

El formulario de login esta en:

```python
def login_form(...)
```

El formulario de registro esta en:

```python
def register_form(...)
```

### Agregar una nueva seccion visual

Dentro de `home()`, busca:

```python
body = f"""
```

Puedes agregar una seccion antes o despues de `{summary}`.

Ejemplo:

```html
<section class="panel">
    <h2>Nota importante</h2>
    <p>Los precios pueden cambiar segun disponibilidad.</p>
</section>
```

### Modificar pantalla de login

Busca:

```python
def login_form(...)
```

Ahi puedes cambiar:

- Titulo.
- Texto de ayuda.
- Inputs.
- Boton.
- Enlace a registro.

### Modificar pantalla principal

Busca:

```python
def home(...)
```

Ahi esta:

- Titulo del dashboard.
- Boton de actualizar.
- Boton imprimir.
- Filtros.
- Tarjetas.
- Tablas por medicamento.

## Errores que debes evitar

- No editar archivos `.pyc`.
- No modificar `data/prices.sqlite3` como texto.
- No borrar `data/product_sources.csv`, porque ahi estan las fuentes del scraper.
- No cambiar nombres de columnas de la base sin actualizar `database.py`.
- Si agregas una columna visual en una tabla, actualiza encabezado y fila.
- No pongas contrasenas reales directamente en el codigo para produccion.
- No elimines `backup_antiguo` si todavia quieres conservar respaldo.

## Render

Comando recomendado:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

El archivo `render.yaml` ya incluye:

```text
MAX_USERS=100000
```

## Recomendaciones para seguir aprendiendo

1. Aprende HTML basico para entender etiquetas como `section`, `table`, `form`.
2. Aprende CSS basico para colores, espacios, bordes y responsive.
3. Aprende SQL basico para consultar tablas.
4. Aprende FastAPI para entender rutas como `@app.get("/")`.
5. Aprende seguridad de contrasenas con bcrypt cuando quieras mejorar el login.

PrecioMed ya funciona como prototipo. El siguiente paso profesional seria separar plantillas HTML en archivos aparte y usar una base de datos como PostgreSQL.
