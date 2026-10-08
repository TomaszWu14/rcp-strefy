"""
sharepoint_sync.py — Auto-pobieranie Czasy.xlsx i Grafik.xlsx z SharePoint

KONFIGURACJA (uzupełnij dane w pliku data/sharepoint_config.json):
{
    "url":           "https://twojafirma.sharepoint.com/sites/NazwaSite",
    "username":      "twoj@example.com",
    "password":      "twoje_haslo",
    "czasy_path":    "/sites/NazwaSite/Shared Documents/Czasy.xlsx",
    "grafik_path":   "/sites/NazwaSite/Shared Documents/Grafik.xlsx",
    "interval_min":  5,
    "enabled":       true
}

WYMAGANA BIBLIOTEKA:
    pip install Office365-REST-Python-Client

URUCHOMIENIE JAKO SCHEDULER (PythonAnywhere Hacker+):
    Dodaj w Tasks: python /home/<user>/rcp-strefy/sharepoint_sync.py --once
    Ustaw interwał co 5 minut.

LUB jako wątek tła w start.py:
    import sharepoint_sync
    sharepoint_sync.start_background()
"""

import json, shutil, time, os, sys, threading
from pathlib import Path
from datetime import datetime

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "sharepoint_config.json"
LOG_FILE    = DATA_DIR / "sharepoint_sync.log"

CZASY_LOCAL  = BASE_DIR / "czasy_calc.parquet"
GRAFIK_LOCAL = DATA_DIR / "grafik_import.xlsx"

_running = False


def _log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_default_config():
    """Tworzy przykładowy plik konfiguracyjny jeśli nie istnieje."""
    if CONFIG_FILE.exists():
        return
    default = {
        "url":          "https://twojafirma.sharepoint.com/sites/NazwaSite",
        "username":     "twoj@example.com",
        "password":     "twoje_haslo",
        "czasy_path":   "/sites/NazwaSite/Shared Documents/Czasy.xlsx",
        "grafik_path":  "/sites/NazwaSite/Shared Documents/Grafik.xlsx",
        "interval_min": 5,
        "enabled":      False,
    }
    DATA_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
    _log("Utworzono przykładowy sharepoint_config.json — uzupełnij dane i ustaw enabled=true")


def download_file(ctx, sp_path, local_path):
    """Pobiera plik z SharePoint do local_path."""
    from office365.sharepoint.files.file import File  # type: ignore
    tmp = str(local_path) + ".tmp"
    with open(tmp, "wb") as f:
        File.from_url(ctx, sp_path).download(f).execute_query()
    shutil.move(tmp, str(local_path))
    _log(f"Pobrano: {sp_path} → {local_path}")


def process_czasy(xlsx_path):
    """Uruchamia pipeline czasy_stref_pipeline.py na pobranym Czasy.xlsx."""
    pipeline = BASE_DIR / "czasy_stref_pipeline.py"
    if not pipeline.exists():
        _log("Brak czasy_stref_pipeline.py — pomijam przetwarzanie")
        return
    import subprocess
    result = subprocess.run(
        [sys.executable, str(pipeline)],
        capture_output=True, text=True, cwd=str(BASE_DIR)
    )
    if result.returncode == 0:
        _log("Pipeline Czasy.xlsx wykonany pomyślnie")
    else:
        _log(f"Pipeline błąd: {result.stderr[:300]}")


def process_grafik(xlsx_path):
    """Importuje grafik z Excela do grafik.json."""
    try:
        import pandas as pd
        df = pd.read_excel(xlsx_path, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]

        # Oczekiwane kolumny: hu, data, godz_od, godz_do, godz_plan
        # Dopasuj elastycznie
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if "hu" in cl:            col_map["hu"] = col
            elif "data" in cl:        col_map["data"] = col
            elif "od" in cl:          col_map["godz_od"] = col
            elif "do" in cl:          col_map["godz_do"] = col
            elif "plan" in cl or "h" in cl: col_map["godz_plan"] = col

        records = []
        import uuid as _uuid
        for _, row in df.iterrows():
            hu = str(row.get(col_map.get("hu",""),"")).strip()
            data = str(row.get(col_map.get("data",""),"")).strip()
            if not hu or not data or hu == "nan" or data == "nan":
                continue
            # Normalizuj datę
            try:
                data = pd.to_datetime(data).strftime("%Y-%m-%d")
            except Exception:
                continue
            records.append({
                "id":        str(_uuid.uuid4())[:8],
                "hu":        hu,
                "data":      data,
                "godz_od":   str(row.get(col_map.get("godz_od",""),"")).strip(),
                "godz_do":   str(row.get(col_map.get("godz_do",""),"")).strip(),
                "godz_plan": str(row.get(col_map.get("godz_plan",""),"8")).strip() or "8",
                "user":      "sharepoint_sync",
            })

        grafik_file = DATA_DIR / "grafik.json"
        grafik_file.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        _log(f"Grafik zaktualizowany: {len(records)} wpisów")
    except Exception as e:
        _log(f"Błąd importu grafiku: {e}")


def sync_once():
    """Jednorazowe pobranie plików z SharePoint."""
    cfg = load_config()
    if not cfg.get("enabled"):
        _log("SharePoint sync wyłączony (enabled=false w sharepoint_config.json)")
        return False

    try:
        from office365.runtime.auth.user_credential import UserCredential  # type: ignore
        from office365.sharepoint.client_context import ClientContext       # type: ignore
    except ImportError:
        _log("Brak biblioteki Office365. Zainstaluj: pip install Office365-REST-Python-Client")
        return False

    try:
        url      = cfg["url"]
        username = cfg["username"]
        password = cfg["password"]
        ctx = ClientContext(url).with_credentials(UserCredential(username, password))

        # Pobierz Czasy.xlsx
        czasy_tmp = DATA_DIR / "Czasy_sync.xlsx"
        download_file(ctx, cfg["czasy_path"], czasy_tmp)
        # Skopiuj jako główny plik i uruchom pipeline
        shutil.copy(str(czasy_tmp), str(BASE_DIR / "Czasy.xlsx"))
        process_czasy(czasy_tmp)

        # Pobierz Grafik.xlsx
        download_file(ctx, cfg["grafik_path"], GRAFIK_LOCAL)
        process_grafik(GRAFIK_LOCAL)

        return True
    except Exception as e:
        _log(f"Błąd sync SharePoint: {e}")
        return False


def _background_loop(interval_min):
    global _running
    _running = True
    _log(f"SharePoint sync uruchomiony (co {interval_min} min)")
    while _running:
        sync_once()
        time.sleep(interval_min * 60)
    _log("SharePoint sync zatrzymany")


def start_background():
    """Uruchamia sync w wątku tła — wywołaj z start.py."""
    save_default_config()
    cfg = load_config()
    if not cfg.get("enabled"):
        _log("SharePoint sync wyłączony — uruchom po konfiguracji sharepoint_config.json")
        return None
    interval = int(cfg.get("interval_min", 5))
    t = threading.Thread(target=_background_loop, args=(interval,), daemon=True)
    t.start()
    return t


def stop_background():
    global _running
    _running = False


if __name__ == "__main__":
    save_default_config()
    if "--once" in sys.argv:
        sync_once()
    else:
        # Ciągłe działanie (dla testów lokalnych)
        cfg = load_config()
        interval = int(cfg.get("interval_min", 5))
        while True:
            sync_once()
            time.sleep(interval * 60)
