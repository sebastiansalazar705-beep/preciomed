# Documentacion de cambios: persistencia de base de datos en PrecioMed

## 1. Problema encontrado

PrecioMed guarda usuarios, precios, logs, consentimientos y ejecuciones del scraper en una base SQLite llamada `prices.sqlite3`.

Antes de este cambio, la ruta estaba fija asi:

```python
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "prices.sqlite3"
```

Esto funciona bien en desarrollo local, pero en Render puede ser riesgoso porque el filesystem normal del servicio web puede ser efimero. Eso significa que archivos creados o modificados por la aplicacion pueden perderse en reinicios, redeploys o recreaciones del servicio.

Riesgo principal:

- Usuarios registrados podrian desaparecer si solo viven en la SQLite del filesystem efimero.
- Precios y logs del scraper podrian volver a un estado anterior.
- Consentimientos de tratamiento de datos podrian perderse.

## 2. Estado actual revisado

Archivos revisados:

- `config.py`
- `database.py`
- `app.py`
- `render.yaml`
- `README.md`
- `RENDER_CONFIG.md`
- `data/products.csv`
- `data/product_sources.csv`
- `data/pharmacies.csv`

Hallazgos:

- El proyecto usa Python con FastAPI/Uvicorn.
- La base actual es SQLite.
- La ruta local historica es `data/prices.sqlite3`.
- `render.yaml` esta configurado como servicio web en Render con `plan: free`.
- El panel de Render indica que los discos persistentes no estan disponibles en servicios Free.
- Las variables sensibles se manejan por variables de entorno y no deben escribirse en GitHub.

## 3. Solucion aplicada

Se preparo la aplicacion para que la base SQLite pueda vivir en un directorio configurable con la variable:

```text
PRECIOMED_DB_DIR
```

En desarrollo local no hace falta configurar nada. La app sigue usando:

```text
data/prices.sqlite3
```

En Render, cuando se active un disco persistente, se recomienda montar el disco en:

```text
/var/data
```

Y configurar:

```text
PRECIOMED_DB_DIR=/var/data
```

Con esto, la base quedara en:

```text
/var/data/prices.sqlite3
```

## 4. Por que no se monto el disco directamente sobre `data/`

La carpeta `data/` tambien contiene archivos CSV importantes del repositorio:

- `products.csv`
- `product_sources.csv`
- `pharmacies.csv`

Si se monta un disco persistente encima de `data/`, el disco puede ocultar esos CSV del repositorio. Por eso se separaron dos conceptos:

- `DATA_DIR`: carpeta de archivos semilla del proyecto.
- `DB_DIR`: carpeta donde vive la base SQLite.

Esta separacion permite que los CSV sigan saliendo del codigo versionado y que la base viva en un volumen persistente.

## 5. Archivos modificados

### `config.py`

Antes:

```python
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "prices.sqlite3"
```

Ahora:

```python
DATA_DIR = BASE_DIR / "data"
DB_DIR = Path(os.environ.get("PRECIOMED_DB_DIR", DATA_DIR)).expanduser()
DB_PATH = DB_DIR / "prices.sqlite3"
```

Para que sirve:

- Si `PRECIOMED_DB_DIR` no existe, usa `data/` como antes.
- Si `PRECIOMED_DB_DIR=/var/data`, guarda la base en `/var/data/prices.sqlite3`.
- No cambia la ubicacion de los CSV.

### `database.py`

Antes:

```python
from config import DATA_DIR, DB_PATH

DATA_DIR.mkdir(parents=True, exist_ok=True)
connection = sqlite3.connect(DB_PATH)
```

Ahora:

```python
from config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
connection = sqlite3.connect(DB_PATH)
```

Para que sirve:

- Crea la carpeta real donde vivira la base.
- Funciona tanto con `data/` como con `/var/data`.
- Evita depender de que la base siempre este dentro de `data/`.

### `RENDER_CONFIG.md`

Se agrego la variable:

```text
PRECIOMED_DB_DIR=/var/data
```

Tambien se documento que no debe montarse el disco sobre `data/`.

### `README.md`

Se agrego una nota de configuracion para Render:

```text
PRECIOMED_DB_DIR=/var/data
```

Y se explico que localmente la base sigue en `data/prices.sqlite3`.

## 6. Como funciona la conexion a la base

La aplicacion lee `DB_PATH` desde `config.py`.

Flujo:

1. `config.py` define `DB_DIR`.
2. Si existe `PRECIOMED_DB_DIR`, usa ese directorio.
3. Si no existe, usa `data/`.
4. `database.py` crea la carpeta si falta.
5. SQLite abre `prices.sqlite3` dentro de esa carpeta.

Ejemplo local:

```text
PRECIOMED_DB_DIR no configurada
DB_PATH = data/prices.sqlite3
```

Ejemplo Render con disco:

```text
PRECIOMED_DB_DIR=/var/data
DB_PATH = /var/data/prices.sqlite3
```

## 7. Configuracion local

No necesitas cambiar nada para desarrollo local.

Instalar dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Ejecutar:

```powershell
python start.py
```

Abrir:

```text
http://127.0.0.1:5000
```

