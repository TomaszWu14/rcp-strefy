"""
TIMER – Flask app v3
Zmiany:
 - Usunięto Strefę KONIEC z KPI i widoków
 - Zgłoszenia: strefa źródłowa → strefa docelowa + akceptacja przez kierownika
 - Auto-reload danych z parquet (sprawdza mtime co request)
 - Rola lider widzi swój dział
 - Baza userów z pliku Excel/JSON (gotowa do podpięcia SharePoint)
"""
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import json, uuid, os, io, secrets

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    # Fail-fast poza trybem deweloperskim; w dev (FLASK_DEBUG=1) klucz losowy — sesje giną po restarcie.
    if os.environ.get("FLASK_DEBUG") != "1":
        raise RuntimeError("Brak FLASK_SECRET_KEY (zob. .env.example). Do lokalnego demo: FLASK_DEBUG=1.")
    app.secret_key = secrets.token_hex(32)

# Publiczne demo: jawne konta demo, więc bez ustawień SMTP i bez wysyłki poczty z serwera.
DEMO_MODE = os.environ.get("DEMO_MODE") == "1"

DATA_DIR    = Path(__file__).parent / "data"
_P1 = Path(__file__).parent / "czasy_calc.parquet"
_P2 = Path(__file__).parent / "data" / "czasy_calc.parquet"
PARQUET = _P1 if _P1.exists() else _P2
USERS_FILE   = DATA_DIR / "users.json"
ZGLOS_FILE   = DATA_DIR / "zgloszenia.json"
PODSTR_FILE  = DATA_DIR / "podstrefy.json"
GRAFIK_FILE  = DATA_DIR / "grafik.json"
SLOWNIK_FILE = DATA_DIR / "slowniki.json"
SMTP_FILE    = DATA_DIR / "smtp_config.json"
KOREKTY_FILE = DATA_DIR / "korekty.json"
DATA_DIR.mkdir(exist_ok=True)

# Strefa KONIEC wykluczona z analiz
STREFY_ROBOCZE = [
    "STREFA_PICKING","STREFA_PRZYJĘCIA","STREFA_PRZEWOZNIK_A","STREFA_PRZEWOZNIK_B",
    "STREFA_BUS","STREFA_EXPORT","STREFA_INV","STREFA_ZWROTY",
    "STREFA_INNE","STREFA_KONTENERY","STREFA_REO","STREFA_KLIENT_A",
    "STREFA_ADMIN_MAG","STREFA_SZKOLENIE","STREFA_ODDZIAŁY",
    "STREFA_ODDZIAŁ_KPL","STREFA_ODDZIAŁ_PAK","STREFA_KLIENT_B",
    "STREFA_ZERO","STREFA_REKLAMACJE","STREFA_KP_ELEKTRYK",
    "STREFA_KP_PALECIAK","STREFA_PRZERWA","STREFA_UKRAINA","STREFA_KLIENT_C",
]
PODSTREFY = [
    "STREFA_Przekładanie_palet","STREFA_Oklejanie_kartonów(INB)",
    "STREFA_Brak_zleceń_w_pickingu","STREFA_Foliowanie_palet",
    "STREFA_Przepakowania_kartonów","STREFA_Klient_D",
    "STREFA_Generowanie_zleceń","STREFA_Strefa_0051",
    "STREFA_Przyjęcie_kontenerów","STREFA_Sprzątanie",
    "STREFA_Oklejanie_kartonów(EXP)","STREFA_Awaria_systemu",
    "STREFA_Błąd_procesu","STREFA_Foliowanie",
]
DZIALY = [
    "Dział_Kompletacji","Dział_Wysyłek_B","Dział_Wysyłek_A",
    "Dział_Wysyłek_Bus","Dział_Eksportu","Dział_Przyjęć",
    "Dział_Przyjęć_Kontenerowych","Dział_Inwentaryzacja","Dział_Zwrotów",
    "Dział_Reklamacji","Dział_Reorganizacji_Magazynu","Dział_Dystrybucji_Oddziały",
    "Dział_Administracji","Dział_Pomocniczy(Inne)",
]

RESOURCE_GROUPS = ["ALL", "INBOUND", "OUTBOUND", "PICKING", "LOGISTYKA", "ADMINISTRACJA"]

PERMISSION_LABELS = {
    "view_all_workers":    "Widok wszystkich pracowników",
    "approve_reports":     "Akceptacja zgłoszeń",
    "export_data":         "Eksport danych CSV",
    "manage_users":        "Zarządzanie użytkownikami",
    "manage_dictionaries": "Zarządzanie słownikami",
    "manage_settings":     "Ustawienia systemu",
    "view_kpi":            "Dostęp do KPI",
    "view_schedule":       "Dostęp do grafiku",
    "manage_subzones":     "Zarządzanie podstrefami",
}

DEFAULT_PERMISSIONS = {
    "kierownik": {k: True for k in PERMISSION_LABELS},
    "super_user": {
        "view_all_workers":    True,
        "approve_reports":     True,
        "export_data":         True,
        "manage_users":        False,
        "manage_dictionaries": False,
        "manage_settings":     False,
        "view_kpi":            True,
        "view_schedule":       True,
        "manage_subzones":     True,
    },
    "lider": {
        "view_all_workers":    False,
        "approve_reports":     False,
        "export_data":         True,
        "manage_users":        False,
        "manage_dictionaries": False,
        "manage_settings":     False,
        "view_kpi":            True,
        "view_schedule":       True,
        "manage_subzones":     True,
    },
}


STREFA_COLORS = {
    "STREFA_PICKING":     "#185FA5",
    "STREFA_PRZYJĘCIA":   "#2E75B6",
    "STREFA_PRZEWOZNIK_A":         "#4ade80",
    "STREFA_PRZEWOZNIK_B":        "#f59e0b",
    "STREFA_BUS":         "#ef4444",
    "STREFA_EXPORT":      "#a78bfa",
    "STREFA_INV":         "#f472b6",
    "STREFA_ZWROTY":      "#34d399",
    "STREFA_INNE":        "#fb923c",
    "STREFA_KONTENERY":   "#60a5fa",
    "STREFA_REO":         "#e879f9",
    "STREFA_KLIENT_A":     "#facc15",
    "STREFA_ADMIN_MAG":   "#94a3b8",
    "STREFA_SZKOLENIE":   "#f87171",
    "STREFA_ODDZIAŁY":    "#86efac",
    "STREFA_ODDZIAŁ_KPL": "#fcd34d",
    "STREFA_ODDZIAŁ_PAK": "#c4b5fd",
    "STREFA_KLIENT_B":     "#6ee7b7",
    "STREFA_ZERO":        "#fda4af",
    "STREFA_REKLAMACJE":  "#a5f3fc",
    "STREFA_KP_ELEKTRYK": "#d9f99d",
    "STREFA_KP_PALECIAK": "#fef08a",
    "STREFA_PRZERWA":     "#fbcfe8",
    "STREFA_UKRAINA":     "#e2e8f0",
    "STREFA_KLIENT_C":        "#bfdbfe",
}

# ── Helpers email i słowniki ─────────────────────────────────────────────────
def load_smtp():
    return load_json(SMTP_FILE, {
        "server": "smtp.example.com", "port": 587,
        "user": "", "password": "", "from": "",
        "kierownicy_email": [], "enabled": False
    })

def send_email_alert(subject, body):
    """Wyślij email do kierowników — działa tylko jeśli SMTP skonfigurowane."""
    cfg = load_smtp()
    if DEMO_MODE or not cfg.get("enabled") or not cfg.get("user"):
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[TIMER] {subject}"
        msg["From"]    = cfg["from"] or cfg["user"]
        msg["To"]      = ", ".join(cfg["kierownicy_email"])
        with smtplib.SMTP(cfg["server"], cfg["port"]) as s:
            s.starttls()
            s.login(cfg["user"], cfg["password"])
            s.sendmail(msg["From"], cfg["kierownicy_email"], msg.as_string())
        return True
    except Exception as e:
        print(f"[Email] Błąd: {e}")
        return False

