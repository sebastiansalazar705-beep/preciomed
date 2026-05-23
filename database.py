import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from config import DATA_DIR, DB_PATH


@contextmanager
def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pharmacies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                website TEXT
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_name TEXT NOT NULL UNIQUE,
                category TEXT
            );

            CREATE TABLE IF NOT EXISTS price_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pharmacy_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                price_cop INTEGER NOT NULL,
                list_price_cop INTEGER,
                discount_percent REAL,
                product_match_status TEXT DEFAULT 'review',
                product_match_score INTEGER DEFAULT 0,
                match_notes TEXT DEFAULT '',
                product_url TEXT,
                observed_at TEXT NOT NULL,
                FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT,
                email TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'cliente',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS app_start_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                username TEXT,
                ip_identifier TEXT,
                status TEXT NOT NULL,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                username TEXT,
                email TEXT,
                ip_identifier TEXT,
                status TEXT NOT NULL,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                security_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                used_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                ip_address TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            """
        )
        ensure_price_observation_columns(connection)
        ensure_user_columns(connection)
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reset_codes_email ON password_reset_codes(email)"
        )


def ensure_price_observation_columns(connection):
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(price_observations)").fetchall()
    }
    migrations = {
        "list_price_cop": "ALTER TABLE price_observations ADD COLUMN list_price_cop INTEGER",
        "discount_percent": "ALTER TABLE price_observations ADD COLUMN discount_percent REAL",
        "product_match_status": (
            "ALTER TABLE price_observations "
            "ADD COLUMN product_match_status TEXT DEFAULT 'review'"
        ),
        "product_match_score": (
            "ALTER TABLE price_observations "
            "ADD COLUMN product_match_score INTEGER DEFAULT 0"
        ),
        "match_notes": "ALTER TABLE price_observations ADD COLUMN match_notes TEXT DEFAULT ''",
    }
    for column_name, sql in migrations.items():
        if column_name not in existing_columns:
            connection.execute(sql)


def ensure_user_columns(connection):
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    migrations = {
        "full_name": "ALTER TABLE users ADD COLUMN full_name TEXT",
        "email": "ALTER TABLE users ADD COLUMN email TEXT",
        "role": "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'cliente'",
        "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at TEXT",
    }
    for column_name, sql in migrations.items():
        if column_name not in existing_columns:
            connection.execute(sql)

    connection.execute(
        """
        UPDATE users
        SET email = username
        WHERE email IS NULL OR email = ''
        """
    )
    connection.execute(
        """
        UPDATE users
        SET full_name = username
        WHERE full_name IS NULL OR full_name = ''
        """
    )


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def utc_now_datetime():
    return datetime.now(timezone.utc)


def ensure_default_user(username, email, full_name, password_hash, role="admin"):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (username, email),
        ).fetchone()
        if row:
            connection.execute(
                """
                UPDATE users
                SET username = ?, email = ?, full_name = ?, role = ?
                WHERE id = ?
                """,
                (username, email, full_name, role, row["id"]),
            )
            return row["id"]

        connection.execute(
            """
            INSERT INTO users (username, full_name, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, full_name, email, password_hash, role, utc_now()),
        )
        return connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()["id"]


def count_users():
    with get_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) AS total FROM users WHERE is_active = 1"
        ).fetchone()["total"]


def fetch_users():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, username, full_name, email, role, is_active, created_at, last_login_at
            FROM users
            ORDER BY created_at ASC
            """
        ).fetchall()


def get_user_by_username(username):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, username, full_name, email, password_hash, role, is_active, created_at, last_login_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()


def get_user_by_email(email):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, username, full_name, email, password_hash, role, is_active, created_at, last_login_at
            FROM users
            WHERE lower(email) = lower(?)
            """,
            (email,),
        ).fetchone()


def create_user(username, full_name, email, password_hash, role="cliente"):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (username, full_name, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, full_name, email, password_hash, role, utc_now()),
        )
        return connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()["id"]


def update_user_password(user_id, password_hash):
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )


def update_last_login(user_id):
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (utc_now(), user_id),
        )


def log_app_start(username=None, ip_identifier=None, status="exitoso", error_message=None):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_start_logs (
                started_at,
                username,
                ip_identifier,
                status,
                error_message
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (utc_now(), username, ip_identifier, status, error_message),
        )


def log_activity(
    event_type,
    username=None,
    email=None,
    ip_identifier=None,
    status="exitoso",
    message=None,
):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO activity_logs (
                created_at,
                event_type,
                username,
                email,
                ip_identifier,
                status,
                message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (utc_now(), event_type, username, email, ip_identifier, status, message),
        )


