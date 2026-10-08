"""
TIMER – Start serwera
Uruchamia Flask na 0.0.0.0 (dostępny dla całej sieci firmowej)
+ Scheduler odświeżający dane z SAP co godzinę
"""
import subprocess, sys, socket, threading, time, shutil
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
PORT = 5000

# ── Kopiuj parquet jeśli jest obok ───────────────────────────────────────────
for src in [BASE / "czasy_calc.parquet", BASE.parent / "czasy_calc.parquet"]:
    dst = BASE / "czasy_calc.parquet"
    if src.exists() and src != dst:
        shutil.copy(src, dst)
        print(f"Dane skopiowane z: {src}")
        break

# ── IP serwera ────────────────────────────────────────────────────────────────
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

ip = get_ip()

# ── Scheduler SAP (co 1h) ─────────────────────────────────────────────────────
PIPELINE = BASE / "czasy_stref_pipeline.py"

def run_pipeline():
    if not PIPELINE.exists():
        return
    print(f"[{time.strftime('%H:%M')}] Uruchamiam pipeline...")
    try:
        r = subprocess.run([sys.executable, str(PIPELINE)],
                           capture_output=True, text=True, timeout=600)
        print(f"[{time.strftime('%H:%M')}] Pipeline {'OK' if r.returncode==0 else 'BLAD'}")
        if r.returncode != 0:
            print(r.stderr[-300:])
    except Exception as e:
        print(f"[Scheduler] {e}")

def scheduler_loop():
    run_pipeline()
    while True:
        time.sleep(3600)
        run_pipeline()

if PIPELINE.exists():
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Scheduler aktywny — pipeline co 1h")

# ── SharePoint sync (co 5 min, jeśli skonfigurowany) ─────────────────────────
try:
    import sharepoint_sync
    sharepoint_sync.start_background()
except Exception as _sp_err:
    print(f"[SharePoint] Pominięto: {_sp_err}")

# ── Start info ────────────────────────────────────────────────────────────────
print("=" * 52)
print("  TIMER — System czasu pracy w strefach")
print("=" * 52)
print(f"  Lokalny:  http://localhost:{PORT}")
print(f"  Siec:     http://{ip}:{PORT}  <- dla kolegów")
print("  Konta:    data/users.json (demo: kierownik / demo123)")
print()
print(f"  Problem z dostepem? Uruchom setup_network.py")
print(f"  jako Administrator (raz, przy pierwszym starcie)")
print("=" * 52)

# ── Flask ─────────────────────────────────────────────────────────────────────
from app import app, ensure_admin
ensure_admin()
# Celowo 0.0.0.0: aplikacja ma być dostępna z sieci LAN (port otwiera setup_network.py).
app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)  # nosec B104
