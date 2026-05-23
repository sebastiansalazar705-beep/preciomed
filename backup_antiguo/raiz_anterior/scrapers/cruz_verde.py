from scrapers.product_page import scrape as scrape_sources


def scrape(products):
    return [
        item
        for item in scrape_sources(products)
        if item.pharmacy_name.lower() == "cruz verde"
    ]
