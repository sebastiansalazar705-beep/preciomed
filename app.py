import hashlib
import hmac
import os
import re
import secrets
import socket
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http import HTTPStatus
from html import escape
from urllib.parse import urlencode

import bcrypt
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from config import (
    EMAIL_FROM,
    EMAIL_PASSWORD,
    EMAIL_USER,
    LOGIN_LOCK_MINUTES,
    MAX_LOGIN_ATTEMPTS,
    MAX_USERS,
    REMEMBER_SESSION_DAYS,
    RESET_CODE_MINUTES,
    RESET_MAX_ATTEMPTS,
    SESSION_HOURS,
    SMTP_HOST,
    SMTP_PORT,
)
from database import (
    count_failed_logins,
    count_users,
    create_password_reset_code,
    create_user,
    ensure_default_user,
    fetch_activity_logs,
    fetch_app_start_logs,
    fetch_latest_prices,
    fetch_users,
    get_latest_password_reset_code_by_email,
    get_password_reset_code,
    get_user_by_email,
    get_user_by_username,
    increment_password_reset_attempt,
    init_db,
    log_activity,
    log_app_start,
    mark_password_reset_code_used,
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
CODE_PATTERN = re.compile(r"^\d{6}$")

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


def utc_now():
    return datetime.now(timezone.utc)


def request_ip(request):
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def sign_session(email, expires_at=None):
    expires_at = expires_at or (utc_now() + timedelta(hours=SESSION_HOURS))
    expires_text = str(int(expires_at.timestamp()))
    payload = f"{email}:{expires_text}"
    signature = hmac.new(
        get_secret_key().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def current_username_from_cookie(cookie_value):
    if not cookie_value or cookie_value.count(":") != 2:
        return None
    email, expires_text, signature = cookie_value.split(":", 2)
    if not expires_text.isdigit() or int(expires_text) < int(utc_now().timestamp()):
        return None
    expected = sign_session(
        email,
        datetime.fromtimestamp(int(expires_text), timezone.utc),
    ).split(":", 2)[2]
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


def current_user(request):
    email = current_username(request)
    return get_user_by_email(email) if email else None


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


def generate_security_code():
    return f"{secrets.randbelow(1000000):06d}"


def send_security_code(email, code):
    if not SMTP_HOST or not EMAIL_USER or not EMAIL_PASSWORD:
        return False, "SMTP no configurado. Configura SMTP_HOST, SMTP_PORT, EMAIL_USER y EMAIL_PASSWORD."

    message = EmailMessage()
    message["Subject"] = "Codigo de recuperacion PrecioMed"
    message["From"] = EMAIL_FROM or EMAIL_USER
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "Hola.",
                "",
                "Tu codigo de recuperacion de PrecioMed es:",
                code,
                "",
                f"Este codigo vence en {RESET_CODE_MINUTES} minutos.",
                "Si no pediste recuperar tu contrasena, ignora este correo.",
            ]
        )
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(message)
    return True, "Correo enviado."


def reset_code_expired(row):
    expires_at = datetime.fromisoformat(row["expires_at"])
    return expires_at < utc_now()


