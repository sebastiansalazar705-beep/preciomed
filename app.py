import hashlib
import hmac
import os
import re
import socket
from http import HTTPStatus
from html import escape
from urllib.parse import urlencode

import bcrypt
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from config import MAX_USERS
from database import (
    count_users,
    create_user,
    ensure_default_user,
    fetch_activity_logs,
    fetch_app_start_logs,
    fetch_latest_prices,
    fetch_users,
    get_user_by_email,
    get_user_by_username,
    init_db,
    log_activity,
    log_app_start,
    update_last_login,
    update_user_password,
)
from run_scraper import run as run_scraper


APP_NAME = "PrecioMed"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "preciomed123"
DEFAULT_EMAIL = "admin@preciomed.local"
DEFAULT_FULL_NAME = "Administrador PrecioMed"
SESSION_COOKIE = "preciomed_session"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title=APP_NAME)


def machine_identifier():
    hostname = socket.gethostname()
    try:
        ip_address = socket.gethostbyname(hostname)
        return f"{hostname} ({ip_address})"
    except OSError:
        return hostname


@app.on_event("startup")
def startup_event():
    try:
        init_db()
        ensure_default_user(
            get_admin_username(),
            get_admin_email(),
            DEFAULT_FULL_NAME,
            get_password_hash(),
        )
        log_app_start(
            username=None,
            ip_identifier=machine_identifier(),
            status="exitoso",
            error_message="Aplicacion iniciada correctamente.",
        )
        log_activity(
            "app_start",
            ip_identifier=machine_identifier(),
            status="exitoso",
            message="Aplicacion iniciada correctamente.",
        )
    except Exception as error:
        log_app_start(
            username=None,
            ip_identifier=machine_identifier(),
            status="error",
            error_message=str(error),
        )
        try:
            log_activity(
                "app_start",
                ip_identifier=machine_identifier(),
                status="error",
                message=str(error),
            )
        except Exception:
            pass
        raise


def get_secret_key():
    return os.environ.get("PRECIOMED_SECRET_KEY", "dev-secret-change-in-render")


def get_admin_username():
    return os.environ.get("PRECIOMED_USERNAME", DEFAULT_USERNAME)


def get_admin_email():
    return os.environ.get("PRECIOMED_ADMIN_EMAIL", DEFAULT_EMAIL).strip().lower()


def get_password_hash():
    password_hash = os.environ.get("PRECIOMED_PASSWORD_HASH")
    if password_hash:
        return password_hash
    return hash_password(DEFAULT_PASSWORD)


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    if not password_hash:
        return False
    if password_hash.startswith("$2"):
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, password_hash)


