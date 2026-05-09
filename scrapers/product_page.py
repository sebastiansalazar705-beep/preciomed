import csv
import gzip
import json
import re
import time
import zlib
from html import unescape
from urllib.parse import quote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import PRODUCT_SOURCES_CSV, USER_AGENT
from scrapers.base import ScrapedPrice


PRICE_PATTERN = re.compile(r"\$\s*([0-9][0-9\.\,]*)")
TITLE_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")


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
    with urlopen(request, timeout=20) as response:
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


def extract_product_name(html, fallback, product_name_hint=None):
    if product_name_hint:
        return product_name_hint

    match = TITLE_PATTERN.search(html)
    if match:
        return clean_text(match.group(1))
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
    for match in PRICE_PATTERN.finditer(clean_text(html)):
        price = parse_price_cop(match.group(1))
        if price and price >= 100:
            return price
    return None


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

    product = products[0]
    item = product["items"][0]
    offer = item["sellers"][0]["commertialOffer"]
    price_cop = int(round(float(offer["Price"])))

    if price_cop <= 0:
        print(f"Producto sin precio disponible en Colsubsidio: {source['product_url']}")
        return None

    return ScrapedPrice(
        pharmacy_name=source["pharmacy_name"],
        pharmacy_website=source["pharmacy_website"],
        search_name=source["search_name"],
        product_name=product["productName"],
        price_cop=price_cop,
        product_url=product["link"],
    )


def scrape(products=None):
    results = []

    for source in load_sources():
        try:
            if is_colsubsidio_source(source):
                item = scrape_colsubsidio(source)
                if item:
                    results.append(item)
                time.sleep(1)
                continue

            html = fetch_html(source["product_url"])
            product_name = extract_product_name(
                html,
                source["search_name"],
                source.get("product_name_hint"),
            )
            price_cop = extract_price(html)

            if price_cop is None:
                print(f"No encontre precio en: {source['product_url']}")
                continue

            results.append(
                ScrapedPrice(
                    pharmacy_name=source["pharmacy_name"],
                    pharmacy_website=source["pharmacy_website"],
                    search_name=source["search_name"],
                    product_name=product_name,
                    price_cop=price_cop,
                    product_url=source["product_url"],
                )
            )
            time.sleep(1)
        except (HTTPError, URLError, TimeoutError) as error:
            print(f"No pude leer {source['product_url']}: {error}")

    return results
