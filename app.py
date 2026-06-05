import hashlib
import hmac
import base64
import json
import os
import re
import secrets
import socket
import smtplib
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http import HTTPStatus
from html import escape
from urllib.parse import urlencode

import bcrypt
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from config import (
    ADMIN_EMAILS,
    EMAIL_FROM,
    EMAIL_PASSWORD,
    EMAIL_USER,
    LOGIN_LOCK_MINUTES,
    MAX_LOGIN_ATTEMPTS,
    MAX_USERS,
    REMEMBER_SESSION_DAYS,
    RESET_CODE_MINUTES,
    RESET_MAX_ATTEMPTS,
    SCRAPER_JOB_TOKEN,
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
    fetch_activity_logs_by_email,
    fetch_app_start_logs,
    fetch_latest_prices,
    fetch_scraper_runs,
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
    update_user_role,
)
from run_scraper import run as run_scraper


APP_NAME = "PrecioMed"
DATA_PROCESSING_VERSION = "ley-1581-2012-v1"
DEFAULT_USERNAME = "admin"
DEFAULT_EMAIL = "admin@preciomed.local"
DEFAULT_FULL_NAME = "Administrador PrecioMed"
ROLE_ADMIN = "admin"
ROLE_CLIENT = "cliente"
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
            ROLE_ADMIN,
        )
        apply_admin_roles()
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
    secret_key = os.environ.get("PRECIOMED_SECRET_KEY")
    if os.environ.get("RENDER") == "true" and not secret_key:
        raise RuntimeError("PRECIOMED_SECRET_KEY debe configurarse en Render.")
    return secret_key or "dev-secret-change-in-render"


def get_admin_username():
    return os.environ.get("PRECIOMED_USERNAME", DEFAULT_USERNAME)


def get_admin_email():
    return os.environ.get("PRECIOMED_ADMIN_EMAIL", DEFAULT_EMAIL).strip().lower()


def configured_admin_emails():
    emails = set(ADMIN_EMAILS)
    emails.add(get_admin_email())
    return {email.strip().lower() for email in emails if email.strip()}


def role_for_email(email):
    return ROLE_ADMIN if email.strip().lower() in configured_admin_emails() else ROLE_CLIENT


def apply_admin_roles():
    for user in fetch_users():
        desired_role = role_for_email(user["email"] or user["username"])
        if user["role"] != desired_role:
            update_user_role(user["id"], desired_role)


def get_password_hash():
    password_hash = os.environ.get("PRECIOMED_PASSWORD_HASH")
    if password_hash:
        return password_hash
    dev_password = os.environ.get("PRECIOMED_DEV_PASSWORD")
    if dev_password and os.environ.get("RENDER") != "true":
        return hash_password(dev_password)
    raise RuntimeError(
        "Configura PRECIOMED_PASSWORD_HASH en produccion o PRECIOMED_DEV_PASSWORD en desarrollo local."
    )


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
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": email,
        "exp": int(expires_at.timestamp()),
    }
    header_text = base64.urlsafe_b64encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    payload_text = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    token_payload = f"{header_text}.{payload_text}"
    signature = hmac.new(
        get_secret_key().encode("utf-8"),
        token_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_text = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{token_payload}.{signature_text}"


def decode_urlsafe_json(value):
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))