def load_slowniki():
    default = {
        "strefy": [
            "STREFA_PICKING","STREFA_PRZYJĘCIA","STREFA_PRZEWOZNIK_A","STREFA_PRZEWOZNIK_B",
            "STREFA_BUS","STREFA_EXPORT","STREFA_INV","STREFA_ZWROTY",
            "STREFA_INNE","STREFA_KONTENERY","STREFA_REO","STREFA_KLIENT_A",
            "STREFA_ADMIN_MAG","STREFA_SZKOLENIE","STREFA_ODDZIAŁY",
            "STREFA_ODDZIAŁ_KPL","STREFA_ODDZIAŁ_PAK","STREFA_KLIENT_B",
            "STREFA_ZERO","STREFA_REKLAMACJE","STREFA_KP_ELEKTRYK",
            "STREFA_KP_PALECIAK","STREFA_PRZERWA","STREFA_UKRAINA","STREFA_KLIENT_C",
        ],
        "podstrefy": [
            "STREFA_Przekładanie_palet","STREFA_Oklejanie_kartonów(INB)",
            "STREFA_Brak_zleceń_w_pickingu","STREFA_Foliowanie_palet",
            "STREFA_Przepakowania_kartonów","STREFA_Klient_D",
            "STREFA_Generowanie_zleceń","STREFA_Strefa_0051",
            "STREFA_Przyjęcie_kontenerów","STREFA_Sprzątanie",
            "STREFA_Oklejanie_kartonów(EXP)","STREFA_Awaria_systemu",
            "STREFA_Błąd_procesu","STREFA_Foliowanie",
        ]
    }
    return load_json(SLOWNIK_FILE, default)

def get_strefy():
    return load_slowniki()["strefy"]

def get_podstrefy():
    return load_slowniki()["podstrefy"]

# ── Cache danych ──────────────────────────────────────────────────────────────
_df_cache = {"df": None, "mtime": 0}

def load_df():
    if not PARQUET.exists():
        return pd.DataFrame()
    mtime = PARQUET.stat().st_mtime
    if _df_cache["mtime"] != mtime:
        df = pd.read_parquet(PARQUET)
        df["data"] = pd.to_datetime(df["data"])
        df = df[df["strefa_docelowa"] != "STREFA_KONIEC"]
        _df_cache["df"] = df
        _df_cache["mtime"] = mtime
    base = _df_cache["df"]
    return apply_corrections(base)

# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

def load_users():
    return load_json(USERS_FILE, {})

def random_password():
    """Losowe hasło jednorazowe (do przekazania użytkownikowi i zmiany w „Moje konto”)."""
    return secrets.token_urlsafe(9)

def ensure_admin():
    """Pierwszy start bez data/users.json: zakłada konto admin z losowym hasłem, wypisanym raz w konsoli."""
    if USERS_FILE.exists():
        return
    haslo = random_password()
    DATA_DIR.mkdir(exist_ok=True)
    save_json(USERS_FILE, {"admin": {
        "password": generate_password_hash(haslo), "role": "kierownik", "name": "Administrator",
        "hu": "", "dzial": "", "resource_group": "ALL", "aktualny": True}})
    print(f"  Utworzono konto: admin / {haslo}  (zapisz je — nie zostanie pokazane ponownie)")

def hms_to_s(hms):
    """HH:MM:SS → sekundy."""
    try:
        parts = str(hms).split(":")
        return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
    except Exception:
        return 0

def s_to_hms(s):
    s = max(0, int(s))
    return f"{s//3600:02}:{(s%3600)//60:02}:{s%60:02}"

def _save_correction(z):
    """Tworzy rekord korekty danych na podstawie zatwierdzonego zgłoszenia."""
    typ = z.get("typ_problemu", "")
    df  = load_df()
    # Znajdź HU pracownika
    users_map = load_users()
    pracownik_name = z.get("pracownik", "")
    hu = ""
    for v in users_map.values():
        if v.get("name","").upper() == pracownik_name.upper() or v.get("hu","").endswith(pracownik_name.upper().replace(" ","_")):
            hu = v.get("hu","")
            break
    if not hu and not df.empty:
        match = df[df["pracownik"] == pracownik_name]
        if not match.empty:
            hu = match["hu"].iloc[0]

    korekta = {
        "id":            str(uuid.uuid4())[:8],
        "zgloszenie_id": z.get("id",""),
        "timestamp":     datetime.now().isoformat(),
        "pracownik":     pracownik_name,
        "hu":            hu,
        "data":          z.get("data_pracy",""),
        "typ":           typ,
        "strefa_minus":  "",
        "czas_minus_s":  0,
        "strefa_plus":   "",
        "czas_plus_s":   0,
        "opis":          z.get("opis",""),
        "akceptowal":    z.get("akceptowal_name",""),
    }

    czas_s = hms_to_s(z.get("czas_korekty","00:00:00"))

    if typ == "bledna_strefa":
        korekta["strefa_minus"] = z.get("strefa_z","")
        korekta["czas_minus_s"] = czas_s
        korekta["strefa_plus"]  = z.get("strefa_do","")
        korekta["czas_plus_s"]  = czas_s
    elif typ == "brak_odbicia":
        korekta["strefa_plus"]  = z.get("strefa_brak","")
        korekta["czas_plus_s"]  = hms_to_s(
            f"{z.get('godz_wejscia','00:00')}:00"
        )  # przybliżone — czas od wejścia do wyjścia
        wej = z.get("godz_wejscia","00:00")
        wyj = z.get("godz_wyjscia","00:00")
        try:
            h1,m1 = map(int, wej.split(":"))
            h2,m2 = map(int, wyj.split(":"))
            korekta["czas_plus_s"] = max(0, (h2*60+m2 - h1*60-m1)*60)
        except Exception:
            korekta["czas_plus_s"] = czas_s
    elif typ == "nadmiar_czasu":
        korekta["strefa_minus"] = z.get("strefa_nadmiar","")
        korekta["czas_minus_s"] = czas_s
    elif typ == "brak_czasu":
        korekta["strefa_plus"]  = z.get("strefa_brak","")
        korekta["czas_plus_s"]  = czas_s

    korekty = load_json(KOREKTY_FILE, [])
    korekty.insert(0, korekta)
    save_json(KOREKTY_FILE, korekty)

def apply_corrections(df):
    """Nakłada zatwierdzone korekty jako syntetyczne wiersze na DataFrame."""
    korekty = load_json(KOREKTY_FILE, [])
    if not korekty or df.empty:
        return df
    rows = []
    for k in korekty:
        hu   = k.get("hu","")
        data = k.get("data","")
        if not hu or not data:
            continue
        match = df[(df["hu"]==hu) & (df["data"].dt.strftime("%Y-%m-%d")==data)]
        pracownik = match["pracownik"].iloc[0] if not match.empty else k.get("pracownik","")
        ts = pd.to_datetime(data) if data else pd.NaT
        if k.get("czas_minus_s",0) > 0 and k.get("strefa_minus"):
            rows.append({"hu":hu,"pracownik":pracownik,"data":ts,
                         "strefa_docelowa":k["strefa_minus"],
                         "czas_s":-int(k["czas_minus_s"]),"czas_h":-k["czas_minus_s"]/3600,
                         "dt":pd.NaT,"dt_exit":pd.NaT})
        if k.get("czas_plus_s",0) > 0 and k.get("strefa_plus"):
            rows.append({"hu":hu,"pracownik":pracownik,"data":ts,
                         "strefa_docelowa":k["strefa_plus"],
                         "czas_s":int(k["czas_plus_s"]),"czas_h":k["czas_plus_s"]/3600,
                         "dt":pd.NaT,"dt_exit":pd.NaT})
    if rows:
        corr_df = pd.DataFrame(rows)
        df = pd.concat([df, corr_df], ignore_index=True)
    return df

def hash_password(plain):
    return generate_password_hash(plain)

def verify_password(stored, plain):
    """Obsługuje stare plaintext (migracja) i nowe hasze werkzeug."""
    if stored and stored.startswith("pbkdf2:") or (stored and stored.startswith("scrypt:")):
        return check_password_hash(stored, plain)
    return stored == plain  # plaintext fallback — zamień przy kolejnym logowaniu