def recovery_url(path, **params):
    return f"{path}?{urlencode(params)}"


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
            '<a class="nav-link" href="/perfil">Perfil</a>'
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
    error_messages = {
        "1": "Usuario o contrasena incorrectos.",
        "locked": f"Demasiados intentos fallidos. Intenta de nuevo en {LOGIN_LOCK_MINUTES} minutos.",
        "expired": "Tu sesion expiro. Ingresa de nuevo.",
    }
    error_html = f'<p class="error">{error_messages.get(error, "")}</p>' if error else ""
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
        <p><a href="/recuperar">Olvidaste tu contrasena?</a></p>
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
    ip_address = request_ip(request)
    if count_failed_logins(email, ip_address, LOGIN_LOCK_MINUTES) >= MAX_LOGIN_ATTEMPTS:
        log_activity(
            "login",
            email=email,
            ip_identifier=ip_address,
            status="error",
            message="Login bloqueado temporalmente por demasiados intentos.",
        )
        return RedirectResponse("/login?error=locked", status_code=HTTPStatus.SEE_OTHER)

    user = get_user_by_email(email)
    valid_password = user and user["is_active"] and verify_password(password, user["password_hash"])
    if not valid_password:
        log_activity(
            "login",
            username=user["username"] if user else None,
            email=email,
            ip_identifier=ip_address,
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
        ip_identifier=ip_address,
        status="exitoso",
        message="Inicio de sesion exitoso.",
    )
    session_expires_at = utc_now() + (
        timedelta(days=REMEMBER_SESSION_DAYS) if remember else timedelta(hours=SESSION_HOURS)
    )
    response = RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(user["email"], session_expires_at),
        httponly=True,
        secure=os.environ.get("RENDER") == "true",
        samesite="lax",
        max_age=60 * 60 * 24 * REMEMBER_SESSION_DAYS if remember else 60 * 60 * SESSION_HOURS,
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
        ip_identifier=request_ip(request),
        status="exitoso",
        message="Usuario registrado correctamente.",
    )
    return RedirectResponse("/registro?success=1", status_code=HTTPStatus.SEE_OTHER)


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/perfil", response_class=HTMLResponse)
def profile_form(request: Request, error: str = "", success: str = ""):
    redirect = require_login(request)
    if redirect:
        return redirect

    user = current_user(request)
    error_messages = {
        "current": "La contrasena actual es incorrecta.",
        "match": "La nueva contrasena y su confirmacion no coinciden.",
        "weak": "La nueva contrasena debe tener minimo 8 caracteres, una mayuscula, una minuscula y un numero.",
    }
    error_html = f'<p class="error">{error_messages.get(error, "")}</p>' if error else ""
    success_html = '<p class="success">Contrasena actualizada correctamente.</p>' if success else ""
    body = f"""
    <h1>Perfil de usuario</h1>
    <section class="panel login">
        <h2>Datos de la cuenta</h2>
        <p><strong>Nombre:</strong> {escape(user["full_name"] or "")}</p>
        <p><strong>Correo:</strong> {escape(user["email"] or "")}</p>
    </section>
    <section class="panel login">
        <h2>Cambiar contrasena</h2>
        {error_html}
        {success_html}
        <form method="post" action="/perfil/cambiar-contrasena">
            <input name="current_password" type="password" placeholder="Contrasena actual" autocomplete="current-password" required>
            <input name="new_password" type="password" placeholder="Nueva contrasena" autocomplete="new-password" required>
            <input name="confirm_password" type="password" placeholder="Confirmar nueva contrasena" autocomplete="new-password" required>
            <button type="submit">Actualizar contrasena</button>
        </form>
        <p class="muted">Usa minimo 8 caracteres con mayuscula, minuscula y numero.</p>
    </section>
    """
    return HTMLResponse(layout("Perfil", body, authenticated=True, username=user["email"]))


@app.post("/perfil/cambiar-contrasena")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    redirect = require_login(request)
    if redirect:
        return redirect

    user = current_user(request)
    if not verify_password(current_password, user["password_hash"]):
        log_activity(
            "password_change",
            username=user["username"],
            email=user["email"],
            ip_identifier=request_ip(request),
            status="error",
            message="La contrasena actual es incorrecta.",
        )
        return RedirectResponse("/perfil?error=current", status_code=HTTPStatus.SEE_OTHER)
    if new_password != confirm_password:
        return RedirectResponse("/perfil?error=match", status_code=HTTPStatus.SEE_OTHER)
    if validate_password_strength(new_password):
        return RedirectResponse("/perfil?error=weak", status_code=HTTPStatus.SEE_OTHER)

    update_user_password(user["id"], hash_password(new_password))
    log_activity(
        "password_change",
        username=user["username"],
        email=user["email"],
        ip_identifier=request_ip(request),
        status="exitoso",
        message="Contrasena actualizada correctamente.",
    )
    return RedirectResponse("/perfil?success=1", status_code=HTTPStatus.SEE_OTHER)


