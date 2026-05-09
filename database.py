import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

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
                product_url TEXT,
                observed_at TEXT NOT NULL,
                FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            """
        )


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


def save_price_observation(pharmacy_id, product_id, product_name, price_cop, product_url):
    observed_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO price_observations (
                pharmacy_id,
                product_id,
                product_name,
                price_cop,
                product_url,
                observed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pharmacy_id, product_id, product_name, price_cop, product_url, observed_at),
        )


def fetch_latest_prices():
    with get_connection() as connection:
        return connection.execute(
            """
            WITH latest AS (
                SELECT
                    product_id,
                    pharmacy_id,
                    MAX(observed_at) AS latest_observed_at
                FROM price_observations
                GROUP BY product_id, pharmacy_id
            )
            SELECT
                p.search_name,
                po.product_name,
                ph.name AS pharmacy_name,
                ph.website,
                po.price_cop,
                po.product_url,
                po.observed_at
            FROM latest l
            JOIN price_observations po
                ON po.product_id = l.product_id
                AND po.pharmacy_id = l.pharmacy_id
                AND po.observed_at = l.latest_observed_at
            JOIN products p ON p.id = po.product_id
            JOIN pharmacies ph ON ph.id = po.pharmacy_id
            ORDER BY p.search_name, po.price_cop ASC
            """
        ).fetchall()