def current_username_from_cookie(cookie_value):
    if not cookie_value or cookie_value.count(".") != 2:
        return None
    header_text, payload_text, signature = cookie_value.split(".", 2)
    token_payload = f"{header_text}.{payload_text}"
    expected = hmac.new(
        get_secret_key().encode("utf-8"),
        token_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_text = base64.urlsafe_b64encode(expected).decode("utf-8").rstrip("=")
    if not hmac.compare_digest(signature, expected_text):
        return None
    try:
        payload = decode_urlsafe_json(payload_text)
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(utc_now().timestamp()):
        return None
    email = payload.get("sub", "")

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


def is_admin_user(user):
    return bool(user and user["role"] == ROLE_ADMIN)


def is_authenticated(request):
    return verify_session(request.cookies.get(SESSION_COOKIE))


def require_login(request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)
    return None


def require_admin(request):
    redirect = require_login(request)
    if redirect:
        return redirect
    if not is_admin_user(current_user(request)):
        return RedirectResponse("/?error=forbidden", status_code=HTTPStatus.SEE_OTHER)
    return None


def money(value):
    if value is None:
        return "No detectado"
    return f"${int(value):,}".replace(",", ".")


def discount(value):
    if value is None:
        return "Sin descuento"
    return f"{float(value):.1f}%"


def format_medicine_name(value):
    value = re.sub(r"\s+", " ", (value or "").strip())
    if not value:
        return value
    lowercase_units = {"mg", "ml", "mcg", "ui", "meq", "g"}
    formatted = []
    for word in value.split(" "):
        lower_word = word.lower()
        if lower_word in lowercase_units:
            formatted.append(lower_word)
        elif any(character.isdigit() for character in word):
            formatted.append(word)
        else:
            formatted.append(lower_word[:1].upper() + lower_word[1:])
    return " ".join(formatted)


def pharmacy_count_text(count):
    return f"{count} {'farmacia' if count == 1 else 'farmacias'}"


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


def normalize_search_text(value):
    value = unicodedata.normalize("NFKD", (value or "").strip().lower())
    value = "".join(
        character for character in value if not unicodedata.combining(character)
    )
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    return " ".join(value.split())


def text_matches_search(query, *values):
    if not query:
        return True

    normalized_values = [normalize_search_text(value) for value in values]
    if any(query in value for value in normalized_values):
        return True

    query_tokens = set(re.findall(r"[a-z]+|\d+", query))
    searchable_tokens = set(
        re.findall(r"[a-z]+|\d+", " ".join(normalized_values))
    )
    return bool(query_tokens) and query_tokens <= searchable_tokens


def latest_rows():
    init_db()
    rows = []
    for row in fetch_latest_prices():
        item = dict(row)
        item["display_name"] = format_medicine_name(
            item.get("display_name") or item["search_name"]
        )
        item["product_name"] = format_medicine_name(item["product_name"])
        rows.append(item)
    return rows


def apply_filters(rows, medicine="", pharmacy="", min_price="", max_price=""):
    medicine = normalize_search_text(medicine)
    pharmacy = normalize_search_text(pharmacy)
    min_price_value = parse_price_filter(min_price)
    max_price_value = parse_price_filter(max_price)

    filtered_rows = []
    for row in rows:
        row_price = row["price_cop"] or 0
        row_pharmacy_name = normalize_search_text(row["pharmacy_name"])
        if not text_matches_search(
            medicine,
            row["search_name"],
            row["product_name"],
            row.get("display_name", ""),
        ):
            continue
        if pharmacy and pharmacy != row_pharmacy_name:
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
                "display_name": sorted_items[0].get("display_name") if sorted_items else format_medicine_name(medicine),
                "items": sorted_items,
                "best": best,
                "pharmacy_count": len({item["pharmacy_name"] for item in sorted_items}),
            }
        )

    return sorted(comparisons, key=lambda item: item["medicine"])


