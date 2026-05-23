from dataclasses import dataclass


@dataclass
class ScrapedPrice:
    pharmacy_name: str
    pharmacy_website: str
    search_name: str
    product_name: str
    price_cop: int
    product_url: str
    list_price_cop: int | None = None
    discount_percent: float | None = None
    product_match_status: str = "review"
    product_match_score: int = 0
    match_notes: str = ""