def fetch_activity_logs(limit=50):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, created_at, event_type, username, email, ip_identifier, status, message
            FROM activity_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def fetch_activity_logs_by_email(email, limit=20):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, created_at, event_type, username, email, ip_identifier, status, message
            FROM activity_logs
            WHERE lower(email) = lower(?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (email, limit),
        ).fetchall()


def count_failed_logins(email, ip_identifier=None, minutes=15):
    since = (utc_now_datetime() - timedelta(minutes=minutes)).isoformat()
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM activity_logs
            WHERE event_type = 'login'
              AND status = 'error'
              AND created_at >= ?
              AND lower(email) = lower(?)
              AND (? IS NULL OR ip_identifier = ?)
            """,
            (since, email, ip_identifier, ip_identifier),
        ).fetchone()["total"]


def create_password_reset_code(user_id, email, security_code, expires_at, ip_address=None):
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE password_reset_codes
            SET used = 1, used_at = ?
            WHERE user_id = ? AND used = 0
            """,
            (utc_now(), user_id),
        )


def update_user_role(user_id, role):
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, user_id),
        )
        connection.execute(
            """
            INSERT INTO password_reset_codes (
                user_id,
                email,
                security_code,
                created_at,
                expires_at,
                used,
                attempts,
                ip_address
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (user_id, email, security_code, utc_now(), expires_at, ip_address),
        )


def get_password_reset_code(email, security_code):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, user_id, email, security_code, created_at, expires_at, used, attempts, ip_address
            FROM password_reset_codes
            WHERE lower(email) = lower(?) AND security_code = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (email, security_code),
        ).fetchone()


def get_latest_password_reset_code_by_email(email):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, user_id, email, security_code, created_at, expires_at, used, attempts, ip_address
            FROM password_reset_codes
            WHERE lower(email) = lower(?) AND used = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,),
        ).fetchone()


def increment_password_reset_attempt(code_id):
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE password_reset_codes
            SET attempts = attempts + 1
            WHERE id = ?
            """,
            (code_id,),
        )


def mark_password_reset_code_used(code_id):
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE password_reset_codes
            SET used = 1, used_at = ?
            WHERE id = ?
            """,
            (utc_now(), code_id),
        )


def fetch_app_start_logs(limit=30):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, started_at, username, ip_identifier, status, error_message
            FROM app_start_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def upsert_pharmacy(name, website=None):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pharmacies (name, website)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET website = excluded.website
            """,
            (name, website),
        )
        row = connection.execute(
            "SELECT id FROM pharmacies WHERE name = ?",
            (name,),
        ).fetchone()
        return row["id"]


def upsert_product(search_name, category=None):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO products (search_name, category)
            VALUES (?, ?)
            ON CONFLICT(search_name) DO UPDATE SET category = excluded.category
            """,
            (search_name, category),
        )
        row = connection.execute(
            "SELECT id FROM products WHERE search_name = ?",
            (search_name,),
        ).fetchone()
        return row["id"]


def save_price_observation(
    pharmacy_id,
    product_id,
    product_name,
    price_cop,
    product_url,
    list_price_cop=None,
    discount_percent=None,
    product_match_status="review",
    product_match_score=0,
    match_notes="",
):
    observed_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO price_observations (
                pharmacy_id,
                product_id,
                product_name,
                price_cop,
                list_price_cop,
                discount_percent,
                product_match_status,
                product_match_score,
                match_notes,
                product_url,
                observed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pharmacy_id,
                product_id,
                product_name,
                price_cop,
                list_price_cop,
                discount_percent,
                product_match_status,
                product_match_score,
                match_notes,
                product_url,
                observed_at,
            ),
        )


def fetch_latest_prices():
    with get_connection() as connection:
        return connection.execute(
            """
            WITH latest AS (
                SELECT
                    product_id,
                    pharmacy_id,
                    MAX(id) AS latest_observation_id
                FROM price_observations
                GROUP BY product_id, pharmacy_id
            )
            SELECT
                p.search_name,
                po.product_name,
                ph.name AS pharmacy_name,
                ph.website,
                po.price_cop,
                po.list_price_cop,
                po.discount_percent,
                po.product_match_status,
                po.product_match_score,
                po.match_notes,
                po.product_url,
                po.observed_at
            FROM latest l
            JOIN price_observations po
                ON po.id = l.latest_observation_id
            JOIN products p ON p.id = po.product_id
            JOIN pharmacies ph ON ph.id = po.pharmacy_id
            ORDER BY p.search_name, po.price_cop ASC
            """
        ).fetchall()