def sign_session(email):
    signature = hmac.new(
        get_secret_key().encode("utf-8"),
        email.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{email}:{signature}"


def current_username_from_cookie(cookie_value):
    if not cookie_value or ":" not in cookie_value:
        return None
    email, signature = cookie_value.split(":", 1)
    expected = sign_session(email).split(":", 1)[1]
    if not hmac.compare_digest(signature, expected):
        return None

    user = get_user_by_email(email)
    if not user or not user["is_active"]:
        return None
    return user["email"]


def verify_session(cookie_value):
    return current_username_from_cookie(cookie_value) is not None


def current_username(request):
    return current_username_from_cookie(request.cookies.get(SESSION_COOKIE))


def is_authenticated(request):
    return verify_session(request.cookies.get(SESSION_COOKIE))


def require_login(request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)
    return None


def money(value):
    if value is None:
        return "No detectado"
    return f"${int(value):,}".replace(",", ".")


def discount(value):
    if value is None:
        return "Sin descuento"
    return f"{float(value):.1f}%"


def status_label(value):
    return {
        "ok": "Verificado",
        "review": "Revisar",
        "different": "Diferente",
    }.get(value or "review", "Revisar")


def max_users_label():
    return "Ilimitado" if MAX_USERS <= 0 else str(MAX_USERS)


def max_users_reached():
    return MAX_USERS > 0 and count_users() >= MAX_USERS


def validate_password_strength(password):
    errors = []
    if len(password) < 8:
        errors.append("minimo 8 caracteres")
    if not re.search(r"[A-Z]", password):
        errors.append("una mayuscula")
    if not re.search(r"[a-z]", password):
        errors.append("una minuscula")
    if not re.search(r"\d", password):
        errors.append("un numero")
    return errors


def parse_price_filter(value):
    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    return int(digits) if digits else None


def latest_rows():
    init_db()
    return [dict(row) for row in fetch_latest_prices()]


def apply_filters(rows, medicine="", pharmacy="", min_price="", max_price=""):
    medicine = (medicine or "").strip().lower()
    pharmacy = (pharmacy or "").strip().lower()
    min_price_value = parse_price_filter(min_price)
    max_price_value = parse_price_filter(max_price)

    filtered_rows = []
    for row in rows:
        row_price = row["price_cop"] or 0
        if medicine and medicine not in row["search_name"].lower() and medicine not in row["product_name"].lower():
            continue
        if pharmacy and pharmacy != row["pharmacy_name"].lower():
            continue
        if min_price_value is not None and row_price < min_price_value:
            continue
        if max_price_value is not None and row_price > max_price_value:
            continue
        filtered_rows.append(row)

    return filtered_rows


def group_comparisons(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["search_name"], []).append(row)

    comparisons = []
    for medicine, items in grouped.items():
        sorted_items = sorted(items, key=lambda item: item["price_cop"] or 999999999)
        best = sorted_items[0] if sorted_items else None
        comparisons.append(
            {
                "medicine": medicine,
                "items": sorted_items,
                "best": best,
                "pharmacy_count": len({item["pharmacy_name"] for item in sorted_items}),
            }
        )

    return sorted(comparisons, key=lambda item: item["medicine"])


def layout(title, body, authenticated=False, username=None):
    login_link = (
        (
            f'<span class="nav-user">{escape(username or "")}</span>'
            '<a class="nav-link" href="/usuarios">Usuarios</a>'
            '<a class="nav-link" href="/logout">Cerrar sesion</a>'
        )
        if authenticated
        else '<a class="nav-link" href="/login">Ingresar</a>'
    )
    return f"""
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{escape(title)} - PrecioMed</title>
        <style>
            :root {{
                color-scheme: light;
                --bg: #f4f7fb;
                --surface: #ffffff;
                --line: #dce3ec;
                --text: #17212f;
                --muted: #627083;
                --brand: #0f766e;
                --brand-dark: #115e59;
                --warning: #8a6100;
                --danger: #9f1239;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                background: var(--bg);
                color: var(--text);
                font-family: Arial, Helvetica, sans-serif;
            }}
            header {{
                background: var(--brand-dark);
                color: white;
                padding: 18px 28px;
            }}
            .topbar {{
                align-items: center;
                display: flex;
                justify-content: space-between;
                margin: 0 auto;
                max-width: 1240px;
            }}
            .brand {{
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 0;
            }}
            .nav-link {{
                color: white;
                font-size: 14px;
                margin-left: 16px;
                text-decoration: none;
            }}
            .nav-user {{
                color: #d8fffb;
                font-size: 14px;
                margin-right: 4px;
            }}
            main {{
                margin: 0 auto;
                max-width: 1240px;
                padding: 24px;
            }}
            h1 {{ font-size: 28px; margin: 0 0 6px; }}
            h2 {{ font-size: 20px; margin: 28px 0 12px; }}
            p {{ color: var(--muted); line-height: 1.5; }}
            .panel {{
                background: var(--surface);
                border: 1px solid var(--line);
                border-radius: 8px;
                padding: 18px;
            }}
            .filters {{
                display: grid;
                gap: 12px;
                grid-template-columns: 2fr 1fr 1fr 1fr auto auto;
                margin: 18px 0;
            }}
            input, select, button, .button {{
                border: 1px solid var(--line);
                border-radius: 6px;
                font: inherit;
                min-height: 42px;
                padding: 9px 12px;
            }}
            button, .button {{
                background: var(--brand);
                border-color: var(--brand);
                color: white;
                cursor: pointer;
                text-decoration: none;
                white-space: nowrap;
            }}
            .button.secondary {{
                background: white;
                color: var(--brand-dark);
            }}
            table {{
                background: white;
                border: 1px solid var(--line);
                border-collapse: collapse;
                width: 100%;
            }}
            th, td {{
                border-bottom: 1px solid var(--line);
                padding: 11px;
                text-align: left;
                vertical-align: top;
            }}
            th {{ background: #eaf3f2; font-size: 13px; }}
            .price {{ font-weight: 700; white-space: nowrap; }}
            .muted {{ color: var(--muted); font-size: 13px; }}
            .badge {{
                border-radius: 999px;
                display: inline-block;
                font-size: 12px;
                font-weight: 700;
                padding: 4px 8px;
            }}
            .ok {{ background: #d9f8ea; color: #166534; }}
            .review {{ background: #fff2c4; color: var(--warning); }}
            .different {{ background: #ffe4e6; color: var(--danger); }}
            .summary {{
                display: grid;
                gap: 12px;
                grid-template-columns: repeat(4, 1fr);
                margin: 18px 0;
            }}
            .summary strong {{ display: block; font-size: 24px; margin-top: 4px; }}
            .login {{
                margin: 56px auto;
                max-width: 420px;
            }}
            .login form {{ display: grid; gap: 12px; }}
            .error {{ color: var(--danger); font-weight: 700; }}
            .success {{ color: #166534; font-weight: 700; }}
            @media (max-width: 900px) {{
                .filters, .summary {{ grid-template-columns: 1fr; }}
                main {{ padding: 16px; }}
            }}
            @media print {{
                header, .filters, .actions, .nav-link {{ display: none; }}
                body {{ background: white; }}
                main {{ max-width: none; padding: 0; }}
                .panel, table {{ border-color: #999; }}
                a {{ color: black; text-decoration: none; }}
            }}
        </style>
    </head>
    <body>
        <header>
            <div class="topbar">
                <div class="brand">PrecioMed</div>
                {login_link}
            </div>
        </header>
        <main>{body}</main>
    </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
def home(request: Request, medicine: str = "", pharmacy: str = "", min_price: str = "", max_price: str = ""):
    redirect = require_login(request)
    if redirect:
        return redirect

    username = current_username(request)
    rows = latest_rows()
    filtered_rows = apply_filters(rows, medicine, pharmacy, min_price, max_price)
    comparisons = group_comparisons(filtered_rows)
    pharmacies = sorted({row["pharmacy_name"] for row in rows})
    verified = sum(1 for row in filtered_rows if row["product_match_status"] == "ok")
    user_total = count_users()

    options = ['<option value="">Todas</option>']
    for item in pharmacies:
        selected = " selected" if item.lower() == pharmacy.lower() else ""
        options.append(f'<option value="{escape(item)}"{selected}>{escape(item)}</option>')

    filters = f"""
    <form class="filters" method="get">
        <input name="medicine" placeholder="Buscar medicamento" value="{escape(medicine)}">
        <select name="pharmacy">{"".join(options)}</select>
        <input name="min_price" inputmode="numeric" placeholder="Precio minimo" value="{escape(min_price)}">
        <input name="max_price" inputmode="numeric" placeholder="Precio maximo" value="{escape(max_price)}">
        <button type="submit">Filtrar</button>
        <a class="button secondary" href="/">Limpiar</a>
    </form>
    """

    summary = f"""
    <section class="summary">
        <div class="panel">Medicamentos<strong>{len(comparisons)}</strong></div>
        <div class="panel">Registros<strong>{len(filtered_rows)}</strong></div>
        <div class="panel">Farmacias<strong>{len(pharmacies)}</strong></div>
        <div class="panel">Usuarios<strong>{user_total}/{max_users_label()}</strong></div>
    </section>
    """

    sections = []
    for comparison in comparisons:
        best = comparison["best"]
        best_text = (
            f"Mejor precio: {money(best['price_cop'])} en {escape(best['pharmacy_name'])}"
            if best
            else "Sin precios disponibles"
        )
        rows_html = []
        for row in comparison["items"]:
            query = urlencode({"medicine": row["search_name"], "pharmacy": row["pharmacy_name"]})
            status = row["product_match_status"] or "review"
            rows_html.append(
                f"""
                <tr>
                    <td>{escape(row["pharmacy_name"])}</td>
                    <td>
                        {escape(row["product_name"])}
                        <div class="muted">{escape(row["match_notes"] or "")}</div>
                    </td>
                    <td class="price">{money(row["price_cop"])}</td>
                    <td>{money(row["list_price_cop"])}</td>
                    <td>{discount(row["discount_percent"])}</td>
                    <td>
                        <span class="badge {escape(status)}">{status_label(status)}</span>
                        <div class="muted">{row["product_match_score"] or 0}% coincidencia</div>
                    </td>
                    <td>{escape(row["observed_at"][:10])}</td>
                    <td><a href="{escape(row["product_url"])}" target="_blank">Ver</a></td>
                    <td><a href="/?{escape(query)}">Comparar</a></td>
                </tr>
                """
            )
        sections.append(
            f"""
            <section>
                <h2>{escape(comparison["medicine"])}</h2>
                <p>{best_text}. Disponible en {comparison["pharmacy_count"]} farmacia(s).</p>
                <table>
                    <thead>
                        <tr>
                            <th>Farmacia</th>
                            <th>Medicamento encontrado</th>
                            <th>Precio</th>
                            <th>Precio antes</th>
                            <th>Descuento</th>
                            <th>Validacion</th>
                            <th>Fecha</th>
                            <th>Fuente</th>
                            <th>Accion</th>
                        </tr>
                    </thead>
                    <tbody>{"".join(rows_html)}</tbody>
                </table>
            </section>
            """
        )

    body = f"""
    <h1>Dashboard de medicamentos</h1>
    <p>Consulta precios publicados por farmacia, valida coincidencias y compara el mejor precio disponible.</p>
    <div class="actions">
        <a class="button" href="/actualizar">Actualizar precios</a>
        <button onclick="window.print()">Imprimir vista</button>
    </div>
    {filters}
    {summary}
    {"".join(sections) if sections else '<div class="panel">No hay resultados con esos filtros.</div>'}
    """
    return HTMLResponse(layout("Dashboard", body, authenticated=True, username=username))


@app.head("/")
def home_head():
    return Response(status_code=HTTPStatus.OK)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)
    error_html = '<p class="error">Usuario o contrasena incorrectos.</p>' if error else ""
    body = f"""
    <section class="panel login">
        <h1>Ingresar a PrecioMed</h1>
        <p>Acceso basico para proteger el panel de consulta y actualizacion.</p>
        {error_html}
        <form method="post" action="/login">
            <input name="email" type="email" placeholder="Correo electronico" autocomplete="email" required>
            <input name="password" type="password" placeholder="Contrasena" autocomplete="current-password" required>
            <label class="muted">
                <input name="remember" type="checkbox" value="1" style="min-height:auto; width:auto;">
                Recordar sesion
            </label>
            <button type="submit">Ingresar</button>
        </form>
        <p><a href="/registro">Crear usuario nuevo</a></p>
        <p class="muted">Correo inicial: admin@preciomed.local. Contrasena inicial: preciomed123. Cambialos en Render con variables de entorno.</p>
    </section>
    """
    return HTMLResponse(layout("Login", body))


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember: str = Form(""),
):
    email = email.strip().lower()
    user = get_user_by_email(email)
    valid_password = user and user["is_active"] and verify_password(password, user["password_hash"])
    if not valid_password:
        log_activity(
            "login",
            username=user["username"] if user else None,
            email=email,
            ip_identifier=request.client.host if request.client else None,
            status="error",
            message="Correo o contrasena incorrectos.",
        )
        return RedirectResponse("/login?error=1", status_code=HTTPStatus.SEE_OTHER)

    if not user["password_hash"].startswith("$2"):
        update_user_password(user["id"], hash_password(password))

    update_last_login(user["id"])
    log_activity(
        "login",
        username=user["username"],
        email=user["email"],
        ip_identifier=request.client.host if request.client else None,
        status="exitoso",
        message="Inicio de sesion exitoso.",
    )
    response = RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(user["email"]),
        httponly=True,
        secure=os.environ.get("RENDER") == "true",
        samesite="lax",
        max_age=60 * 60 * 24 * 30 if remember else 60 * 60 * 8,
    )
    return response


@app.get("/registro", response_class=HTMLResponse)
def register_form(request: Request, error: str = "", success: str = ""):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)

    error_messages = {
        "max": "Se alcanzó el número máximo de usuarios permitidos.",
        "exists": "Ese correo electronico ya esta registrado.",
        "email": "Escribe un correo electronico valido.",
        "match": "Las contrasenas no coinciden.",
        "weak": "La contrasena debe tener minimo 8 caracteres, una mayuscula, una minuscula y un numero.",
    }
    error_html = f'<p class="error">{error_messages.get(error, "")}</p>' if error else ""
    success_html = '<p class="success">Usuario creado. Ya puedes iniciar sesion.</p>' if success else ""
    body = f"""
    <section class="panel login">
        <h1>Crear usuario</h1>
        <p>Usuarios registrados: {count_users()} de {max_users_label()} permitidos.</p>
        {error_html}
        {success_html}
        <form method="post" action="/registro">
            <input name="full_name" placeholder="Nombre completo" autocomplete="name" required>
            <input name="email" type="email" placeholder="Correo electronico" autocomplete="email" required>
            <input name="password" type="password" placeholder="Contrasena" autocomplete="new-password" required>
            <input name="confirm_password" type="password" placeholder="Confirmar contrasena" autocomplete="new-password" required>
            <button type="submit">Crear usuario</button>
        </form>
        <p class="muted">La contrasena debe incluir minimo 8 caracteres, una mayuscula, una minuscula y un numero.</p>
        <p><a href="/login">Volver al login</a></p>
    </section>
    """
    return HTMLResponse(layout("Registro", body))


@app.post("/registro")
def register_user(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    full_name = full_name.strip()
    email = email.strip().lower()
    username = email

    if max_users_reached():
        return RedirectResponse("/registro?error=max", status_code=HTTPStatus.SEE_OTHER)
    if not EMAIL_PATTERN.match(email):
        return RedirectResponse("/registro?error=email", status_code=HTTPStatus.SEE_OTHER)
    if get_user_by_email(email):
        return RedirectResponse("/registro?error=exists", status_code=HTTPStatus.SEE_OTHER)
    if password != confirm_password:
        return RedirectResponse("/registro?error=match", status_code=HTTPStatus.SEE_OTHER)
    if validate_password_strength(password):
        return RedirectResponse("/registro?error=weak", status_code=HTTPStatus.SEE_OTHER)

    create_user(username, full_name, email, hash_password(password))
    log_activity(
        "register",
        username=username,
        email=email,
        ip_identifier=request.client.host if request.client else None,
        status="exitoso",
        message="Usuario registrado correctamente.",
    )
    return RedirectResponse("/registro?success=1", status_code=HTTPStatus.SEE_OTHER)


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/usuarios", response_class=HTMLResponse)
def users_view(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    username = current_username(request)
    user_rows = fetch_users()
    log_rows = fetch_activity_logs()

    users_html = []
    for user in user_rows:
        status = "Activo" if user["is_active"] else "Inactivo"
        users_html.append(
            f"""
            <tr>
                <td>{escape(user["full_name"] or "")}</td>
                <td>{escape(user["username"])}</td>
                <td>{escape(user["email"] or "")}</td>
                <td>{status}</td>
                <td>{escape(user["created_at"][:19])}</td>
                <td>{escape((user["last_login_at"] or "")[:19])}</td>
            </tr>
            """
        )

    logs_html = []
    for log in log_rows:
        logs_html.append(
            f"""
            <tr>
                <td>{escape(log["created_at"][:19])}</td>
                <td>{escape(log["event_type"])}</td>
                <td>{escape(log["username"] or "Sistema")}</td>
                <td>{escape(log["email"] or "")}</td>
                <td>{escape(log["ip_identifier"] or "No detectado")}</td>
                <td>{escape(log["status"])}</td>
                <td>{escape(log["message"] or "")}</td>
            </tr>
            """
        )

    body = f"""
    <h1>Usuarios y registros de inicio</h1>
    <p>Usuarios registrados: {count_users()} de {max_users_label()} permitidos.</p>
    <section>
        <h2>Usuarios</h2>
        <table>
            <thead>
                <tr>
                    <th>Nombre completo</th>
                    <th>Usuario</th>
                    <th>Correo</th>
                    <th>Estado</th>
                    <th>Creado</th>
                    <th>Ultimo ingreso</th>
                </tr>
            </thead>
            <tbody>{"".join(users_html)}</tbody>
        </table>
    </section>
    <section>
        <h2>Registro de inicios</h2>
        <table>
            <thead>
                <tr>
                    <th>Fecha y hora</th>
                    <th>Evento</th>
                    <th>Usuario</th>
                    <th>Correo</th>
                    <th>IP / equipo</th>
                    <th>Estado</th>
                    <th>Mensaje</th>
                </tr>
            </thead>
            <tbody>{"".join(logs_html)}</tbody>
        </table>
    </section>
    """
    return HTMLResponse(layout("Usuarios", body, authenticated=True, username=username))


@app.get("/actualizar")
def actualizar(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    run_scraper()
    return RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME}


def run_server():
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
