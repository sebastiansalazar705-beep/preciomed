import csv

from config import PRODUCTS_CSV
from database import (
    create_scraper_run,
    finish_scraper_run,
    init_db,
    save_price_observation,
    upsert_pharmacy,
    upsert_product,
)
from scrapers import product_page


def load_products():
    with PRODUCTS_CSV.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def load_product_metadata():
    return {row["search_name"]: row for row in load_products()}


def run(source="manual"):
    init_db()
    run_id = create_scraper_run(source)
    products = load_products()
    product_metadata = load_product_metadata()
    saved = 0

    try:
        scraped_prices = product_page.scrape(products)

        seen = set()
        for item in scraped_prices:
            key = (item.pharmacy_name.lower(), item.search_name.lower(), item.product_url)
            if key in seen:
                continue
            seen.add(key)

            metadata = product_metadata.get(item.search_name, {})
            pharmacy_id = upsert_pharmacy(item.pharmacy_name, item.pharmacy_website)
            product_id = upsert_product(
                item.search_name,
                metadata.get("category"),
                metadata.get("display_name") or metadata.get("canonical_name"),
                metadata.get("brand"),
                metadata.get("laboratory"),
            )
            save_price_observation(
                pharmacy_id=pharmacy_id,
                product_id=product_id,
                product_name=item.product_name,
                price_cop=item.price_cop,
                product_url=item.product_url,
                list_price_cop=item.list_price_cop,
                discount_percent=item.discount_percent,
                product_match_status=item.product_match_status,
                product_match_score=item.product_match_score,
                match_notes=item.match_notes,
            )
            saved += 1

        finish_scraper_run(run_id, "success", saved)
        print(f"Listo. Se guardaron {saved} precios reales en la base de datos.")
    except Exception as error:
        finish_scraper_run(run_id, "error", saved, str(error))
        raise


if __name__ == "__main__":
    run()
