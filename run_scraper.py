import csv

from config import PRODUCTS_CSV
from database import (
    init_db,
    save_price_observation,
    upsert_pharmacy,
    upsert_product,
)
from scrapers import product_page


def load_products():
    with PRODUCTS_CSV.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def run():
    init_db()
    products = load_products()
    scraped_prices = product_page.scrape(products)

    for item in scraped_prices:
        pharmacy_id = upsert_pharmacy(item.pharmacy_name, item.pharmacy_website)
        product_id = upsert_product(item.search_name)
        save_price_observation(
            pharmacy_id=pharmacy_id,
            product_id=product_id,
            product_name=item.product_name,
            price_cop=item.price_cop,
            product_url=item.product_url,
        )

    print(f"Listo. Se guardaron {len(scraped_prices)} precios reales en la base de datos.")


if __name__ == "__main__":
    run()
