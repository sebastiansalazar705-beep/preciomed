from collections import defaultdict
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import os

from database import fetch_latest_prices, init_db


HTML_START = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Comparador de precios</title>
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f6f7f9;
            color: #1d2733;
        }

        header {
            background: #146c5a;
            color: white;
            padding: 24px;
        }

        main {
            max-width: 1000px;
            margin: 0 auto;
            padding: 24px;
        }

        h1 {
            margin: 0;
            font-size: 28px;
        }

        h2 {
            margin-top: 28px;
            font-size: 22px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border: 1px solid #d9dee5;
        }

        th,
        td {
            padding: 12px;
            border-bottom: 1px solid #e6e9ee;
            text-align: left;
            vertical-align: top;
        }

        th {
            background: #eef4f2;
        }

        .price {
            font-weight: bold;
            white-space: nowrap;
        }

        .empty {
            background: white;
            border: 1px solid #d9dee5;
            padding: 18px;
        }

        a {
            color: #146c5a;
        }
    </style>
</head>
<body>
    <header>
        <h1>Comparador de precios de farmacias</h1>
    </header>
    <main>
"""


HTML_END = """
    </main>
</body>
</html>
"""


def format_price(value):
    return f"${value:,.0f}".replace(",", ".")


def render_page():
    init_db()
    grouped_prices = defaultdict(list)

    for row in fetch_latest_prices():
        grouped_prices[row["search_name"]].append(row)

    content = [HTML_START]

    if not grouped_prices:
        content.append(
            """
            <div class="empty">
                Todavia no hay precios. Ejecuta primero <strong>python run_scraper.py</strong>.
            </div>
            """
        )
    else:
        for product, rows in grouped_prices.items():
            content.append(f"<h2>{escape(product)}</h2>")
            content.append(
                """
                <table>
                    <thead>
                        <tr>
                            <th>Farmacia</th>
                            <th>Producto encontrado</th>
                            <th>Precio</th>
                            <th>Fecha consulta</th>
                            <th>Link</th>
                        </tr>
                    </thead>
                    <tbody>
                """
            )

            for row in rows:
                content.append(
                    f"""
                    <tr>
                        <td>{escape(row["pharmacy_name"])}</td>
                        <td>{escape(row["product_name"])}</td>
                        <td class="price">{format_price(row["price_cop"])}</td>
                        <td>{escape(row["observed_at"][:10])}</td>
                        <td><a href="{escape(row["product_url"])}" target="_blank">Ver</a></td>
                    </tr>
                    """
                )

            content.append("</tbody></table>")

    content.append(HTML_END)
    return "".join(content).encode("utf-8")


class PriceComparisonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Pagina no encontrada")
            return

        html = render_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def run_server():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    server = HTTPServer((host, port), PriceComparisonHandler)
    print(f"Pagina disponible en http://{host}:{port}")
    print("Presiona Ctrl+C para detenerla.")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
