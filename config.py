from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "prices.sqlite3"
PRODUCTS_CSV = DATA_DIR / "products.csv"
PRODUCT_SOURCES_CSV = DATA_DIR / "product_sources.csv"
PHARMACIES_CSV = DATA_DIR / "pharmacies.csv"

# Tiempo de espera entre actualizaciones cuando se usa scheduler.py.
SCRAPER_INTERVAL_MINUTES = 60

# Identifica tu proyecto con educacion y respeto al sitio consultado.
USER_AGENT = "University price comparison project contact: student@example.com"

# Maximo de usuarios que se pueden registrar en la plataforma.
# Usa 0 para permitir registros ilimitados. En Render se cambia con MAX_USERS.
MAX_USERS = int(os.environ.get("MAX_USERS", "100000"))
