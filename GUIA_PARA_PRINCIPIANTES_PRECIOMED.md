# Guia para principiantes de Preciomed

Este documento explica que librerias usa el proyecto, para que sirve cada archivo y como ejecutar todo paso a paso.

## 1. Idea general

Preciomed es una aplicacion en Python que revisa enlaces de productos de farmacias, extrae precios, guarda datos en SQLite y muestra una pagina web local para comparar.

## 2. Librerias usadas

| Libreria | Tipo | Para que se usa |
|---|---|---|
| csv | Python estandar | Leer y exportar archivos CSV. |
| sqlite3 | Python estandar | Guardar precios en una base local. |
| http.server | Python estandar | Crear la pagina web local. |
| urllib.request | Python estandar | Descargar HTML o JSON de las paginas. |
| urllib.parse | Python estandar | Analizar URLs y construir consultas. |
| re | Python estandar | Buscar precios y comparar textos. |
| json | Python estandar | Leer respuestas de APIs. |
| gzip / zlib | Python estandar | Descomprimir respuestas web. |
| time | Python estandar | Pausar entre solicitudes. |
| datetime | Python estandar | Guardar fecha y hora de consulta. |
| html | Python estandar | Limpiar textos HTML. |
| collections.defaultdict | Python estandar | Agrupar resultados por producto. |
| beautifulsoup4 | Dependencia instalada | Disponible para mejorar lectura HTML en el futuro. |
| requests | Dependencia instalada | Disponible para hacer peticiones HTTP mas comodas en el futuro. |

## 3. Archivos principales

| Archivo | Funcion |
|---|---|
| app.py | Muestra la interfaz web. |
| config.py | Guarda rutas y configuracion. |
| database.py | Crea tablas, guarda y consulta precios. |
| run_scraper.py | Ejecuta el scraper una vez. |
| export_prices.py | Exporta resultados a CSV. |
| start.py | Actualiza precios e inicia la pagina. Render usa este archivo. |
| scheduler.py | Ejecuta actualizaciones periodicas. |
| scrapers/base.py | Define el modelo de precio scrapeado. |
| scrapers/product_page.py | Lee paginas, precios, descuentos y valida productos. |
| data/products.csv | Lista productos buscados. |
| data/product_sources.csv | Lista enlaces exactos por farmacia. |
| data/prices.sqlite3 | Base de datos local. |

## 4. Como ejecutar en tu computador

```powershell
cd "RUTA_DE_TU_PROYECTO"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_scraper.py
python app.py
```

Despues abre:

```text
http://127.0.0.1:5000
```

## 5. Como ejecutar en Render

En Render usa:

```text
Build Command: pip install -r requirements.txt
Start Command: python start.py
```

## 6. Flujo recomendado

1. Edita `data/product_sources.csv`.
2. Ejecuta `python run_scraper.py`.
3. Ejecuta `python app.py`.
4. Revisa la pagina local.
5. Sube cambios a GitHub.
6. Render publica desde GitHub.

## 7. Validacion de producto

El sistema compara palabras importantes del enlace esperado con el nombre encontrado. Si coincide bien muestra `OK`; si faltan datos muestra `Revisar` o `Diferente`.

## 8. Descuentos

El sistema intenta leer el precio actual y el precio anterior. Si ambos existen, calcula:

```text
descuento = (precio_antes - precio_actual) / precio_antes
```

Si no hay precio anterior claro, muestra `Sin descuento`.

## 9. Comandos utiles

| Comando | Que hace |
|---|---|
| python run_scraper.py | Actualiza precios. |
| python app.py | Prende la pagina local. |
| python export_prices.py | Exporta CSV. |
| python start.py | Actualiza y prende la pagina. |
| git add . | Prepara cambios. |
| git commit -m "mensaje" | Guarda una version. |
| git push | Sube a GitHub. |

## 10. Consejos

- Empieza leyendo `app.py`.
- Luego mira `run_scraper.py`.
- Despues estudia `database.py`.
- Finalmente revisa `scrapers/product_page.py`.
- Haz cambios pequenos y prueba seguido.
