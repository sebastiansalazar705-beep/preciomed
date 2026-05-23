# PrecioMed

PrecioMed es una aplicacion web para comparar precios publicados de medicamentos en Farmatodo, Cruz Verde y Colsubsidio.

La version principal usada para organizar este repositorio fue `upload-preciomed`, porque era la carpeta mas actualizada.

## Funcionalidades

- Login basico de usuario.
- Cookie de sesion firmada con clave secreta.
- Dashboard de medicamentos.
- Filtros por medicamento, farmacia, precio minimo y precio maximo.
- Comparacion por medicamento entre farmacias.
- Validacion de coincidencia del producto encontrado contra la URL esperada.
- Vista imprimible desde el boton `Imprimir vista`.
- Actualizacion manual de precios desde el boton `Actualizar precios`.
- Base de datos SQLite.

## Usuario inicial

Para desarrollo local:

```text
Usuario: admin
Contrasena: preciomed123
```

En Render se recomienda configurar variables de entorno:

```text
PRECIOMED_USERNAME=admin
PRECIOMED_PASSWORD_HASH=<hash sha256 de tu contrasena>
PRECIOMED_SECRET_KEY=<clave larga aleatoria>
```

Si no defines `PRECIOMED_PASSWORD_HASH`, se usa la contrasena inicial de desarrollo.

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

## Nota academica

PrecioMed compara precios publicados por farmacias. No recomienda automedicacion ni reemplaza la orientacion de un profesional de salud.