def user_initials(user):
    if not user:
        return "PM"
    name = (user["full_name"] or user["email"] or "PM").strip()
    parts = [part for part in re.split(r"\s+", name) if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def layout(title, body, authenticated=False, user=None, active="dashboard"):
    nav_items = []
    if authenticated:
        nav_items.extend(
            [
                ("/", "Dashboard", "dashboard"),
                ("/perfil", "Perfil", "profile"),
            ]
        )
        if is_admin_user(user):
            nav_items.extend(
                [
                    ("/admin", "Panel admin", "admin"),
                    ("/usuarios", "Usuarios", "users"),
                ]
            )
        nav_items.append(("/logout", "Cerrar sesion", "logout"))
    else:
        nav_items.append(("/login", "Ingresar", "login"))

    nav_html = "".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{href}">{label}</a>'
        for href, label, key in nav_items
    )
    user_card = ""
    if authenticated and user:
        role_label = "Administrador" if is_admin_user(user) else "Cliente"
        user_card = f"""
        <div class="user-card">
            <div class="avatar">{escape(user_initials(user))}</div>
            <div>
                <strong>{escape(user["full_name"] or user["email"])}</strong>
                <span>{escape(role_label)}</span>
            </div>
        </div>
        """
    app_shell_class = "app-shell" if authenticated else "public-shell"
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
                --bg: #f7f1ff;
                --surface: #ffffff;
                --surface-soft: #fbf8ff;
                --line: #e4d7f5;
                --text: #241634;
                --muted: #746385;
                --brand: #8b5cf6;
                --brand-dark: #5b21b6;
                --brand-soft: #efe7ff;
                --accent: #a78bfa;
                --warning: #8a5a00;
                --danger: #b4234b;
                --shadow: 0 18px 45px rgba(59, 27, 95, 0.13);
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                background:
                    radial-gradient(circle at top left, rgba(139, 92, 246, 0.18), transparent 34%),
                    linear-gradient(135deg, #f7f1ff 0%, #fbf8ff 48%, #f2ecff 100%);
                color: var(--text);
                font-family: Inter, Segoe UI, Arial, Helvetica, sans-serif;
            }}
            a {{ color: var(--brand-dark); }}
            .app-shell {{
                display: grid;
                grid-template-columns: 260px minmax(0, 1fr);
                min-height: 100vh;
            }}
            .sidebar {{
                background: linear-gradient(180deg, #5b21b6 0%, #7c3aed 100%);
                color: white;
                padding: 24px 18px;
                position: sticky;
                top: 0;
                height: 100vh;
            }}
            .public-shell {{
                min-height: 100vh;
            }}
            .public-header {{
                background: rgba(255,255,255,0.82);
                border-bottom: 1px solid var(--line);
                backdrop-filter: blur(18px);
                padding: 18px 28px;
            }}
            .brand {{
                align-items: center;
                display: flex;
                font-size: 24px;
                font-weight: 800;
                gap: 10px;
                letter-spacing: 0;
            }}
            .brand-mark {{
                align-items: center;
                background: #eadcff;
                border-radius: 14px;
                color: #4c1d95;
                display: inline-flex;
                font-size: 18px;
                font-weight: 900;
                height: 38px;
                justify-content: center;
                width: 38px;
            }}
            .brand small {{
                color: #efe7ff;
                display: block;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0;
                margin-top: 3px;
            }}
            .nav-link {{
                align-items: center;
                border-radius: 8px;
                color: rgba(255,255,255,0.86);
                display: flex;
                font-size: 15px;
                font-weight: 700;
                gap: 10px;
                margin-top: 8px;
                padding: 11px 12px;
                text-decoration: none;
                transition: background .18s ease, transform .18s ease;
            }}
            .nav-link:hover, .nav-link.active {{
                background: rgba(255,255,255,0.15);
                color: white;
                transform: translateX(2px);
            }}
            .user-card {{
                align-items: center;
                background: rgba(255,255,255,0.12);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 12px;
                display: flex;
                gap: 10px;
                margin: 24px 0 18px;
                padding: 12px;
            }}
            .user-card span {{
                color: #eadcff;
                display: block;
                font-size: 12px;
                margin-top: 2px;
            }}
            .avatar {{
                align-items: center;
                background: #f4edff;
                border-radius: 999px;
                color: var(--brand-dark);
                display: inline-flex;
                flex: 0 0 auto;
                font-weight: 900;
                height: 42px;
                justify-content: center;
                width: 42px;
            }}
            main {{
                margin: 0 auto;
                max-width: 1240px;
                padding: 28px;
            }}
            .content {{ width: 100%; }}
            h1 {{ font-size: 34px; margin: 0 0 8px; }}
            h2 {{ font-size: 20px; margin: 28px 0 12px; }}
            p {{ color: var(--muted); line-height: 1.5; }}
            .hero {{
                background:
                    linear-gradient(120deg, rgba(76,29,149,.92), rgba(139,92,246,.82)),
                    url("https://images.unsplash.com/photo-1587854692152-cbe660dbde88?auto=format&fit=crop&w=1400&q=80");
                background-position: center;
                background-size: cover;
                border-radius: 18px;
                box-shadow: var(--shadow);
                color: white;
                margin-bottom: 22px;
                overflow: hidden;
                padding: 34px;
            }}
            .hero p {{ color: rgba(255,255,255,0.86); max-width: 780px; }}
            .hero h1 {{ font-size: 38px; }}
            .panel {{
                background: var(--surface);
                border: 1px solid var(--line);
                border-radius: 12px;
                box-shadow: 0 10px 30px rgba(59, 27, 95, 0.07);
                padding: 20px;
                transition: transform .18s ease, box-shadow .18s ease;
            }}
            .panel:hover {{
                box-shadow: 0 16px 42px rgba(59, 27, 95, 0.11);
                transform: translateY(-1px);
            }}
            .filters {{
                display: grid;
                gap: 12px;
                grid-template-columns: 2fr 1fr 1fr 1fr auto auto;
                margin: 18px 0;
            }}
            input, select, button, .button {{
                border: 1px solid var(--line);
                border-radius: 9px;
                font: inherit;
                min-height: 42px;
                padding: 9px 12px;
            }}
            input:focus, select:focus {{
                border-color: var(--brand);
                box-shadow: 0 0 0 4px rgba(139, 92, 246, .16);
                outline: none;
            }}
            button, .button {{
                background: linear-gradient(135deg, var(--brand), var(--accent));
                border-color: var(--brand);
                color: white;
                cursor: pointer;
                display: inline-flex;
                font-weight: 800;
                justify-content: center;
                align-items: center;
                text-decoration: none;
                white-space: nowrap;
            }}
            .button.secondary {{
                background: white;
                color: var(--brand-dark);
            }}
            table {{
                background: white;
                border-collapse: collapse;
                border-radius: 12px;
                box-shadow: 0 8px 26px rgba(59, 27, 95, 0.07);
                overflow: hidden;
                width: 100%;
            }}
            th, td {{
                border-bottom: 1px solid var(--line);
                padding: 11px;
                text-align: left;
                vertical-align: top;
            }}
            th {{ background: #f0e7ff; color: #4c1d95; font-size: 13px; }}
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
            .summary strong {{ display: block; font-size: 28px; margin-top: 4px; }}
            .best-price-banner {{
                align-items: center;
                background: linear-gradient(135deg, #efe7ff, #f8f4ff);
                border: 1px solid #c4b5fd;
                border-left: 6px solid var(--brand);
                border-radius: 8px;
                display: flex;
                justify-content: space-between;
                gap: 14px;
                margin: 8px 0 14px;
                padding: 14px 16px;
            }}
            .best-price-banner strong {{
                color: var(--brand-dark);
                font-size: 18px;
            }}
            .best-price-banner span {{
                color: #5b4b73;
                font-weight: 700;
                white-space: nowrap;
            }}
            .consent-box {{
                align-items: flex-start;
                display: flex;
                gap: 10px;
                line-height: 1.45;
            }}
            .consent-box input {{
                margin-top: 4px;
                min-height: auto;
                width: auto;
            }}
            .quick-grid {{
                display: grid;
                gap: 14px;
                grid-template-columns: repeat(3, 1fr);
                margin: 18px 0;
            }}
            .section-head {{
                align-items: center;
                display: flex;
                justify-content: space-between;
                gap: 12px;
                margin: 22px 0 12px;
            }}
            .login {{
                margin: 56px auto;
                max-width: 420px;
            }}
            .login form {{ display: grid; gap: 12px; }}
            .back-row {{
                display: flex;
                gap: 10px;
                margin-bottom: 16px;
            }}
            .error {{ color: var(--danger); font-weight: 700; }}
            .success {{ color: #166534; font-weight: 700; }}
            @media (max-width: 900px) {{
                .app-shell {{ grid-template-columns: 1fr; }}
                .sidebar {{ height: auto; position: relative; }}
                .filters, .summary, .quick-grid {{ grid-template-columns: 1fr; }}
                .best-price-banner {{ align-items: flex-start; flex-direction: column; }}
                .best-price-banner span {{ white-space: normal; }}
                main {{ padding: 16px; }}
                .hero {{ padding: 24px; }}
                .hero h1 {{ font-size: 30px; }}
            }}
            @media print {{
                .sidebar, .filters, .actions, .nav-link, .back-row {{ display: none; }}
                body {{ background: white; }}
                main {{ max-width: none; padding: 0; }}
                .panel, table {{ border-color: #999; }}
                a {{ color: black; text-decoration: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="{app_shell_class}">
            {'<aside class="sidebar"><div class="brand"><span class="brand-mark">PM</span><div>PrecioMed<small>Salud, datos y precios claros</small></div></div>' + user_card + '<nav>' + nav_html + '</nav></aside>' if authenticated else '<header class="public-header"><div class="brand"><span class="brand-mark">PM</span><div>PrecioMed</div></div></header>'}
            <main class="content">{body}</main>
        </div>
    </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    medicine: str = "",
    pharmacy: str = "",
    min_price: str = "",
    max_price: str = "",
    error: str = "",
):
    redirect = require_login(request)
    if redirect:
        return redirect

    user = current_user(request)
    rows = latest_rows()
    admin = is_admin_user(user)
    if not admin:
        rows = [row for row in rows if row["product_match_status"] == "ok"]
    filtered_rows = apply_filters(rows, medicine, pharmacy, min_price, max_price)
    comparisons = group_comparisons(filtered_rows)
    pharmacies = sorted({row["pharmacy_name"] for row in rows})
    verified = sum(1 for row in filtered_rows if row["product_match_status"] == "ok")
    user_total = count_users()
    welcome_name = escape((user["full_name"] or user["email"]).split()[0])
    forbidden_html = (
        '<div class="panel error">No tienes permiso para entrar al panel administrativo.</div>'
        if error == "forbidden"
        else ""
    )

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
        <div class="panel">{'Registros' if admin else 'Precios'}<strong>{len(filtered_rows)}</strong></div>
        <div class="panel">Farmacias<strong>{len(pharmacies)}</strong></div>
        <div class="panel">{'Usuarios' if admin else 'Coincidencias'}<strong>{f'{user_total}/{max_users_label()}' if admin else verified}</strong></div>
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
            if admin:
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
            else:
                rows_html.append(
                    f"""
                    <tr>
                        <td>{escape(row["pharmacy_name"])}</td>
                        <td>{escape(row["product_name"])}</td>
                        <td class="price">{money(row["price_cop"])}</td>
                        <td>{money(row["list_price_cop"])}</td>
                        <td>{discount(row["discount_percent"])}</td>
                        <td><a href="{escape(row["product_url"])}" target="_blank">Ver producto</a></td>
                    </tr>
                    """
                )
        admin_headers = """
            <th>Validacion</th>
            <th>Fecha</th>
            <th>Fuente</th>
            <th>Accion</th>
        """
        client_headers = "<th>Fuente</th>"
        sections.append(
            f"""
            <section>
                <h2>{escape(comparison["display_name"])}</h2>
                <div class="best-price-banner">
                    <strong>{best_text}</strong>
                    <span>Disponible en {pharmacy_count_text(comparison["pharmacy_count"])}</span>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Farmacia</th>
                            <th>Medicamento encontrado</th>
                            <th>Precio</th>
                            <th>Precio antes</th>
                            <th>Descuento</th>
                            {admin_headers if admin else client_headers}
                        </tr>
                    </thead>
                    <tbody>{"".join(rows_html)}</tbody>
                </table>
            </section>
            """
        )

    quick_links = f"""
    <section class="quick-grid">
        <a class="panel" href="#buscar"><strong>Buscar medicamento</strong><p>Filtra por nombre, farmacia y rango de precio.</p></a>
        <a class="panel" href="/perfil"><strong>Mi perfil</strong><p>Edita tu seguridad y revisa tus accesos recientes.</p></a>
        {'<a class="panel" href="/admin"><strong>Panel admin</strong><p>Usuarios, logs, seguridad y datos del sistema.</p></a>' if admin else '<a class="panel" href="#comparaciones"><strong>Comparar precios</strong><p>Encuentra la farmacia con mejor valor disponible.</p></a>'}
    </section>
    """

    body = f"""
    <section class="hero">
        <h1>Hola, {welcome_name}. Compara medicamentos con claridad.</h1>
        <p>Busca productos, revisa farmacias y encuentra el mejor precio publicado con comparaciones claras y consistentes.</p>
    </section>
    {forbidden_html}
    <div class="actions">
        {'<a class="button" href="/actualizar">Actualizar precios</a>' if admin else ''}
        <button onclick="window.print()">Imprimir vista</button>
    </div>
    {quick_links}
    <div id="buscar"></div>
    {filters}
    {summary}
    <div id="comparaciones"></div>
    {"".join(sections) if sections else '<div class="panel">No hay resultados con esos filtros.</div>'}
    """
    return HTMLResponse(layout("Dashboard", body, authenticated=True, user=user, active="dashboard"))


@app.head("/")
def home_head():
    return Response(status_code=HTTPStatus.OK)


@app.get("/tratamiento-datos", response_class=HTMLResponse)
def data_processing_policy(request: Request):
    user = current_user(request)
    body = """
    <section class="panel">
        <h1>Tratamiento de datos personales</h1>
        <p>PrecioMed trata datos personales de usuarios registrados para crear y administrar cuentas, autenticar accesos, proteger la seguridad de la plataforma, gestionar recuperacion de contrasena y prestar el servicio de comparacion de precios.</p>
        <p>La autorizacion se solicita conforme a la Ley 1581 de 2012 de Colombia y sus normas reglamentarias sobre proteccion de datos personales. El titular puede conocer, actualizar, rectificar o solicitar la eliminacion de sus datos cuando legalmente proceda.</p>
        <p>Los datos sensibles no se publican en vistas de cliente. La informacion administrativa, logs, fechas, acciones y validaciones queda restringida a usuarios administradores.</p>
        <p>PrecioMed no debe almacenar claves, tokens ni credenciales en el repositorio ni en el frontend. Las credenciales operativas deben configurarse como variables de entorno del despliegue.</p>
    </section>
    """
    if user:
        return HTMLResponse(
            layout(
                "Tratamiento de datos",
                body,
                authenticated=True,
                user=user,
                active="profile",
            )
        )
    return HTMLResponse(layout("Tratamiento de datos", body))


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
        "max": "Se alcanzo el numero maximo de usuarios permitidos.",
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
            <label class="consent-box muted">
                <input name="data_processing_consent" type="checkbox" value="1" required>
                <span>Autorizo a PrecioMed el tratamiento de mis datos personales para crear y administrar mi cuenta, gestionar seguridad y prestar el servicio, conforme a la Ley 1581 de 2012 de Colombia y la <a href="/tratamiento-datos" target="_blank">politica de tratamiento de datos personales</a>.</span>
            </label>
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
    data_processing_consent: str = Form(""),
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
    if data_processing_consent != "1":
        return RedirectResponse("/registro?error=consent", status_code=HTTPStatus.SEE_OTHER)

    role = role_for_email(email)
    create_user(
        username,
        full_name,
        email,
        hash_password(password),
        role,
        data_processing_consent_at=utc_now().isoformat(),
        data_processing_consent_version=DATA_PROCESSING_VERSION,
    )
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
    activity_rows = fetch_activity_logs_by_email(user["email"])
    activity_html = "".join(
        f"""
        <tr>
            <td>{escape(row["created_at"][:19])}</td>
            <td>{escape(row["event_type"])}</td>
            <td>{escape(row["status"])}</td>
            <td>{escape(row["message"] or "")}</td>
        </tr>
        """
        for row in activity_rows
    )
    body = f"""
    <div class="back-row"><a class="button secondary" href="/">Volver al Dashboard</a></div>
    <h1>Perfil de usuario</h1>
    <section class="panel">
        <h2>Datos de la cuenta</h2>
        <p><strong>Nombre:</strong> {escape(user["full_name"] or "")}</p>
        <p><strong>Correo:</strong> {escape(user["email"] or "")}</p>
        <p><strong>Rol:</strong> {escape('Administrador' if is_admin_user(user) else 'Cliente')}</p>
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
    <section>
        <h2>Mi actividad reciente</h2>
        <table>
            <thead><tr><th>Fecha</th><th>Evento</th><th>Estado</th><th>Mensaje</th></tr></thead>
            <tbody>{activity_html or '<tr><td colspan="4">Sin actividad reciente.</td></tr>'}</tbody>
        </table>
    </section>
    """
    return HTMLResponse(layout("Perfil", body, authenticated=True, user=user, active="profile"))


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
        "consent": "Debes aceptar la autorizacion de tratamiento de datos personales para registrarte.",
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
    redirect = require_admin(request)
    if redirect:
        return redirect

    user = current_user(request)
    user_rows = fetch_users()
    log_rows = fetch_activity_logs()

    users_html = []
    for account in user_rows:
        status = "Activo" if account["is_active"] else "Inactivo"
        users_html.append(
            f"""
            <tr>
                <td>{escape(account["full_name"] or "")}</td>
                <td>{escape(account["username"])}</td>
                <td>{escape(account["email"] or "")}</td>
                <td>{escape(account["role"])}</td>
                <td>{status}</td>
                <td>{escape(account["created_at"][:19])}</td>
                <td>{escape((account["last_login_at"] or "")[:19])}</td>
                <td>{escape((account["data_processing_consent_at"] or "")[:19])}</td>
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
                    <th>Rol</th>
                    <th>Estado</th>
                    <th>Creado</th>
                    <th>Ultimo ingreso</th>
                    <th>Consentimiento datos</th>
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
    return HTMLResponse(layout("Usuarios", body, authenticated=True, user=user, active="users"))


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    redirect = require_admin(request)
    if redirect:
        return redirect

    user = current_user(request)
    rows = latest_rows()
    user_rows = fetch_users()
    log_rows = fetch_activity_logs(12)
    scraper_rows = fetch_scraper_runs(8)
    admin_total = sum(1 for item in user_rows if item["role"] == ROLE_ADMIN)
    client_total = sum(1 for item in user_rows if item["role"] == ROLE_CLIENT)
    pharmacies = sorted({row["pharmacy_name"] for row in rows})
    medicines = sorted({row["search_name"] for row in rows})

    log_html = "".join(
        f"""
        <tr>
            <td>{escape(row["created_at"][:19])}</td>
            <td>{escape(row["event_type"])}</td>
            <td>{escape(row["email"] or "")}</td>
            <td>{escape(row["status"])}</td>
            <td>{escape(row["message"] or "")}</td>
        </tr>
        """
        for row in log_rows
    )
    medicine_html = "".join(f"<li>{escape(item)}</li>" for item in medicines[:12])
    pharmacy_html = "".join(f"<li>{escape(item)}</li>" for item in pharmacies)
    scraper_html = "".join(
        f"""
        <tr>
            <td>{escape(row["started_at"][:19])}</td>
            <td>{escape((row["finished_at"] or "")[:19])}</td>
            <td>{escape(row["status"])}</td>
            <td>{escape(row["source"] or "")}</td>
            <td>{row["items_saved"]}</td>
            <td>{escape(row["error_message"] or "")}</td>
        </tr>
        """
        for row in scraper_rows
    )

    body = f"""
    <div class="back-row"><a class="button secondary" href="/">Volver al Dashboard</a></div>
    <section class="hero">
        <h1>Panel administrativo</h1>
        <p>Controla usuarios, actividad, seguridad, medicamentos y farmacias sin exponer informacion administrativa a clientes.</p>
    </section>
    <section class="summary">
        <div class="panel">Usuarios activos<strong>{count_users()}</strong></div>
        <div class="panel">Administradores<strong>{admin_total}</strong></div>
        <div class="panel">Clientes<strong>{client_total}</strong></div>
        <div class="panel">Farmacias<strong>{len(pharmacies)}</strong></div>
    </section>
    <section class="quick-grid">
        <a class="panel" href="/usuarios"><strong>Usuarios y logs</strong><p>Ver registros, inicios de sesion y actividad.</p></a>
        <a class="panel" href="/actualizar"><strong>Actualizar precios</strong><p>Ejecutar scraper y refrescar comparaciones.</p></a>
        <a class="panel" href="/"><strong>Vista de precios</strong><p>Revisar dashboard principal de medicamentos.</p></a>
    </section>
    <section class="quick-grid">
        <div class="panel"><h2>Medicamentos</h2><ul>{medicine_html or '<li>Sin datos.</li>'}</ul></div>
        <div class="panel"><h2>Farmacias</h2><ul>{pharmacy_html or '<li>Sin datos.</li>'}</ul></div>
        <div class="panel"><h2>Seguridad</h2><p>Roles activos: admin y cliente. Los clientes no pueden entrar a este panel ni a usuarios.</p></div>
    </section>
    <section>
        <div class="section-head">
            <h2>Scraping</h2>
            <a class="button secondary" href="/actualizar">Ejecutar ahora</a>
        </div>
        <table>
            <thead><tr><th>Inicio</th><th>Fin</th><th>Estado</th><th>Origen</th><th>Guardados</th><th>Error</th></tr></thead>
            <tbody>{scraper_html or '<tr><td colspan="6">Sin ejecuciones registradas.</td></tr>'}</tbody>
        </table>
    </section>
    <section>
        <div class="section-head">
            <h2>Actividad reciente</h2>
            <a class="button secondary" href="/usuarios">Ver todo</a>
        </div>
        <table>
            <thead><tr><th>Fecha</th><th>Evento</th><th>Correo</th><th>Estado</th><th>Mensaje</th></tr></thead>
            <tbody>{log_html or '<tr><td colspan="5">Sin actividad reciente.</td></tr>'}</tbody>
        </table>
    </section>
    """
    return HTMLResponse(layout("Admin", body, authenticated=True, user=user, active="admin"))


@app.get("/actualizar")
def actualizar(request: Request):
    redirect = require_admin(request)
    if redirect:
        return redirect
    run_scraper()
    return RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)


def valid_scraper_job_token(token):
    return bool(SCRAPER_JOB_TOKEN) and hmac.compare_digest(token or "", SCRAPER_JOB_TOKEN)


@app.get("/cron/actualizar-precios")
def scheduled_price_update(token: str = ""):
    if not valid_scraper_job_token(token):
        return Response("Endpoint protegido.", status_code=HTTPStatus.FORBIDDEN)
    run_scraper(source="render-cron")
    return {"status": "ok"}


@app.post("/cron/actualizar-precios")
def scheduled_price_update_post(background_tasks: BackgroundTasks, token: str = ""):
    if not valid_scraper_job_token(token):
        return Response("Endpoint protegido.", status_code=HTTPStatus.FORBIDDEN)
    background_tasks.add_task(run_scraper, "render-cron")
    return {"status": "queued"}


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
