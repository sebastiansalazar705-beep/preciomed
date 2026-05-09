from dataclasses import dataclass


@dataclass
class ScrapedPrice:
    pharmacy_name: str
    pharmacy_website: str
    search_name: str
    product_name: str
    price_cop: int
    product_url: str
