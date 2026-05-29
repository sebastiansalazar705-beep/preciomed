import csv
import gzip
import json
import re
import unicodedata
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import quote, unquote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import (
    PRODUCT_SOURCES_CSV,
    SCRAPER_MAX_WORKERS,
    SCRAPER_REQUEST_TIMEOUT,
    USER_AGENT,
)
from scrapers.base import ScrapedPrice


PRICE_PATTERN = re.compile(r"\$\s*([0-9][0-9\.\,]*)")
TITLE_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
TOKEN_PATTERN = re.compile(r"[a-z]+|\d+")
NOISE_TOKENS = {
    "www",
    "com",
    "co",
    "producto",
    "products",
    "html",
    "p",
    "cocv",
    "caja",
    "blister",
    "tableta",
    "tabletas",
    "capsula",
    "capsulas",
    "recubierta",
    "recubiertas",
    "frasco",
    "solucion",
    "oral",
    "dura",
    "genfar",
    "mk",
    "x",
}


def load_sources():
    with PRODUCT_SOURCES_CSV.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def fetch_html(url):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    with urlopen(request, timeout=SCRAPER_REQUEST_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read()
        encoding = response.headers.get("Content-Encoding", "").lower()

        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)

        return body.decode(charset, errors="replace")


def fetch_json(url):
    return json.loads(fetch_html(url))


def clean_text(value):
    value = TAG_PATTERN.sub(" ", value)
    value = unescape(value)
    return SPACE_PATTERN.sub(" ", value).strip()


