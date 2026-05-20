import csv

from config import DATA_DIR
from database import fetch_latest_prices, init_db


OUTPUT_FILE = DATA_DIR / "latest_prices.csv"


def export_latest_prices():
    init_db()
    rows = fetch_latest_prices()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "producto_buscado",
                "producto_encontrado",
                "farmacia",
                "precio_descuento_cop",
                "precio_antes_cop",
                "descuento_porcentaje",
                "validacion_producto",
                "puntaje_coincidencia",
                "notas_validacion",
                "fecha_consulta",
                "url_producto",
            ]
        )

        for row in rows:
            writer.writerow(
                [
                    row["search_name"],
                    row["product_name"],
                    row["pharmacy_name"],
                    row["price_cop"],
                    row["list_price_cop"],
                    row["discount_percent"],
                    row["product_match_status"],
                    row["product_match_score"],
                    row["match_notes"],
                    row["observed_at"],
                    row["product_url"],
                ]
            )

    print(f"Archivo creado: {OUTPUT_FILE}")
    print(f"Total de registros exportados: {len(rows)}")


if __name__ == "__main__":
    export_latest_prices()