def migrate_password_if_needed(login_, stored, plain):
    """Przy udanym logowaniu z plaintextem — hashuje od razu."""
    if stored and not (stored.startswith("pbkdf2:") or stored.startswith("scrypt:")):
        users = load_users()
        users[login_]["password"] = hash_password(plain)
        save_json(USERS_FILE, users)

# ── Session / role helpers ────────────────────────────────────────────────────
def current_user():
    return session.get("user")

def get_role():
    u = current_user()
    if not u:
        return None
    return load_users().get(u, {}).get("role", "lider")

def is_kierownik():          return get_role() == "kierownik"
def is_super_user():         return get_role() == "super_user"
def is_lider():              return get_role() == "lider"
def is_kierownik_or_lider(): return get_role() in ("kierownik", "lider")
def is_admin_or_super():     return get_role() in ("kierownik", "super_user")

def get_user_permissions(username=None):
    if username is None:
        username = current_user()
    users = load_users()
    u = users.get(username or "", {})
    role = u.get("role", "pracownik")
    perms = DEFAULT_PERMISSIONS.get(role, {k: False for k in PERMISSION_LABELS}).copy()
    perms.update(u.get("permissions", {}))
    return perms

def has_permission(perm):
    return get_user_permissions().get(perm, False)

def user_info():
    u = current_user()
    return load_users().get(u, {}) if u else {}

def get_team_hus():
    """HU widoczne dla bieżącego użytkownika."""
    users = load_users()
    u = current_user()
    if not u:
        return []
    info = users.get(u, {})
    role = info.get("role", "lider")
    if role in ("kierownik", "super_user"):
        return [v["hu"] for v in users.values() if v.get("hu")]
    if role == "lider":
        rg    = info.get("resource_group", "")
        dzial = info.get("dzial", "")
        if rg and rg != "ALL":
            return [v["hu"] for v in users.values()
                    if v.get("resource_group") == rg and v.get("hu") and v.get("aktualny", True)]
        if dzial:
            return [v["hu"] for v in users.values()
                    if v.get("dzial") == dzial and v.get("hu") and v.get("aktualny", True)]
        return []
    return [info["hu"]] if info.get("hu") else []

FULL_ACCESS_ROLES = ("kierownik", "super_user")

def scope_df(df):
    """Odcinki widoczne dla bieżącego użytkownika: pełny wgląd tylko kierownik/super_user."""
    if get_role() in FULL_ACCESS_ROLES:
        return df
    return df[df["hu"].isin(get_team_hus())]

def pending_notifications():
    """Liczba zgłoszeń oczekujących na akceptację widocznych dla bieżącego użytkownika."""
    if not has_permission("approve_reports"):
        return 0
    lst = load_json(ZGLOS_FILE, [])
    return sum(1 for z in lst if z.get("status") == "nowe")

def _nav():
    perms = get_user_permissions()
    return {
        "current_user":          current_user(),
        "is_kierownik":          is_kierownik(),
        "is_super_user":         is_super_user(),
        "is_lider":              is_lider(),
        "is_kierownik_or_lider": is_kierownik_or_lider(),
        "is_admin_or_super":     is_admin_or_super(),
        "user_info":             user_info(),
        "get_role":              get_role(),
        "STREFA_COLORS":         STREFA_COLORS,
        "NAV_STREFY":            get_strefy(),
        "NAV_PODSTREFY":         get_podstrefy(),
        "perms":                 perms,
        "pending_notif":         pending_notifications(),
    }

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper

# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        users = load_users()
        u = users.get(username)
        if u and verify_password(u.get("password", ""), password):
            if not u.get("aktualny", True):
                flash("Konto nieaktywne — skontaktuj się z administratorem.", "error")
            else:
                migrate_password_if_needed(username, u.get("password", ""), password)
                session["user"] = username
                return redirect(url_for("dashboard"))
        else:
            flash("Nieprawidłowy login lub hasło.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ══════════════════════════════════════════════════════════════════════════════
# KPI
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/kpi")
@login_required
def kpi():
    df = load_df()
    if df.empty:
        return render_template("kpi.html", error=True, strefy_all=STREFY_ROBOCZE, **_nav())

    ui = user_info(); role = get_role()
    last = df["data"].max()
    data_od  = request.args.get("data_od", last.replace(day=1).strftime("%Y-%m-%d"))
    data_do  = request.args.get("data_do", last.strftime("%Y-%m-%d"))
    strefy_f = request.args.getlist("strefy")
    pracownik_f = request.args.get("pracownik","")

    lider_f = request.args.get("lider_f", "")
    users_all = load_users()
    liderzy = sorted(
        [{"login": k, "name": v.get("name", k)} for k, v in users_all.items() if v.get("role") == "lider"],
        key=lambda x: x["name"]
    )

    if role not in FULL_ACCESS_ROLES:
        df = scope_df(df)
        pracownicy = sorted(df["pracownik"].unique().tolist())
    else:
        # admin/super_user mogą filtrować po liderze
        if lider_f and lider_f in users_all:
            lider_info = users_all[lider_f]
            lider_role = lider_info.get("role", "")
            if lider_role == "lider":
                lider_dzial = lider_info.get("dzial", "")
                lider_rg    = lider_info.get("resource_group", "")
                if lider_rg and lider_rg != "ALL":
                    team_hus = [v["hu"] for v in users_all.values()
                                if v.get("resource_group") == lider_rg and v.get("hu")]
                elif lider_dzial:
                    team_hus = [v["hu"] for v in users_all.values()
                                if v.get("dzial") == lider_dzial and v.get("hu")]
                else:
                    team_hus = []
                df = df[df["hu"].isin(team_hus)]
        pracownicy = sorted(df["pracownik"].unique().tolist())

    if pracownik_f:
        df = df[df["pracownik"] == pracownik_f]
    if data_od:
        df = df[df["data"] >= pd.to_datetime(data_od)]
    if data_do:
        df = df[df["data"] <= pd.to_datetime(data_do)]

    strefy_all = sorted(df["strefa_docelowa"].unique().tolist()) if not df.empty else STREFY_ROBOCZE
    if strefy_f:
        df = df[df["strefa_docelowa"].isin(strefy_f)]

    if df.empty:
        return render_template("kpi.html", error=False, kpi_data=[], total_hms="00:00:00",
            pivot_cols=[], col_totals={}, data_od=data_od, data_do=data_do,
            strefy_f=strefy_f, strefy_all=strefy_all, pracownicy=pracownicy,
            pracownik_f=pracownik_f, liderzy=liderzy, lider_f=lider_f,
            miesiac_b="", miesiac_b_data=[], chart_labels="[]", chart_datasets="[]", **_nav())

    # Suma per strefa (totals)
    suma = df.groupby("strefa_docelowa")["czas_s"].sum().reset_index()
    suma["czas_hms"] = suma["czas_s"].apply(s_to_hms)
    suma["czas_h"]   = (suma["czas_s"]/3600).round(2)
    suma = suma.sort_values("czas_s", ascending=False)

    # Pivot: strefa × miesiąc
    df["miesiac"] = df["data"].dt.to_period("M").astype(str)
    pivot = df.groupby(["strefa_docelowa","miesiac"])["czas_s"].sum().unstack(fill_value=0)
    pivot_cols = sorted(pivot.columns.tolist())

    # Totale per kolumna
    col_totals = {col: s_to_hms(int(pivot[col].sum())) for col in pivot_cols}

    kpi_data = []
    for _, row in suma.iterrows():
        strefa = row["strefa_docelowa"]
        prow   = pivot.loc[strefa] if strefa in pivot.index else {}
        kpi_data.append({
            "strefa_docelowa": strefa,
            "czas_hms":        row["czas_hms"],
            "czas_h":          row["czas_h"],
            "czas_s":          int(row["czas_s"]),
            "color":           STREFA_COLORS.get(strefa, "#94a3b8"),
            "pivot":           {col: s_to_hms(int(prow.get(col,0))) for col in pivot_cols},
        })

    total_s = int(df["czas_s"].sum())

    # Wykres dzienny per strefa - top 10 stref wg sumy
    df["dzien"] = df["data"].dt.strftime("%Y-%m-%d")
    pv2 = df.groupby(["dzien","strefa_docelowa"])["czas_s"].sum().unstack(fill_value=0).reset_index()
    labels = pv2["dzien"].tolist()
    # Top 10 stref wg łącznego czasu
    strefa_cols = [c for c in pv2.columns if c != "dzien"]
    top10 = sorted(strefa_cols, key=lambda s: pv2[s].sum(), reverse=True)[:10]
    datasets = []
    for strefa in top10:
        color = STREFA_COLORS.get(strefa,"#94a3b8")
        vals  = [round(float(v)/3600, 2) if float(v) > 0 else None for v in pv2[strefa].tolist()]
        datasets.append({
            "label":           strefa.replace("STREFA_",""),
            "data":            vals,
            "backgroundColor": color,
            "borderColor":     color,
            "borderWidth":     2,
            "fill":            False,
            "tension":         0.3,
            "pointRadius":     2,
        })

    # Porównanie miesięcy — miesiąc B
    miesiac_b      = request.args.get("miesiac_b", "")
    miesiac_b_data = []
    if miesiac_b:
        df_full = load_df()
        if role not in FULL_ACCESS_ROLES:
            df_full = scope_df(df_full)
        elif lider_f and lider_f in users_all:
            df_full = df_full[df_full["hu"].isin(
                [v["hu"] for v in users_all.values() if v.get("dzial") == users_all[lider_f].get("dzial") and v.get("hu")]
            )]
        df_b = df_full[df_full["data"].dt.to_period("M").astype(str) == miesiac_b]
        if not df_b.empty:
            suma_b = df_b.groupby("strefa_docelowa")["czas_s"].sum().reset_index()
            miesiac_b_data = {r["strefa_docelowa"]: s_to_hms(int(r["czas_s"])) for _, r in suma_b.iterrows()}

    return render_template("kpi.html", error=False,
        kpi_data=kpi_data, total_hms=s_to_hms(total_s),
        pivot_cols=pivot_cols, col_totals=col_totals,
        data_od=data_od, data_do=data_do,
        strefy_f=strefy_f, strefy_all=strefy_all,
        pracownicy=pracownicy, pracownik_f=pracownik_f,
        liderzy=liderzy, lider_f=lider_f,
        miesiac_b=miesiac_b, miesiac_b_data=miesiac_b_data,
        chart_labels=json.dumps(labels),
        chart_datasets=json.dumps(datasets),
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# SZCZEGÓŁY

# ══════════════════════════════════════════════════════════════════════════════
@app.route("/szczegoly")
@login_required
def szczegoly():
    df = load_df()
    if df.empty:
        return render_template("szczegoly.html", rows=[], data_od="", data_do="",
            pracownicy=[], pracownik_f="", strefy_f=[], strefy_all=STREFY_ROBOCZE, **_nav())

    ui = user_info(); role = get_role()
    last = df["data"].max()
    data_od  = request.args.get("data_od", last.replace(day=1).strftime("%Y-%m-%d"))
    data_do  = request.args.get("data_do", last.strftime("%Y-%m-%d"))
    pracownik_f = request.args.get("pracownik","")
    strefy_f = request.args.getlist("strefy")

    if role not in FULL_ACCESS_ROLES:
        df = scope_df(df)
        pracownicy = sorted(df["pracownik"].unique().tolist())
    else:
        pracownicy = sorted(df["pracownik"].unique().tolist())

    if pracownik_f:
        df = df[df["pracownik"] == pracownik_f]
    if data_od:
        df = df[df["data"] >= pd.to_datetime(data_od)]
    if data_do:
        df = df[df["data"] <= pd.to_datetime(data_do)]

    strefy_all = sorted(df["strefa_docelowa"].unique().tolist()) if not df.empty else STREFY_ROBOCZE
    if strefy_f:
        df = df[df["strefa_docelowa"].isin(strefy_f)]

    # Pivot: pracownik × strefa per dzień
    if not df.empty:
        agg = df.groupby(["data","pracownik","strefa_docelowa"])["czas_s"].sum().reset_index()
        agg = agg[agg["czas_s"] > 0]
        # strefy które faktycznie mają dane
        strefy_pivot = sorted(agg["strefa_docelowa"].unique().tolist())
        # pivot per (data, pracownik)
        pv = agg.pivot_table(index=["data","pracownik"], columns="strefa_docelowa",
                              values="czas_s", aggfunc="sum", fill_value=0).reset_index()
        pv.columns.name = None
        pv = pv.sort_values(["data","pracownik"], ascending=[False,True])
        rows = []
        for _, r in pv.head(3000).iterrows():
            row_strefy = {}
            total = 0
            for s in strefy_pivot:
                val = int(r.get(s, 0))
                row_strefy[s] = s_to_hms(val) if val > 0 else ""
                total += val
            rows.append({
                "data":      str(r["data"].date()),
                "pracownik": r["pracownik"],
                "strefy":    row_strefy,
                "total":     s_to_hms(total),
            })
    else:
        rows = []
        strefy_pivot = []

    # Podsumowanie miesięczne per pracownik
    if not df.empty and not agg.empty:
        agg["miesiac"] = agg["data"].dt.to_period("M").astype(str)
        monthly_sum = (agg.groupby(["miesiac","pracownik"])["czas_s"]
                         .sum().reset_index()
                         .sort_values(["miesiac","pracownik"]))
        monthly_rows = [{"miesiac":r["miesiac"],"pracownik":r["pracownik"],"total":s_to_hms(int(r["czas_s"]))}
                        for _,r in monthly_sum.iterrows()]
    else:
        monthly_rows = []

    # Podstrefy zapisane w tym zakresie
    podstr_recs = load_json(PODSTR_FILE, [])
    if data_od:
        podstr_recs = [r for r in podstr_recs if r.get("data","") >= data_od]
    if data_do:
        podstr_recs = [r for r in podstr_recs if r.get("data","") <= data_do]

    return render_template("szczegoly.html",
        rows=rows, strefy_pivot=strefy_pivot,
        data_od=data_od, data_do=data_do,
        pracownicy=pracownicy, pracownik_f=pracownik_f,
        strefy_f=strefy_f, strefy_all=strefy_all,
        monthly_rows=monthly_rows,
        podstr_recs=podstr_recs,
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# ZGŁOSZENIA — strefa_z → strefa_do, akceptacja przez kierownika
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/zgloszenia", methods=["GET","POST"])
@login_required
def zgloszenia():
    ui   = user_info()
    role = get_role()
    df   = scope_df(load_df())
    pracownicy = sorted(df["pracownik"].unique().tolist()) if not df.empty else []

    if request.method == "POST":
        action = request.form.get("action","nowe")

        if action == "nowe":
            z = {
                "id":              str(uuid.uuid4())[:8],
                "timestamp":       datetime.now().isoformat(),
                "zglaszajacy":     current_user(),
                "zglaszajacy_name":ui.get("name", current_user()),
                "data_pracy":      request.form.get("data_pracy",""),
                "pracownik":       request.form.get("pracownik",""),
                "typ_problemu":    request.form.get("typ_problemu",""),
                "strefa_z":        request.form.get("strefa_z",""),
                "strefa_do":       request.form.get("strefa_do",""),
                "czas_korekty":    request.form.get("czas_korekty",""),
                "strefa_brak":     request.form.get("strefa_brak",""),
                "godz_wejscia":    request.form.get("godz_wejscia",""),
                "godz_wyjscia":    request.form.get("godz_wyjscia",""),
                "strefa_nadmiar":  request.form.get("strefa_nadmiar",""),
                "czas_faktyczny":  request.form.get("czas_faktyczny",""),
                "opis":            request.form.get("opis",""),
                "status":          "nowe",
                "akceptowal":      None,
                "akceptowal_name": None,
                "data_akceptacji": None,
            }
            lst = load_json(ZGLOS_FILE, [])
            lst.insert(0, z)
            save_json(ZGLOS_FILE, lst)
            flash("Zgłoszenie wysłane ✓", "success")
            # Email do kierowników
            body = (f"Typ: {z.get('typ_problemu','')}\n"
                    f"Pracownik: {z['pracownik']}\nData: {z['data_pracy']}\n"
                    f"Opis: {z['opis']}\n\nZglasajacy: {z['zglaszajacy_name']}")
            send_email_alert(
                f"Nowe zgloszenie - {z['pracownik']} ({z['data_pracy']})",
                body
            )

        elif action == "akceptuj" and has_permission("approve_reports"):
            zid = request.form.get("zid","")
            lst = load_json(ZGLOS_FILE, [])
            for z in lst:
                if z["id"] == zid:
                    z["status"]          = "zaakceptowane"
                    z["akceptowal"]      = current_user()
                    z["akceptowal_name"] = ui.get("name", current_user())
                    z["data_akceptacji"] = datetime.now().isoformat()
                    # --- zapisz korektę danych ---
                    _save_correction(z)
            save_json(ZGLOS_FILE, lst)
            flash("Zgłoszenie zaakceptowane i korekta zapisana ✓", "success")

        elif action == "odrzuc" and has_permission("approve_reports"):
            zid   = request.form.get("zid","")
            powod = request.form.get("powod","")
            lst   = load_json(ZGLOS_FILE, [])
            for z in lst:
                if z["id"] == zid:
                    z["status"] = "odrzucone"
                    z["powod_odrzucenia"] = powod
                    z["akceptowal"]       = current_user()
                    z["akceptowal_name"]  = ui.get("name", current_user())
                    z["data_akceptacji"]  = datetime.now().isoformat()
            save_json(ZGLOS_FILE, lst)
            flash("Zgłoszenie odrzucone.", "info")

        return redirect(url_for("zgloszenia"))

    # GET
    lst = load_json(ZGLOS_FILE, [])
    filtr = request.args.get("filtr","wszystkie")

    if role == "lider":
        team_hu = get_team_hus()
        users_l = load_users()
        hu_to_login = {v["hu"]: k for k, v in users_l.items() if v.get("hu")}
        team_logins = set(hu_to_login.get(h, "") for h in team_hu)
        lst = [z for z in lst if z["zglaszajacy"] in team_logins
               or z["zglaszajacy"] == current_user()]
    elif role not in FULL_ACCESS_ROLES:
        own = ui.get("hu", "")[3:].replace("_", " ")
        lst = [z for z in lst if z["zglaszajacy"] == current_user()
               or (own and z.get("pracownik") == own)]

    if filtr != "wszystkie":
        lst = [z for z in lst if z["status"] == filtr]

    return render_template("zgloszenia.html",
        zgloszenia=lst, pracownicy=pracownicy,
        strefy=STREFY_ROBOCZE, filtr=filtr,
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# PODSTREFY (STREFA_INNE / STREFA_ZERO)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/podstrefy", methods=["GET","POST"])
@login_required
def podstrefy():
    ui   = user_info()
    df   = load_df()
    hu_list = sorted(df["hu"].unique().tolist()) if not df.empty else []

    if request.method == "POST":
        action = request.form.get("action","save")
        if action == "delete":
            rid  = request.form.get("record_id","")
            recs = load_json(PODSTR_FILE, [])
            recs = [r for r in recs if r["id"] != rid]
            save_json(PODSTR_FILE, recs)
            flash("Rekord usunięty.", "info")
            return redirect(url_for("podstrefy"))

        psy = []
        for i in range(1, 6):
            ps = request.form.get(f"podstrefa_{i}","").strip()
            cz = request.form.get(f"czas_{i}","").strip()
            if ps and cz:
                psy.append({"podstrefa": ps, "czas": cz})

        strefa_inne_hms = request.form.get("strefa_inne","00:00:00")
        strefa_zero_hms = request.form.get("strefa_zero","00:00:00")
        sap_limit_s = hms_to_s(strefa_inne_hms) + hms_to_s(strefa_zero_hms)
        pods_sum_s  = sum(hms_to_s(p["czas"]) for p in psy)
        if sap_limit_s > 0 and pods_sum_s > sap_limit_s + 60:
            flash(f"Suma podstref ({s_to_hms(pods_sum_s)}) przekracza czas SAP INNE+ZERO ({s_to_hms(sap_limit_s)}). Popraw wartości.", "error")
            return redirect(url_for("podstrefy"))

        rec = {
            "id":          request.form.get("record_id") or str(uuid.uuid4())[:8],
            "timestamp":   datetime.now().isoformat(),
            "user":        current_user(),
            "user_name":   ui.get("name", current_user()),
            "dzial":       request.form.get("dzial",""),
            "data":        request.form.get("data_pracy",""),
            "hu":          request.form.get("hu",""),
            "strefa_inne": strefa_inne_hms,
            "strefa_zero": strefa_zero_hms,
            "podstrefy":   psy,
        }
        recs = load_json(PODSTR_FILE, [])
        ids  = [r["id"] for r in recs]
        if rec["id"] in ids:
            recs = [rec if r["id"]==rec["id"] else r for r in recs]
            flash("Zaktualizowano ✓", "success")
        else:
            recs.insert(0, rec)
            flash("Zapisano ✓", "success")
        save_json(PODSTR_FILE, recs)
        return redirect(url_for("podstrefy"))

    recs    = load_json(PODSTR_FILE, [])
    search  = request.args.get("search","").strip()
    edit_id = request.args.get("edit","")
    edit_rec = None
    data_od_p = request.args.get("data_od","")
    data_do_p = request.args.get("data_do","")

    # Lista użytkowników z STREFA_INNE lub STREFA_ZERO > 0 w wybranym zakresie
    df_pod = load_df()
    if not df_pod.empty:
        if data_od_p:
            df_pod = df_pod[df_pod["data"] >= pd.to_datetime(data_od_p)]
        if data_do_p:
            df_pod = df_pod[df_pod["data"] <= pd.to_datetime(data_do_p)]
        df_pod = scope_df(df_pod)
        df_inne_zero = df_pod[df_pod["strefa_docelowa"].isin(["STREFA_INNE","STREFA_ZERO"])]
        kandidaci = (df_inne_zero.groupby(["hu","pracownik","strefa_docelowa","data"])["czas_s"]
                     .sum().reset_index())
        kandidaci = kandidaci[kandidaci["czas_s"] > 0]
        kandidaci["czas_hms"] = kandidaci["czas_s"].apply(s_to_hms)
        # Dodaj dział z users
        users_map = load_users()
        hu_dzial  = {v["hu"]: v.get("dzial","") for v in users_map.values() if v.get("hu")}
        kandidaci["dzial"] = kandidaci["hu"].map(hu_dzial).fillna("")
        kandidaci_list = kandidaci.to_dict("records")
    else:
        kandidaci_list = []

    if search:
        recs = [r for r in recs if search.lower() in r.get("hu","").lower()
                or search.lower() in r.get("data","")]
    if edit_id:
        edit_rec = next((r for r in recs if r["id"]==edit_id), None)

    return render_template("podstrefy.html",
        records=recs[:500], edit_rec=edit_rec,
        dzialy=DZIALY, podstrefy_list=PODSTREFY,
        hu_list=hu_list, search=search,
        kandidaci=kandidaci_list,
        data_od_p=data_od_p, data_do_p=data_do_p,
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# UŻYTKOWNICY
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/uzytkownicy", methods=["GET","POST"])
@login_required
def uzytkownicy():
    if not has_permission("manage_users"):
        return redirect(url_for("kpi"))
    users  = load_users()
    df     = load_df()
    hu_list = sorted(df["hu"].unique().tolist()) if not df.empty else []

    if request.method == "POST":
        action = request.form.get("action","add")
        login_ = request.form.get("login","").strip()

        if action == "add":
            login_ = (request.form.get("login_new","") or request.form.get("login","")).strip()
            if not login_:
                flash("Podaj login.", "error")
            elif login_ in users:
                flash(f"Login {login_} już istnieje.", "error")
            else:
                raw_pass = request.form.get("password","").strip()
                if not raw_pass:
                    raw_pass = random_password()
                    flash(f"Hasło jednorazowe dla {login_}: {raw_pass}", "info")
                users[login_] = {
                    "password":       hash_password(raw_pass),
                    "role":           request.form.get("role","lider"),
                    "name":           request.form.get("name",""),
                    "hu":             request.form.get("hu",""),
                    "dzial":          request.form.get("dzial",""),
                    "resource_group": request.form.get("resource_group",""),
                    "aktualny":       True,
                    "permissions":    {},
                }
                save_json(USERS_FILE, users)
                flash(f"Użytkownik {login_} dodany ✓", "success")

        elif action == "edit" and login_ and login_ in users:
            new_pass = request.form.get("password","").strip()
            users[login_]["name"]           = request.form.get("name", users[login_].get("name",""))
            users[login_]["role"]           = request.form.get("role",  users[login_].get("role","pracownik"))
            users[login_]["hu"]             = request.form.get("hu",    users[login_].get("hu",""))
            users[login_]["dzial"]          = request.form.get("dzial", users[login_].get("dzial",""))
            users[login_]["resource_group"] = request.form.get("resource_group", users[login_].get("resource_group",""))
            if new_pass:
                users[login_]["password"] = hash_password(new_pass)
            save_json(USERS_FILE, users)
            flash(f"Użytkownik {login_} zaktualizowany ✓", "success")

        elif action == "set_permissions" and login_ and login_ in users:
            new_perms = {perm: (request.form.get(f"perm_{perm}") == "1") for perm in PERMISSION_LABELS}
            users[login_]["permissions"] = new_perms
            save_json(USERS_FILE, users)
            flash(f"Uprawnienia dla {login_} zapisane ✓", "success")

        elif action == "reset_password" and login_ and login_ in users:
            new_pass = request.form.get("new_password","").strip() or random_password()
            users[login_]["password"] = hash_password(new_pass)
            save_json(USERS_FILE, users)
            flash(f"Hasło dla {login_} zmienione na: {new_pass}", "success")

        elif action == "delete" and login_ != "admin":
            users.pop(login_, None)
            save_json(USERS_FILE, users)
            flash(f"Użytkownik {login_} usunięty.", "info")

        elif action == "toggle":
            if login_ in users:
                users[login_]["aktualny"] = not users[login_].get("aktualny", True)
                save_json(USERS_FILE, users)
                st = "aktywowany" if users[login_]["aktualny"] else "dezaktywowany"
                flash(f"Użytkownik {login_} {st}.", "info")

        elif action == "edit_dzial" and login_:
            if login_ in users:
                users[login_]["dzial"] = request.form.get("dzial","")
                save_json(USERS_FILE, users)

        return redirect(url_for("uzytkownicy") + (f"?search={request.form.get('search','')}" if request.form.get('search') else ""))

    search_u   = request.args.get("search","").strip().lower()
    filtr_rola = request.args.get("filtr_rola","").strip()
    filtered   = {}
    for k,v in users.items():
        if search_u and search_u not in k.lower() and search_u not in v.get("name","").lower() and search_u not in v.get("hu","").lower():
            continue
        if filtr_rola and v.get("role","pracownik") != filtr_rola:
            continue
        filtered[k] = v

    return render_template("uzytkownicy.html",
        users=filtered, all_count=len(users),
        hu_list=hu_list, dzialy=DZIALY,
        resource_groups=RESOURCE_GROUPS,
        permission_labels=PERMISSION_LABELS,
        default_permissions=DEFAULT_PERMISSIONS,
        get_user_permissions=get_user_permissions,
        search_u=search_u, **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# EKSPORT CSV
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/eksport")
@login_required
def eksport():
    df   = load_df()
    miesiac = request.args.get("miesiac","")

    df = scope_df(df)

    if miesiac:
        df = df[df["data"].dt.to_period("M").astype(str) == miesiac]

    out = df[["data","pracownik","hu","strefa_docelowa","dt","dt_exit","czas_s"]].copy()
    out["czas"] = out["czas_s"].apply(s_to_hms)
    out = out.drop(columns=["czas_s"])
    out["data"] = out["data"].dt.date

    buf = io.StringIO()
    out.to_csv(buf, index=False, sep=";", encoding="utf-8-sig")
    fname = f"timer_eksport_{miesiac or 'all'}.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})

# ══════════════════════════════════════════════════════════════════════════════
# HISTORIA KOREKT
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/korekty")
@login_required
def korekty():
    if not has_permission("approve_reports"):
        return redirect(url_for("dashboard"))
    korekty_list = load_json(KOREKTY_FILE, [])
    role = get_role()
    if role == "lider":
        team = get_team_hus()
        korekty_list = [k for k in korekty_list if k.get("hu","") in team]
    search = request.args.get("search","").strip().lower()
    if search:
        korekty_list = [k for k in korekty_list
                        if search in k.get("pracownik","").lower()
                        or search in k.get("data","")]
    return render_template("korekty.html", korekty=korekty_list[:500], search=search, **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# WYSZUKIWARKA PRACOWNIKA
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/pracownik")
@login_required
def pracownik_search():
    query    = request.args.get("q","").strip()
    df       = load_df()
    users_m  = load_users()

    df = scope_df(df)

    wyniki = []
    if query and not df.empty:
        mask = df["pracownik"].str.contains(query, case=False, na=False) | \
               df["hu"].str.contains(query, case=False, na=False)
        wyniki = sorted(df[mask]["pracownik"].unique().tolist())

    # Szczegóły konkretnego pracownika
    pracownik_name = request.args.get("pracownik","")
    profil = None
    if pracownik_name and not df.empty:
        df_p = df[df["pracownik"] == pracownik_name]
        if not df_p.empty:
            hu = df_p["hu"].iloc[0]
            # Dane użytkownika z users.json
            u_data = next((v for v in users_m.values() if v.get("hu") == hu), {})
            # Strefy w bieżącym miesiącu
            last = df_p["data"].max()
            m_str = last.strftime("%Y-%m")
            df_m = df_p[df_p["data"].dt.to_period("M").astype(str) == m_str]
            strefy_suma = (df_m.groupby("strefa_docelowa")["czas_s"].sum()
                           .reset_index().sort_values("czas_s", ascending=False))
            strefy_lista = [{"strefa": r["strefa_docelowa"],
                             "czas_hms": s_to_hms(int(r["czas_s"])),
                             "color": STREFA_COLORS.get(r["strefa_docelowa"],"#94a3b8")}
                            for _, r in strefy_suma.iterrows()]
            # Zgłoszenia pracownika
            zgl_all = load_json(ZGLOS_FILE, [])
            zgl_p   = [z for z in zgl_all if z.get("pracownik","").upper() == pracownik_name.upper()][:20]
            # Podstrefy
            pods_all = load_json(PODSTR_FILE, [])
            pods_p   = [r for r in pods_all if r.get("hu","") == hu][:20]
            # Grafik — dzisiaj
            grafik_all = load_json(GRAFIK_FILE, [])
            dzis = datetime.now().strftime("%Y-%m-%d")
            grafik_dzis = next((g for g in grafik_all if g.get("hu") == hu and g.get("data") == dzis), None)
            profil = {
                "pracownik": pracownik_name,
                "hu":        hu,
                "dzial":     u_data.get("dzial","—"),
                "miesiac":   m_str,
                "strefy":    strefy_lista,
                "zgloszenia": zgl_p,
                "podstrefy": pods_p,
                "grafik_dzis": grafik_dzis,
                "aktywny_dzis": grafik_dzis is not None,
            }
    return render_template("pracownik.html",
        query=query, wyniki=wyniki, pracownik_name=pracownik_name, profil=profil,
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# IMPORT / EKSPORT UŻYTKOWNIKÓW
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/uzytkownicy/eksport_csv")
@login_required
def eksport_uzytkownicy():
    if not has_permission("manage_users"):
        return redirect(url_for("dashboard"))
    users = load_users()
    buf = io.StringIO()
    buf.write("login;name;role;hu;dzial;resource_group;aktualny\n")
    for login_, u in users.items():
        buf.write(f"{login_};{u.get('name','')};{u.get('role','')};{u.get('hu','')};{u.get('dzial','')};{u.get('resource_group','')};{u.get('aktualny',True)}\n")
    return Response(buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=uzytkownicy.csv"})

@app.route("/uzytkownicy/import_excel", methods=["POST"])
@login_required
def import_uzytkownicy():
    if not has_permission("manage_users"):
        return redirect(url_for("dashboard"))
    f = request.files.get("plik")
    if not f:
        flash("Brak pliku.", "error")
        return redirect(url_for("uzytkownicy"))
    try:
        df_imp = pd.read_excel(f, dtype=str)
        df_imp.columns = [c.strip().lower() for c in df_imp.columns]
        users = load_users()
        dodano = 0
        pominięto = 0
        jednorazowe = []
        for _, row in df_imp.iterrows():
            login_ = str(row.get("login","")).strip().upper()
            if not login_:
                continue
            if login_ in users:
                pominięto += 1
                continue
            raw_pass = str(row.get("haslo", row.get("password", ""))).strip()
            if not raw_pass or raw_pass.lower() == "nan":
                raw_pass = random_password()
                jednorazowe.append(f"{login_}: {raw_pass}")
            users[login_] = {
                "password":       hash_password(raw_pass),
                "role":           str(row.get("role","lider")).strip(),
                "name":           str(row.get("name", row.get("nazwa",""))).strip(),
                "hu":             str(row.get("hu","")).strip(),
                "dzial":          str(row.get("dzial","")).strip(),
                "resource_group": str(row.get("resource_group","")).strip(),
                "aktualny":       True,
                "permissions":    {},
            }
            dodano += 1
        save_json(USERS_FILE, users)
        flash(f"Import zakończony: dodano {dodano}, pominięto {pominięto} (już istnieją).", "success")
        if jednorazowe:
            flash("Hasła jednorazowe (przekaż użytkownikom): " + ", ".join(jednorazowe), "info")
    except Exception as e:
        flash(f"Błąd importu: {e}", "error")
    return redirect(url_for("uzytkownicy"))

# ══════════════════════════════════════════════════════════════════════════════
# MOJE KONTO
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/moje_konto", methods=["GET","POST"])
@login_required
def moje_konto():
    login_ = current_user()
    users  = load_users()
    u      = users.get(login_, {})

    if request.method == "POST":
        action = request.form.get("action","")
        if action == "change_password":
            stare    = request.form.get("stare_haslo","").strip()
            nowe     = request.form.get("nowe_haslo","").strip()
            powt     = request.form.get("powtorz_haslo","").strip()
            if not verify_password(u.get("password", ""), stare):
                flash("Nieprawidłowe obecne hasło.", "error")
            elif len(nowe) < 4:
                flash("Nowe hasło musi mieć co najmniej 4 znaki.", "error")
            elif nowe != powt:
                flash("Hasła nie są zgodne.", "error")
            else:
                users[login_]["password"] = hash_password(nowe)
                save_json(USERS_FILE, users)
                flash("Hasło zostało zmienione ✓", "success")
        return redirect(url_for("moje_konto"))

    effective_perms = get_user_permissions(login_)
    return render_template("moje_konto.html",
        u=u, login=login_,
        effective_perms=effective_perms,
        permission_labels=PERMISSION_LABELS,
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/reload")
@login_required
def api_reload():
    _df_cache["mtime"] = 0
    return jsonify({"status": "ok"})

@app.route("/api/inne_zero")
@login_required
def api_inne_zero():
    """Zwraca INNE i ZERO dla danego HU i daty (do popupu podstref)."""
    hu   = request.args.get("hu","")
    data = request.args.get("data","")
    df   = load_df()
    if df.empty or not hu or not data:
        return jsonify({"inne_s":0,"zero_s":0,"inne_hms":"00:00:00","zero_hms":"00:00:00","total_s":0})
    import pandas as _pd
    try:
        data_dt = _pd.to_datetime(data)
    except Exception:
        return jsonify({"inne_s":0,"zero_s":0,"total_s":0,"inne_hms":"00:00:00","zero_hms":"00:00:00","total_hms":"00:00:00"})
    df = scope_df(df)
    mask = (df["hu"] == hu) & (df["data"].dt.date == data_dt.date())
    df_u = df[mask]
    inne_s = int(df_u[df_u["strefa_docelowa"]=="STREFA_INNE"]["czas_s"].sum())
    zero_s = int(df_u[df_u["strefa_docelowa"]=="STREFA_ZERO"]["czas_s"].sum())
    total  = inne_s + zero_s
    return jsonify({
        "hu": hu, "data": data,
        "inne_s": inne_s, "zero_s": zero_s,
        "total_s": total,
        "inne_hms": s_to_hms(inne_s),
        "zero_hms": s_to_hms(zero_s),
        "total_hms": s_to_hms(total),
    })

@app.route("/api/podstrefy_save", methods=["POST"])
@login_required
def api_podstrefy_save():
    """Zapisuje wpis podstref z popupu (AJAX)."""
    data = request.get_json()
    ui   = user_info()
    users_map = load_users()
    hu   = data.get("hu","")
    # Pobierz dział z users
    dzial = next((v.get("dzial","") for v in users_map.values() if v.get("hu")==hu), "")
    rec = {
        "id":          str(uuid.uuid4())[:8],
        "timestamp":   datetime.now().isoformat(),
        "user":        current_user(),
        "user_name":   ui.get("name", current_user()),
        "dzial":       dzial,
        "data":        data.get("data",""),
        "hu":          hu,
        "strefa_inne": s_to_hms(int(data.get("inne_s",0))),
        "strefa_zero": s_to_hms(int(data.get("zero_s",0))),
        "podstrefy":   data.get("podstrefy",[]),
    }
    recs = load_json(PODSTR_FILE, [])
    recs.insert(0, rec)
    save_json(PODSTR_FILE, recs)
    return jsonify({"status":"ok","id":rec["id"]})

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD (strona główna po zalogowaniu)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    df  = load_df()
    ui  = user_info()

    if df.empty:
        return render_template("dashboard.html", stats={}, top_strefy=[], alerty=[], **_nav())

    # Filtr roli
    df = scope_df(df)

    last  = df["data"].max()
    m_str = last.strftime("%Y-%m") if pd.notna(last) else ""
    df_m  = df[df["data"].dt.to_period("M").astype(str) == m_str]

    total_s   = int(df_m["czas_s"].sum())
    pracownicy_cnt = df_m["pracownik"].nunique()
    strefy_cnt     = df_m["strefa_docelowa"].nunique()

    top = (df_m.groupby("strefa_docelowa")["czas_s"].sum()
               .sort_values(ascending=False).head(5).reset_index())
    top_strefy = [{"strefa": r["strefa_docelowa"],
                   "czas_hms": s_to_hms(int(r["czas_s"])),
                   "czas_h": round(float(r["czas_s"])/3600, 1),
                   "color": STREFA_COLORS.get(r["strefa_docelowa"],"#94a3b8")}
                  for _, r in top.iterrows()]

    total_all_h = round(df_m.groupby("strefa_docelowa")["czas_s"].sum().sum()/3600,1)

    # Alerty — INNE+ZERO nierozpisane
    podstr = load_json(PODSTR_FILE, [])
    rozpisane_klucze = {(r["hu"], r["data"]) for r in podstr}
    df_iz = df_m[df_m["strefa_docelowa"].isin(["STREFA_INNE","STREFA_ZERO"])]
    alerty = []
    for (hu, data), grp in df_iz.groupby(["hu", df_iz["data"].dt.strftime("%Y-%m-%d")]):
        if (hu, data) not in rozpisane_klucze and grp["czas_s"].sum() > 300:
            alerty.append({
                "hu": hu,
                "pracownik": grp["pracownik"].iloc[0],
                "data": data,
                "czas_hms": s_to_hms(int(grp["czas_s"].sum())),
            })
    alerty = alerty[:10]

    stats = {
        "miesiac": m_str,
        "total_hms": s_to_hms(total_s),
        "total_h": round(total_s/3600, 1),
        "pracownicy": pracownicy_cnt,
        "strefy": strefy_cnt,
    }

    # ─── Trend tygodniowy — top 5 stref ─────────────────────────────────────
    trend_labels = None
    trend_datasets = None
    if not df_m.empty:
        df_t = df_m.copy()
        df_t["week"] = df_t["data"].dt.strftime("%Y-W%V")
        weeks = sorted(df_t["week"].unique())
        top5 = (df_t.groupby("strefa_docelowa")["czas_s"].sum()
                    .sort_values(ascending=False).head(5).index.tolist())
        datasets = []
        for st in top5:
            weekly = df_t[df_t["strefa_docelowa"] == st].groupby("week")["czas_s"].sum()
            data_pts = [round(float(weekly.get(w, 0)) / 3600, 1) for w in weeks]
            color = STREFA_COLORS.get(st, "#94a3b8")
            datasets.append({
                "label": st.replace("STREFA_", ""),
                "data": data_pts,
                "borderColor": color,
                "backgroundColor": color + "33",
                "tension": 0.3,
                "fill": False,
                "pointRadius": 3,
            })
        trend_labels = json.dumps(weeks)
        trend_datasets = json.dumps(datasets)

    # ─── Plan vs Wykonanie ───────────────────────────────────────────────────
    plan_vs_exec = None
    grafik_recs = load_json(GRAFIK_FILE, [])
    plan_by_hu: dict = {}
    for r in grafik_recs:
        if str(r.get("data", ""))[:7] == m_str:
            hu = r.get("hu", "")
            try:
                plan_h = float(r.get("godz_plan", 8))
            except (ValueError, TypeError):
                plan_h = 8.0
            plan_by_hu[hu] = plan_by_hu.get(hu, 0.0) + plan_h
    if plan_by_hu:
        exec_by_hu = (df_m.groupby("hu")["czas_s"].sum() / 3600).round(1).to_dict()
        hu_to_prac = df_m.drop_duplicates("hu").set_index("hu")["pracownik"].to_dict()
        rows = []
        for hu, plan_h in plan_by_hu.items():
            exec_h = round(float(exec_by_hu.get(hu, 0.0)), 1)
            rows.append({
                "pracownik": hu_to_prac.get(hu, hu),
                "hu": hu,
                "plan_h": round(plan_h, 1),
                "exec_h": exec_h,
                "diff": round(exec_h - plan_h, 1),
            })
        plan_vs_exec = sorted(rows, key=lambda x: x["diff"])

    return render_template("dashboard.html",
        stats=stats, top_strefy=top_strefy, alerty=alerty,
        trend_labels=trend_labels, trend_datasets=trend_datasets,
        plan_vs_exec=plan_vs_exec,
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# GRAFIK OBECNOŚCI
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/grafik", methods=["GET","POST"])
@login_required
def grafik():
    if not has_permission("view_schedule"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        action = request.form.get("action","add")
        if action == "add":
            rec = {
                "id":        str(uuid.uuid4())[:8],
                "hu":        request.form.get("hu",""),
                "data":      request.form.get("data",""),
                "godz_od":   request.form.get("godz_od",""),
                "godz_do":   request.form.get("godz_do",""),
                "godz_plan": request.form.get("godz_plan","8"),
                "user":      current_user(),
            }
            recs = load_json(GRAFIK_FILE, [])
            recs.insert(0, rec)
            save_json(GRAFIK_FILE, recs)
            flash("Wpis grafiku dodany ✓", "success")
        elif action == "delete":
            rid  = request.form.get("record_id","")
            recs = load_json(GRAFIK_FILE, [])
            recs = [r for r in recs if r["id"] != rid]
            save_json(GRAFIK_FILE, recs)
            flash("Wpis usunięty.", "info")
        return redirect(url_for("grafik"))

    recs = load_json(GRAFIK_FILE, [])
    df   = load_df()
    # Dla lidera — tylko jego dział
    if is_lider():
        team = get_team_hus()
        recs = [r for r in recs if r.get("hu","") in team]
    hu_list = sorted(df["hu"].unique().tolist()) if not df.empty else []
    search  = request.args.get("search","")
    if search:
        recs = [r for r in recs if search.lower() in r.get("hu","").lower()
                or search in r.get("data","")]

    # Wykrywanie niezgodności SAP vs grafik
    niezgodnosci = []
    if not df.empty and recs:
        for r in recs[:200]:
            hu   = r.get("hu","")
            data = r.get("data","")
            plan = float(r.get("godz_plan", 8))
            try:
                mask = (df["hu"]==hu) & (df["data"].dt.strftime("%Y-%m-%d")==data)
                sap_s = float(df[mask]["czas_s"].sum())
                sap_h = round(sap_s/3600, 2)
                diff  = round(sap_h - plan, 2)
                if abs(diff) > 0.5:
                    niezgodnosci.append({
                        "hu": hu, "data": data,
                        "plan_h": plan, "sap_h": sap_h,
                        "diff_h": diff,
                        "typ": "nadmiar" if diff > 0 else "brak",
                    })
            except Exception:
                pass

    return render_template("grafik.html",
        records=recs[:500], hu_list=hu_list,
        search=search, niezgodnosci=niezgodnosci[:20],
        **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# SŁOWNIKI (konfigurowalne strefy i podstrefy)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/slowniki", methods=["GET","POST"])
@login_required
def slowniki():
    if not has_permission("manage_dictionaries"):
        return redirect(url_for("dashboard"))
    sl = load_slowniki()
    if request.method == "POST":
        typ    = request.form.get("typ","strefy")
        action = request.form.get("action","add")
        wartosc = request.form.get("wartosc","").strip()
        if action == "add" and wartosc:
            if wartosc not in sl[typ]:
                sl[typ].append(wartosc)
                sl[typ].sort()
                flash(f"Dodano: {wartosc}", "success")
        elif action == "delete" and wartosc:
            sl[typ] = [x for x in sl[typ] if x != wartosc]
            flash(f"Usunięto: {wartosc}", "info")
        save_json(SLOWNIK_FILE, sl)
        return redirect(url_for("slowniki"))
    return render_template("slowniki.html", slowniki=sl, **_nav())

# ══════════════════════════════════════════════════════════════════════════════
# USTAWIENIA SMTP
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/ustawienia", methods=["GET","POST"])
@login_required
def ustawienia():
    if not has_permission("manage_settings"):
        return redirect(url_for("dashboard"))
    cfg = load_smtp()
    if request.method == "POST" and DEMO_MODE:
        flash("W publicznym demo ustawienia SMTP są zablokowane.", "error")
        return redirect(url_for("ustawienia"))
    if request.method == "POST":
        cfg = {
            "server":   request.form.get("server",""),
            "port":     int(request.form.get("port", 587)),
            "user":     request.form.get("user",""),
            "password": request.form.get("password","") or cfg.get("password",""),
            "from":     request.form.get("from_addr",""),
            "kierownicy_email": [e.strip() for e in request.form.get("emails","").split(",") if e.strip()],
            "enabled":  request.form.get("enabled") == "1",
        }
        save_json(SMTP_FILE, cfg)
        flash("Ustawienia zapisane ✓", "success")
        # Test
        if request.form.get("test"):
            ok = send_email_alert("Test TIMER", "Wiadomość testowa z systemu TIMER.")
            flash("Test email wysłany ✓" if ok else "Test nieudany — sprawdź dane SMTP.", "success" if ok else "error")
        return redirect(url_for("ustawienia"))
    return render_template("ustawienia.html", cfg=cfg, **_nav())

# Usunięto widok Live — przekierowanie dla starych linków
@app.route("/live")
@login_required
def live():
    return redirect(url_for("dashboard"))

# ══════════════════════════════════════════════════════════════════════════════
# API — zatwierdzanie podstref
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/server_info")
@login_required
def api_server_info():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "localhost"
    return jsonify({"ip":ip,"port":5000,"url":f"http://{ip}:5000"})

@app.route("/api/podstrefy_zatwierdz", methods=["POST"])
@login_required
def api_zatwierdz():
    if not has_permission("manage_subzones"):
        return jsonify({"error": "brak uprawnień"}), 403
    data = request.get_json()
    rid  = data.get("id","")
    recs = load_json(PODSTR_FILE, [])
    ui   = user_info()
    for r in recs:
        if r["id"] == rid:
            r["zatwierdzone"]       = True
            r["zatwierdzone_przez"] = ui.get("name", current_user())
            r["zatwierdzone_dt"]    = datetime.now().isoformat()
    save_json(PODSTR_FILE, recs)
    return jsonify({"status":"ok"})

@app.route("/api/notifications")
@login_required
def api_notifications():
    return jsonify({"pending": pending_notifications()})

if __name__ == "__main__":
    ensure_admin()
    # Tryb deweloperski: tylko localhost; debugger Werkzeug wyłącznie na życzenie (FLASK_DEBUG=1).
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