@app.get("/recuperar", response_class=HTMLResponse)
def forgot_password_form(request: Request, sent: str = "", error: str = ""):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)

    error_html = '<p class="error">Escribe un correo electronico valido.</p>' if error else ""
    sent_html = (
        '<p class="success">Si el correo existe, enviaremos un codigo de seguridad. Revisa tu bandeja de entrada.</p>'
        if sent
        else ""
    )
    body = f"""
    <section class="panel login">
        <h1>Recuperar contrasena</h1>
        <p>Ingresa tu correo para recibir un codigo temporal de seguridad.</p>
        {error_html}
        {sent_html}
        <form method="post" action="/recuperar">
            <input name="email" type="email" placeholder="Correo electronico" autocomplete="email" required>
            <button type="submit">Enviar codigo</button>
        </form>
        <p><a href="/recuperar/codigo">Ya tengo un codigo</a></p>
        <p><a href="/login">Volver al login</a></p>
    </section>
    """
    return HTMLResponse(layout("Recuperar", body))


@app.post("/recuperar")
def request_password_reset(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    if not EMAIL_PATTERN.match(email):
        return RedirectResponse("/recuperar?error=email", status_code=HTTPStatus.SEE_OTHER)

    user = get_user_by_email(email)
    if user and user["is_active"]:
        code = generate_security_code()
        expires_at = (utc_now() + timedelta(minutes=RESET_CODE_MINUTES)).isoformat()
        create_password_reset_code(user["id"], user["email"], code, expires_at, request_ip(request))
        try:
            email_sent, message = send_security_code(user["email"], code)
        except Exception as error:
            email_sent = False
            message = str(error)

        log_activity(
            "password_reset_request",
            username=user["username"],
            email=user["email"],
            ip_identifier=request_ip(request),
            status="exitoso" if email_sent else "error",
            message=message if email_sent else f"Codigo creado, pero no se pudo enviar correo: {message}",
        )
        if not email_sent:
            print(f"Codigo de recuperacion PrecioMed para {user['email']}: {code}")

    return RedirectResponse("/recuperar?sent=1", status_code=HTTPStatus.SEE_OTHER)


@app.get("/recuperar/codigo", response_class=HTMLResponse)
def reset_code_form(request: Request, email: str = "", error: str = ""):
    error_messages = {
        "invalid": "El codigo no es valido.",
        "expired": "El codigo expiro. Solicita uno nuevo.",
        "used": "Ese codigo ya fue usado. Solicita uno nuevo.",
        "attempts": "Se alcanzo el numero maximo de intentos para este codigo.",
    }
    error_html = f'<p class="error">{error_messages.get(error, "")}</p>' if error else ""
    body = f"""
    <section class="panel login">
        <h1>Codigo de seguridad</h1>
        <p>Escribe el codigo de 6 digitos que recibiste por correo.</p>
        {error_html}
        <form method="post" action="/recuperar/codigo">
            <input name="email" type="email" placeholder="Correo electronico" value="{escape(email)}" autocomplete="email" required>
            <input name="code" inputmode="numeric" placeholder="Codigo de seguridad" maxlength="6" required>
            <button type="submit">Validar codigo</button>
        </form>
        <p><a href="/recuperar">Solicitar otro codigo</a></p>
    </section>
    """
    return HTMLResponse(layout("Codigo", body))


@app.post("/recuperar/codigo")
def validate_reset_code(email: str = Form(...), code: str = Form(...)):
    email = email.strip().lower()
    code = code.strip()
    row = get_password_reset_code(email, code)
    if not row or not CODE_PATTERN.match(code):
        latest_code = get_latest_password_reset_code_by_email(email)
        if latest_code and latest_code["attempts"] < RESET_MAX_ATTEMPTS:
            increment_password_reset_attempt(latest_code["id"])
        return RedirectResponse(
            recovery_url("/recuperar/codigo", error="invalid", email=email),
            status_code=HTTPStatus.SEE_OTHER,
        )
    if row["used"]:
        return RedirectResponse(
            recovery_url("/recuperar/codigo", error="used", email=email),
            status_code=HTTPStatus.SEE_OTHER,
        )
    if row["attempts"] >= RESET_MAX_ATTEMPTS:
        return RedirectResponse(
            recovery_url("/recuperar/codigo", error="attempts", email=email),
            status_code=HTTPStatus.SEE_OTHER,
        )
    if reset_code_expired(row):
        return RedirectResponse(
            recovery_url("/recuperar/codigo", error="expired", email=email),
            status_code=HTTPStatus.SEE_OTHER,
        )

    return RedirectResponse(
        recovery_url("/recuperar/nueva", email=email, code=code),
        status_code=HTTPStatus.SEE_OTHER,
    )


@app.get("/recuperar/nueva", response_class=HTMLResponse)
def new_password_form(request: Request, email: str = "", code: str = "", error: str = "", success: str = ""):
    error_messages = {
        "invalid": "El codigo no es valido o ya no esta disponible.",
        "match": "La nueva contrasena y su confirmacion no coinciden.",
        "weak": "La contrasena debe tener minimo 8 caracteres, una mayuscula, una minuscula y un numero.",
    }
    error_html = f'<p class="error">{error_messages.get(error, "")}</p>' if error else ""
    success_html = '<p class="success">Contrasena actualizada correctamente. Ya puedes iniciar sesion.</p>' if success else ""
    body = f"""
    <section class="panel login">
        <h1>Nueva contrasena</h1>
        {error_html}
        {success_html}
        <form method="post" action="/recuperar/nueva">
            <input name="email" type="hidden" value="{escape(email)}">
            <input name="code" type="hidden" value="{escape(code)}">
            <input name="new_password" type="password" placeholder="Nueva contrasena" autocomplete="new-password" required>
            <input name="confirm_password" type="password" placeholder="Confirmar nueva contrasena" autocomplete="new-password" required>
            <button type="submit">Guardar nueva contrasena</button>
        </form>
        <p><a href="/login">Volver al login</a></p>
    </section>
    """
    return HTMLResponse(layout("Nueva contrasena", body))


@app.post("/recuperar/nueva")
def save_new_password(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    email = email.strip().lower()
    code = code.strip()
    row = get_password_reset_code(email, code)
    target = recovery_url("/recuperar/nueva", email=email, code=code)
    if not row or row["used"] or reset_code_expired(row) or row["attempts"] >= RESET_MAX_ATTEMPTS:
        return RedirectResponse(f"{target}&error=invalid", status_code=HTTPStatus.SEE_OTHER)
    if new_password != confirm_password:
        increment_password_reset_attempt(row["id"])
        return RedirectResponse(f"{target}&error=match", status_code=HTTPStatus.SEE_OTHER)
    if validate_password_strength(new_password):
        increment_password_reset_attempt(row["id"])
        return RedirectResponse(f"{target}&error=weak", status_code=HTTPStatus.SEE_OTHER)

    user = get_user_by_email(email)
    if not user or not user["is_active"]:
        increment_password_reset_attempt(row["id"])
        return RedirectResponse(f"{target}&error=invalid", status_code=HTTPStatus.SEE_OTHER)

    update_user_password(user["id"], hash_password(new_password))
    mark_password_reset_code_used(row["id"])
    log_activity(
        "password_reset_complete",
        username=user["username"],
        email=user["email"],
        ip_identifier=request_ip(request),
        status="exitoso",
        message="Contrasena recuperada correctamente.",
    )
    return RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)


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
