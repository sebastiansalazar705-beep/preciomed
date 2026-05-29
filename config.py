from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_DIR = Path(os.environ.get("PRECIOMED_DB_DIR", DATA_DIR)).expanduser()
DB_PATH = DB_DIR / "prices.sqlite3"
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

# Correos con permiso administrativo. Cambialos en Render con ADMIN_EMAILS.
ADMIN_EMAILS = [
    item.strip().lower()
    for item in os.environ.get(
        "ADMIN_EMAILS",
        "admin@preciomed.local,admin2@preciomed.local,admin3@preciomed.local",
    ).split(",")
    if item.strip()
]

# Seguridad de sesiones, login y recuperacion de contrasena.
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "8"))
REMEMBER_SESSION_DAYS = int(os.environ.get("REMEMBER_SESSION_DAYS", "30"))
MAX_LOGIN_ATTEMPTS = int(os.environ.get("MAX_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.environ.get("LOGIN_LOCK_MINUTES", "15"))
RESET_CODE_MINUTES = int(os.environ.get("RESET_CODE_MINUTES", "15"))
RESET_MAX_ATTEMPTS = int(os.environ.get("RESET_MAX_ATTEMPTS", "5"))

# Token compartido para tareas automaticas externas, por ejemplo Render Cron.
# Si no se configura, los endpoints programados quedan deshabilitados.
SCRAPER_JOB_TOKEN = os.environ.get("SCRAPER_JOB_TOKEN", "")
SCRAPER_REQUEST_TIMEOUT = int(os.environ.get("SCRAPER_REQUEST_TIMEOUT", "18"))
SCRAPER_MAX_WORKERS = int(os.environ.get("SCRAPER_MAX_WORKERS", "4"))

# Configuracion de correo SMTP para recuperar contrasena.
# En Render se recomienda guardar estos datos como variables de entorno.
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_FROM = os.environ.get("EMAIL_FROM", EMAIL_USER)
