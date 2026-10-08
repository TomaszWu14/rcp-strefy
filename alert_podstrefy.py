"""
alert_podstrefy.py — Dzienny alert o nierozpisanych STREFA_INNE / STREFA_ZERO

Uruchom jako Scheduled Task na PythonAnywhere o 12:00:
    python /home/<user>/rcp-strefy/alert_podstrefy.py

Wysyła email do lidera jeśli któryś z jego pracowników
ma nierozpisany czas INNE/ZERO z poprzedniego dnia.
"""

import json, smtplib, sys
from pathlib import Path
from datetime import datetime, timedelta
from email.mime.text import MIMEText

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
PODSTR_FILE = DATA_DIR / "podstrefy.json"
USERS_FILE  = DATA_DIR / "users.json"
SMTP_FILE   = DATA_DIR / "smtp_config.json"

try:
    import pandas as pd
    _P1 = BASE_DIR / "czasy_calc.parquet"
    _P2 = DATA_DIR / "czasy_calc.parquet"
    PARQUET = _P1 if _P1.exists() else _P2
except ImportError:
    print("Brak pandas — zainstaluj: pip install pandas pyarrow")
    sys.exit(1)


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def send_email(cfg, to_addr, subject, body):
    if not cfg.get("enabled") or not cfg.get("user"):
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[TIMER] {subject}"
        msg["From"]    = cfg.get("from") or cfg["user"]
        msg["To"]      = to_addr
        with smtplib.SMTP(cfg["server"], int(cfg.get("port", 587))) as s:
            s.starttls()
            s.login(cfg["user"], cfg["password"])
            s.sendmail(msg["From"], [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"Email błąd ({to_addr}): {e}")
        return False


def main():
    cfg     = load_json(SMTP_FILE, {})
    users   = load_json(USERS_FILE, {})
    podstr  = load_json(PODSTR_FILE, [])

    if not PARQUET.exists():
        print("Brak parquet — pomijam")
        return

    df = pd.read_parquet(PARQUET)
    df["data"] = pd.to_datetime(df["data"])
    df = df[df["strefa_docelowa"] != "STREFA_KONIEC"]

    # Sprawdź poprzedni dzień roboczy
    wczoraj = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    df_iz = df[
        (df["data"].dt.strftime("%Y-%m-%d") == wczoraj) &
        (df["strefa_docelowa"].isin(["STREFA_INNE", "STREFA_ZERO"]))
    ]
    if df_iz.empty:
        print(f"Brak danych INNE/ZERO za {wczoraj}")
        return

    rozpisane = {(r["hu"], r["data"]) for r in podstr}

    # Grupuj nierozpisane per hu
    nierozpisane = {}  # hu → czas_s
    for (hu, data), grp in df_iz.groupby(["hu", df_iz["data"].dt.strftime("%Y-%m-%d")]):
        if (hu, data) not in rozpisane and grp["czas_s"].sum() > 300:
            pracownik = grp["pracownik"].iloc[0]
            nierozpisane.setdefault(hu, []).append({
                "pracownik": pracownik,
                "czas_s": int(grp["czas_s"].sum()),
            })

    if not nierozpisane:
        print(f"Brak nierozpisanych INNE/ZERO za {wczoraj} — brak alertów")
        return

    # Mapuj HU → lider (po dziale lub resource_group)
    hu_to_dzial = {v["hu"]: v.get("dzial","") for v in users.values() if v.get("hu")}

    # Pogrupuj nierozpisane per lider
    lider_alerts = {}  # login_lidera → lista pracowników
    for login_, u in users.items():
        if u.get("role") != "lider":
            continue
        lider_dzial = u.get("dzial","")
        lider_rg    = u.get("resource_group","")
        for hu, wpisy in nierozpisane.items():
            dzial_hu = hu_to_dzial.get(hu,"")
            nalezy = False
            if lider_rg and lider_rg != "ALL":
                nalezy = any(v.get("resource_group") == lider_rg
                             for v in users.values() if v.get("hu") == hu)
            elif lider_dzial and dzial_hu == lider_dzial:
                nalezy = True
            if nalezy:
                lider_alerts.setdefault(login_, []).extend(wpisy)

    # Wyślij email do każdego lidera
    sent = 0
    for login_, wpisy in lider_alerts.items():
        u = users[login_]
        # Znajdź email lidera (pole email lub kierownicy_email jako fallback)
        to_addr = u.get("email","")
        if not to_addr:
            # Fallback: kierownicy z ustawień
            to_addr = cfg.get("kierownicy_email",[""])[0] if cfg.get("kierownicy_email") else ""
        if not to_addr:
            print(f"Brak emaila dla lidera {login_} — pomijam")
            continue

        lines = [f"  • {w['pracownik']} — {w['czas_s']//3600:02}:{(w['czas_s']%3600)//60:02}:{w['czas_s']%60:02}"
                 for w in wpisy]
        body = (
            f"Cześć {u.get('name', login_)},\n\n"
            f"Poniżsi pracownicy z Twojego działu mają nierozpisany czas "
            f"STREFA_INNE lub STREFA_ZERO za {wczoraj}:\n\n"
            + "\n".join(lines) +
            f"\n\nZaloguj się do TIMER i rozpisz podstrefy.\n\n"
            f"-- System TIMER"
        )
        ok = send_email(cfg, to_addr, f"Nierozpisane podstrefy — {wczoraj}", body)
        if ok:
            sent += 1
            print(f"Email wysłany do {login_} ({to_addr}): {len(wpisy)} pracowników")

    print(f"Alert zakończony: wysłano {sent} emaili, {len(lider_alerts)} liderów z alertami")


if __name__ == "__main__":
    main()