La base local queda en:

```text
data/prices.sqlite3
```

## 8. Configuracion recomendada en Render con disco persistente

Render mostro que los discos persistentes no estan disponibles para servicios Free. Para usar disco persistente hay que mover el servicio a un plan que soporte Disk.

Pasos recomendados:

1. Entrar al servicio `preciomed` en Render.
2. Cambiar el plan del servicio web a uno que soporte Persistent Disks.
3. Crear un Disk para el servicio web.
4. Montar el Disk en:

```text
/var/data
```

5. Agregar variable de entorno:

```text
PRECIOMED_DB_DIR=/var/data
```

6. Verificar que las variables sensibles sigan configuradas:

```text
PRECIOMED_PASSWORD_HASH
PRECIOMED_SECRET_KEY
SCRAPER_JOB_TOKEN
ADMIN_EMAILS
MAX_USERS
SMTP_HOST
SMTP_PORT
EMAIL_USER
EMAIL_PASSWORD
EMAIL_FROM
```

7. Hacer redeploy.
8. Probar login, registro, roles, precios y scraper.

## 9. Respaldo antes de mover datos

Antes de cambiar la ruta de la base en produccion, crea un respaldo.

En local:

```powershell
Copy-Item data\prices.sqlite3 data\prices.backup.sqlite3
```

En Render, si el servicio permite shell o SSH:

```bash
cp /opt/render/project/src/data/prices.sqlite3 /var/data/prices.backup.sqlite3
```

Despues copia la base actual al disco persistente:

```bash
cp /opt/render/project/src/data/prices.sqlite3 /var/data/prices.sqlite3
```

Importante:

- No subas `prices.sqlite3` a GitHub.
- No subas backups de la base a GitHub.
- No imprimas usuarios, hashes o tokens en logs publicos.

## 10. Alternativa futura: Render Postgres

Postgres es una opcion mas robusta para produccion porque no depende de archivos locales y maneja mejor concurrencia, respaldos y escalabilidad.

Pero migrar a Postgres requiere mas cambios que montar un disco:

- Cambiar consultas SQLite a SQL compatible con Postgres.
- Cambiar placeholders `?` por placeholders del driver Postgres.
- Reemplazar `sqlite3.Row`.
- Ajustar `AUTOINCREMENT`, `PRAGMA table_info`, `lastrowid` y `ON CONFLICT`.
- Crear migracion de datos desde SQLite hacia Postgres.
- Validar usuarios, roles, consentimientos, precios, logs y scraper despues de importar.

Por seguridad, para este estado del proyecto se eligio preparar SQLite para disco persistente. Es el cambio de menor riesgo porque conserva el modelo actual y no transforma datos.

## 11. Como probar que todo funciona

Pruebas basicas locales:

```powershell
python -m compileall app.py config.py database.py scrapers
python -c "from database import init_db; init_db(); print('DB OK')"
```

Probar con una ruta temporal, sin tocar `data/prices.sqlite3`:

```powershell
$env:PRECIOMED_DB_DIR="$pwd\tmp-db-test"
python -c "from config import DB_PATH; from database import init_db; init_db(); print(DB_PATH)"
Remove-Item Env:\PRECIOMED_DB_DIR
```

Pruebas funcionales:

- Entrar a `/login`.
- Registrar un usuario cliente.
- Confirmar que el usuario acepta tratamiento de datos.
- Entrar como cliente y confirmar que no ve rutas administrativas.
- Entrar como admin y confirmar que ve usuarios, logs y scraping.
- Ejecutar el scraper manual desde admin o por endpoint protegido.
- Buscar Electrolit y confirmar que no se mezcla con Enterolyte.

## 12. Errores posibles y solucion

### Error: la app no encuentra la base

Revisar:

```text
PRECIOMED_DB_DIR
```

Debe apuntar a un directorio existente o que la app pueda crear.

### Error: permisos al crear `prices.sqlite3`

Solucion:

- Verificar que el mount path del disco sea escribible.
- En Render, usar `/var/data`.

### Error: los productos CSV no cargan

Causa posible:

- Se monto el disco sobre `data/` y se ocultaron los CSV.

Solucion:

- Montar el disco en `/var/data`.
- Dejar `data/` solo para CSV versionados.

### Error: datos antiguos no aparecen despues del cambio

Causa posible:

- Se creo una SQLite nueva vacia en `/var/data`.

Solucion:

- Restaurar desde el respaldo.
- Copiar la SQLite anterior al disco persistente antes de activar la variable.

## 13. Recomendaciones futuras

- Activar disco persistente en Render si se mantiene SQLite.
- Crear respaldos periodicos de `prices.sqlite3`.
- Migrar a Render Postgres cuando la aplicacion necesite mas estabilidad y concurrencia.
- Agregar una migracion formal SQLite -> Postgres antes de cambiar produccion.
- Mantener `DATABASE_URL` y credenciales solo en variables de entorno.
- No subir bases SQLite, respaldos ni datos sensibles al repositorio.
- Revisar logs despues de cada deploy.
- Probar login, registro, roles y scraper despues de cada cambio de infraestructura.
