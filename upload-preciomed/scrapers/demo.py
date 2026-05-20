from scrapers.base import ScrapedPrice


DEMO_PRICES = {
    "acetaminofen": [
        ("Farmacia Demo Norte", "Acetaminofen 500 mg caja x 20 tabletas", 7200),
        ("Farmacia Demo Centro", "Acetaminofen 500 mg caja x 20 tabletas", 6900),
    ],
    "ibuprofeno": [
        ("Farmacia Demo Norte", "Ibuprofeno 400 mg caja x 10 capsulas", 8500),
        ("Farmacia Demo Centro", "Ibuprofeno 400 mg caja x 10 capsulas", 8200),
    ],
    "loratadina": [
        ("Farmacia Demo Norte", "Loratadina 10 mg caja x 10 tabletas", 9800),
        ("Farmacia Demo Centro", "Loratadina 10 mg caja x 10 tabletas", 9300),
    ],
    "vitamina c": [
        ("Farmacia Demo Norte", "Vitamina C 500 mg frasco x 30 tabletas", 18500),
        ("Farmacia Demo Centro", "Vitamina C 500 mg frasco x 30 tabletas", 17900),
    ],
    "suero oral": [
        ("Farmacia Demo Norte", "Suero oral sobre x 1 unidad", 2400),
        ("Farmacia Demo Centro", "Suero oral sobre x 1 unidad", 2200),
    ],
}


def scrape(products):
    results = []

    for product in products:
        search_name = product["search_name"].strip().lower()
        for pharmacy_name, product_name, price_cop in DEMO_PRICES.get(search_name, []):
            results.append(
                ScrapedPrice(
                    pharmacy_name=pharmacy_name,
                    pharmacy_website="https://example.com",
                    search_name=search_name,
                    product_name=product_name,
                    price_cop=price_cop,
                    product_url="https://example.com/producto-demo",
                )
            )

    return results
