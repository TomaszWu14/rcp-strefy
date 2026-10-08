"""
TIMER – Konfiguracja sieci (uruchom RAZ jako administrator)
Otwiera port 5000 w Windows Firewall i pokazuje adres IP serwera
"""
import subprocess, socket, sys, os

PORT = 5000

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("  TIMER — Konfiguracja sieci")
    print("=" * 60)

    ip = get_local_ip()
    print(f"\n  IP serwera: {ip}")
    print(f"  Port:       {PORT}")
    print(f"  Adres dla kolegów: http://{ip}:{PORT}\n")

    # Sprawdź czy admin
    if not is_admin():
        print("  ⚠  Uruchom ten skrypt jako Administrator")
        print("     (kliknij prawym → 'Uruchom jako administrator')")
        input("\n  Naciśnij Enter aby zamknąć...")
        sys.exit(1)

    # Otwórz port w firewall
    rule_name = f"TIMER Flask port {PORT}"
    rule = ["netsh", "advfirewall", "firewall"]
    subprocess.run(rule + ["delete", "rule", f"name={rule_name}"], capture_output=True)
    result = subprocess.run(rule + ["add", "rule", f"name={rule_name}", "protocol=TCP", "dir=in",
                                    f"localport={PORT}", "action=allow"],
                            capture_output=True, text=True)

    if result.returncode == 0:
        print(f"  ✓ Firewall otwarty na port {PORT}")
    else:
        print(f"  ✗ Błąd firewall: {result.stderr}")

    # Zapisz IP do pliku konfiguracyjnego
    config_path = __import__('pathlib').Path(__file__).parent / "data" / "server_config.json"
    import json
    config = {"ip": ip, "port": PORT, "url": f"http://{ip}:{PORT}"}
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))

    print(f"\n  ✓ Konfiguracja zapisana")
    print(f"\n  Teraz uruchom: python start.py")
    print(f"  Kolega wpisuje w przeglądarce: http://{ip}:{PORT}")
    print("=" * 60)
    input("\n  Naciśnij Enter aby zamknąć...")
