# Comparador de precios de farmacias

Proyecto base en Python para recolectar precios de productos de farmacias, guardarlos en una base de datos y mostrarlos en una pagina web.

## Que hace este proyecto

- Guarda productos, farmacias y precios en una base de datos SQLite.
- Ejecuta un scraper de ejemplo para probar el flujo completo sin depender todavia de paginas reales.
- Permite agregar scrapers reales farmacia por farmacia.
- Muestra una pagina web local con la comparacion de precios.
- Valida si el producto encontrado parece ser el mismo producto del enlace.
- Guarda precio con descuento, precio antes y porcentaje de descuento cuando la pagina lo permite.
- Incluye una ejecucion periodica sencilla para actualizar precios cada cierto tiempo.

## Estructura

```text

├── app.py                  # Pagina web local
├── config.py               # Configuracion general
├── database.py             # Conexion y tablas de la base de datos
├── requirements.txt        # Librerias necesarias
├── run_scraper.py          # Ejecuta el scraper una vez
├── scheduler.py            # Ejecuta el scraper periodicamente
├── data/
│   └── products.csv        # Productos que quieres comparar
│   └── product_sources.csv # URLs reales que se van a consultar
└── scrapers/
    ├── base.py             # Modelo comun para scrapers
    ├── product_page.py     # Scraper de paginas de producto
    ├── farmatodo.py        # Filtro de Farmatodo
    ├── cruz_verde.py       # Filtro de Cruz Verde
    └── colsubsidio.py      # Filtro de Colsubsidio
```

## Primeros pasos

1. Crear un entorno virtual:

```powershell
python -m venv .venv
```

2. Activarlo:

```powershell
.\.venv\Scripts\Activate.ps1
```

3. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

4. Ejecutar el scraper:

```powershell
python run_scraper.py
```

5. Abrir la pagina web:

```powershell
python app.py
```

Luego entra en el navegador a:

```text
http://127.0.0.1:5000
```

## Modelo de ejecucion recomendado

1. Edita `data/product_sources.csv` y revisa que cada fila apunte al producto exacto que quieres comparar.
2. Ejecuta `python run_scraper.py` para visitar cada enlace y guardar la ultima observacion.
3. Abre `python app.py` y entra a `http://127.0.0.1:5000`.
4. Revisa la columna `Validacion`:
   - `OK`: el nombre encontrado coincide con el enlace esperado.
   - `Revisar`: faltan datos para confirmar que sea exactamente igual.
   - `Diferente`: faltan datos clave como dosis, cantidad o tokens del producto.
5. Si una farmacia muestra `Diferente`, cambia esa URL en `data/product_sources.csv` por el enlace correcto.

La interfaz muestra:

- Producto encontrado.
- Precio con descuento detectado.
- Precio antes, si la pagina publica precio tachado o precio de lista.
- Porcentaje de descuento calculado.
- Nota de validacion del producto.

Para que la comparacion sea justa, usa enlaces con la misma dosis y presentacion. Por ejemplo, no mezcles una caja x 30 con un blister x 10.

## Compartir con otras personas

El link `http://127.0.0.1:5000` solo funciona en tu computador. Para que otras personas puedan verlo desde sus casas, revisa la guia:

```text
PUBLICAR.md
```

## Como se adapta a farmacias reales

El archivo `data/product_sources.csv` contiene las paginas reales que el scraper visita. Cada fila tiene:

```csv
pharmacy_name,pharmacy_website,search_name,product_url
```

Si quieres agregar otro producto, primero agregas el producto a `data/products.csv` y luego agregas una URL real de cada farmacia en `data/product_sources.csv`.

Importante: antes de scrapear una pagina real hay que revisar sus terminos de uso y su `robots.txt`. Para un proyecto universitario es mejor hacer pocas solicitudes, con pausas, y guardar la fecha de consulta.

## Farmacias objetivo

Las fuentes iniciales quedan registradas en `data/pharmacies.csv`:

- Farmatodo: `https://www.farmatodo.com.co/`
- Cruz Verde: `https://www.cruzverde.com.co/`
- Redeban: queda en estado `review`, porque no parece ser farmacia sino una empresa de soluciones de pago.

## Siguiente paso recomendado

Escoge 2 o 3 farmacias y 5 productos iniciales. Con eso se puede crear el primer scraper real sin hacer el proyecto demasiado grande desde el comienzo.