def normalize_text(value):
    value = unquote(value or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    return SPACE_PATTERN.sub(" ", value).strip()


def tokens_from_text(value):
    return [token for token in TOKEN_PATTERN.findall(normalize_text(value))]


def important_tokens(value):
    return {
        token
        for token in tokens_from_text(value)
        if len(token) > 2
        and token not in NOISE_TOKENS
        and not (token.isdigit() and len(token) > 4)
    }


def expected_name_from_source(source):
    if source.get("product_name_hint"):
        return source["product_name_hint"]

    path_parts = [
        part
        for part in urlparse(source["product_url"]).path.split("/")
        if part and part.lower() != "p"
    ]
    slug = path_parts[-1] if path_parts else ""
    if slug.lower().endswith(".html") and len(path_parts) >= 2:
        slug = path_parts[-2]

    slug = re.sub(r"^\d+-", "", slug)
    slug = re.sub(r"-?\d{8,}$", "", slug)
    slug = re.sub(r"COCV_\d+", "", slug, flags=re.IGNORECASE)
    slug = slug.replace("-", " ")
    if not important_tokens(slug):
        return source["search_name"]
    return slug or source["search_name"]


def validate_product_match(source, product_name):
    expected_name = expected_name_from_source(source)
    expected_tokens = important_tokens(expected_name)
    found_tokens = important_tokens(product_name)
    brand_tokens = important_tokens(source.get("brand") or "")

    if not expected_tokens:
        return "review", 0, "No hay suficientes datos del producto esperado."

    if brand_tokens and not brand_tokens <= found_tokens:
        missing_brand = sorted(brand_tokens - found_tokens)
        return (
            "different",
            0,
            "Marca esperada no coincide: " + ", ".join(missing_brand),
        )

    matching_tokens = expected_tokens & found_tokens
    score = round((len(matching_tokens) / len(expected_tokens)) * 100)
    missing_tokens = sorted(expected_tokens - found_tokens)

    expected_numbers = {token for token in tokens_from_text(expected_name) if token.isdigit()}
    found_numbers = {token for token in tokens_from_text(product_name) if token.isdigit()}
    missing_numbers = sorted(expected_numbers - found_numbers)

    if missing_numbers:
        return (
            "different",
            score,
            "Faltan datos clave de dosis/presentacion: " + ", ".join(missing_numbers),
        )

    if score >= 70:
        return "ok", score, "Producto coincide con el enlace esperado."
    if score >= 45:
        return "review", score, "Revisar coincidencia: faltan " + ", ".join(missing_tokens)
    return "different", score, "Producto diferente: faltan " + ", ".join(missing_tokens)


def extract_product_name(html, fallback, product_name_hint=None):
    match = TITLE_PATTERN.search(html)
    if match:
        return clean_text(match.group(1))
    if product_name_hint:
        return product_name_hint
    return fallback.title()


def parse_price_cop(raw_price):
    raw_price = raw_price.strip()

    if "," in raw_price:
        integer_part, decimal_part = raw_price.rsplit(",", 1)
        if len(re.sub(r"\D", "", decimal_part)) == 2:
            raw_price = integer_part

    digits = re.sub(r"\D", "", raw_price)
    if not digits:
        return None
    return int(digits)


def extract_price(html):
    for price in collect_price_candidates(html):
        if price and price >= 100:
            return price
    return None


def extract_price_pair(html):
    prices = collect_price_candidates(html)

    if not prices:
        return None, None, None

    sale_price = prices[0]
    list_price = None
    for price in prices[1:4]:
        if price > sale_price:
            list_price = price
            break

    discount_percent = calculate_discount(list_price, sale_price)
    return sale_price, list_price, discount_percent


def collect_price_candidates(html):
    text = product_price_area(clean_text(html))
    prices = []
    for match in PRICE_PATTERN.finditer(text):
        raw_price = match.group(1)
        before = text[max(0, match.start() - 35) : match.start()].lower()

        if is_unit_price_context(before):
            continue
        if looks_like_decimal_unit_price(raw_price):
            continue

        price = parse_price_cop(raw_price)
        if price and 1_000 <= price <= 5_000_000:
            prices.append(price)
    return prices


def product_price_area(text):
    for marker in (" Agregar producto ", " Cantidad "):
        marker_index = text.find(marker)
        if marker_index > 0 and PRICE_PATTERN.search(text[:marker_index]):
            return text[:marker_index]
    return text


def is_unit_price_context(before):
    unit_markers = (
        "pum:",
        "unidades a",
        "unidad a",
        "tableta a",
        "mililitros a",
        "gramos a",
        "otro a",
    )
    return any(marker in before for marker in unit_markers)


def looks_like_decimal_unit_price(raw_price):
    if "," in raw_price:
        integer_part, decimal_part = raw_price.rsplit(",", 1)
        return len(re.sub(r"\D", "", integer_part)) <= 4 and len(decimal_part) == 2
    if "." in raw_price:
        integer_part, decimal_part = raw_price.rsplit(".", 1)
        return len(re.sub(r"\D", "", integer_part)) <= 4 and len(decimal_part) == 2
    return False


def calculate_discount(list_price, sale_price):
    if not list_price or not sale_price or list_price <= sale_price:
        return None
    return round(((list_price - sale_price) / list_price) * 100, 1)


def is_colsubsidio_source(source):
    return "drogueriascolsubsidio.com" in source["product_url"]


def colsubsidio_api_url(source):
    parsed_url = urlparse(source["product_url"])
    path = parsed_url.path.strip("/")

    if path.endswith("/p"):
        search_term = path.removesuffix("/p").strip("/")
    else:
        search_term = source["search_name"].replace(" ", "-")

    return (
        "https://www.drogueriascolsubsidio.com"
        f"/api/catalog_system/pub/products/search/{quote(search_term)}"
    )


def scrape_colsubsidio(source):
    products = fetch_json(colsubsidio_api_url(source))
    if not products:
        print(f"No encontre producto en API Colsubsidio: {source['product_url']}")
        return None

    product = choose_colsubsidio_product(source, products)
    item = product["items"][0]
    offer = item["sellers"][0]["commertialOffer"]
    price_cop = int(round(float(offer["Price"])))
    list_price_cop = int(round(float(offer.get("ListPrice") or 0))) or None
    discount_percent = calculate_discount(list_price_cop, price_cop)

    if price_cop <= 0:
        print(f"Producto sin precio disponible en Colsubsidio: {source['product_url']}")
        return None

    match_status, match_score, match_notes = validate_product_match(
        source,
        product["productName"],
    )

    return ScrapedPrice(
        pharmacy_name=source["pharmacy_name"],
        pharmacy_website=source["pharmacy_website"],
        search_name=source["search_name"],
        product_name=product["productName"],
        price_cop=price_cop,
        list_price_cop=list_price_cop,
        discount_percent=discount_percent,
        product_match_status=match_status,
        product_match_score=match_score,
        match_notes=match_notes,
        product_url=product["link"],
    )


def choose_colsubsidio_product(source, products):
    expected_path = normalize_text(urlparse(source["product_url"]).path.rstrip("/"))
    for product in products:
        product_path = normalize_text(urlparse(product.get("link", "")).path.rstrip("/"))
        if product_path == expected_path:
            return product

    expected_tokens = important_tokens(expected_name_from_source(source))
    brand_tokens = important_tokens(source.get("brand") or "")
    scored_products = []
    for product in products:
        product_tokens = important_tokens(product.get("productName", ""))
        if brand_tokens and not brand_tokens <= product_tokens:
            continue
        score = len(expected_tokens & product_tokens)
        scored_products.append((score, product))
    if not scored_products:
        return products[0]
    scored_products.sort(key=lambda item: item[0], reverse=True)
    return scored_products[0][1]


def scrape_source(source):
    if is_colsubsidio_source(source):
        return scrape_colsubsidio(source)

    html = fetch_html(source["product_url"])
    product_name = extract_product_name(
        html,
        source["search_name"],
        source.get("product_name_hint"),
    )
    price_cop, list_price_cop, discount_percent = extract_price_pair(html)

    if price_cop is None:
        print(f"No encontre precio en: {source['product_url']}")
        return None

    match_status, match_score, match_notes = validate_product_match(
        source,
        product_name,
    )

    return ScrapedPrice(
        pharmacy_name=source["pharmacy_name"],
        pharmacy_website=source["pharmacy_website"],
        search_name=source["search_name"],
        product_name=product_name,
        price_cop=price_cop,
        list_price_cop=list_price_cop,
        discount_percent=discount_percent,
        product_match_status=match_status,
        product_match_score=match_score,
        match_notes=match_notes,
        product_url=source["product_url"],
    )


def scrape(products=None):
    results = []
    sources = load_sources()
    max_workers = max(1, min(SCRAPER_MAX_WORKERS, len(sources) or 1))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_by_source = {
            executor.submit(scrape_source, source): source
            for source in sources
        }
        for future in as_completed(future_by_source):
            source = future_by_source[future]
            try:
                item = future.result()
                if item:
                    results.append(item)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
                print(f"No pude leer {source['product_url']}: {error}")
            except Exception as error:
                print(f"Error procesando {source['product_url']}: {error}")

    return results
