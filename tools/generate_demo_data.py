"""Generuje syntetyczne dane demo do aplikacji TIMER (KPI czasu w strefach).

Wszystkie osoby, zmiany i zgłoszenia są fikcyjne. Hasła kont demo są hashowane
(werkzeug), hasło każdego konta: ``demo123``.

Użycie:
    python tools/generate_demo_data.py            # zapisuje do ./data
    python tools/generate_demo_data.py --out DIR
"""
import argparse
import json
import random
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from werkzeug.security import generate_password_hash

SEED = 20260101
START, END = date(2026, 1, 5), date(2026, 3, 31)
DEMO_PASSWORD = "demo123"

# (imię, nazwisko, dział, grupa zasobów, zmiana)
WORKERS = [
    ("Jan", "Kowalski", "Dział_Kompletacji", "PICKING", 1),
    ("Anna", "Nowak", "Dział_Kompletacji", "PICKING", 1),
    ("Piotr", "Wiśniewski", "Dział_Kompletacji", "PICKING", 2),
    ("Katarzyna", "Wójcik", "Dział_Kompletacji", "PICKING", 2),
    ("Tomasz", "Kamiński", "Dział_Kompletacji", "PICKING", 1),
    ("Magdalena", "Lewandowska", "Dział_Kompletacji", "PICKING", 2),
    ("Marcin", "Zieliński", "Dział_Przyjęć", "INBOUND", 1),
    ("Agnieszka", "Szymańska", "Dział_Przyjęć", "INBOUND", 1),
    ("Paweł", "Woźniak", "Dział_Przyjęć_Kontenerowych", "INBOUND", 1),
    ("Ewa", "Dąbrowska", "Dział_Przyjęć_Kontenerowych", "INBOUND", 2),
    ("Michał", "Kozłowski", "Dział_Wysyłek_A", "OUTBOUND", 1),
    ("Joanna", "Jankowska", "Dział_Wysyłek_A", "OUTBOUND", 2),
    ("Krzysztof", "Mazur", "Dział_Wysyłek_B", "OUTBOUND", 1),
    ("Monika", "Krawczyk", "Dział_Wysyłek_Bus", "OUTBOUND", 2),
    ("Łukasz", "Piotrowski", "Dział_Eksportu", "OUTBOUND", 1),
    ("Natalia", "Grabowska", "Dział_Eksportu", "OUTBOUND", 1),
    ("Adam", "Pawłowski", "Dział_Inwentaryzacja", "LOGISTYKA", 1),
    ("Karolina", "Michalska", "Dział_Zwrotów", "LOGISTYKA", 2),
    ("Rafał", "Król", "Dział_Reklamacji", "LOGISTYKA", 1),
    ("Barbara", "Wieczorek", "Dział_Reorganizacji_Magazynu", "LOGISTYKA", 2),
    ("Grzegorz", "Jabłoński", "Dział_Dystrybucji_Oddziały", "OUTBOUND", 1),
    ("Aleksandra", "Wróbel", "Dział_Dystrybucji_Oddziały", "OUTBOUND", 2),
    ("Dariusz", "Majewski", "Dział_Administracji", "ADMINISTRACJA", 1),
    ("Patrycja", "Olszewska", "Dział_Pomocniczy(Inne)", "LOGISTYKA", 1),
]
MANAGERS = [("kierownik", "Maria Kierownik", "kierownik", ""),
            ("lider.kpl", "Jakub Lider", "lider", "Dział_Kompletacji"),
            ("lider.wys", "Ola Liderka", "lider", "Dział_Wysyłek_A")]

# Główne strefy pracy wg działu (strefa, waga); reszta dnia: INNE/ZERO/szkolenie
ZONES = {
    "Dział_Kompletacji": [("STREFA_PICKING", 8), ("STREFA_ODDZIAŁ_KPL", 2), ("STREFA_KP_PALECIAK", 1)],
    "Dział_Przyjęć": [("STREFA_PRZYJĘCIA", 8), ("STREFA_KP_ELEKTRYK", 2)],
    "Dział_Przyjęć_Kontenerowych": [("STREFA_KONTENERY", 7), ("STREFA_PRZYJĘCIA", 3)],
    "Dział_Wysyłek_A": [("STREFA_PRZEWOZNIK_A", 8), ("STREFA_PICKING", 2)],
    "Dział_Wysyłek_B": [("STREFA_PRZEWOZNIK_B", 8), ("STREFA_PICKING", 2)],
    "Dział_Wysyłek_Bus": [("STREFA_BUS", 8), ("STREFA_PICKING", 2)],
    "Dział_Eksportu": [("STREFA_EXPORT", 7), ("STREFA_KLIENT_A", 2), ("STREFA_KLIENT_C", 1)],
    "Dział_Inwentaryzacja": [("STREFA_INV", 9), ("STREFA_REO", 1)],
    "Dział_Zwrotów": [("STREFA_ZWROTY", 8), ("STREFA_REKLAMACJE", 2)],
    "Dział_Reklamacji": [("STREFA_REKLAMACJE", 8), ("STREFA_ZWROTY", 2)],
    "Dział_Reorganizacji_Magazynu": [("STREFA_REO", 8), ("STREFA_KP_ELEKTRYK", 2)],
    "Dział_Dystrybucji_Oddziały": [("STREFA_ODDZIAŁY", 6), ("STREFA_ODDZIAŁ_PAK", 3), ("STREFA_KLIENT_B", 1)],
    "Dział_Administracji": [("STREFA_ADMIN_MAG", 9), ("STREFA_SZKOLENIE", 1)],
    "Dział_Pomocniczy(Inne)": [("STREFA_INNE", 5), ("STREFA_UKRAINA", 3), ("STREFA_SZKOLENIE", 2)],
}
SIDE = [("STREFA_INNE", 3), ("STREFA_ZERO", 2), ("STREFA_SZKOLENIE", 1)]
PODSTREFY = ["STREFA_Przekładanie_palet", "STREFA_Foliowanie_palet", "STREFA_Przepakowania_kartonów",
             "STREFA_Sprzątanie", "STREFA_Awaria_systemu", "STREFA_Generowanie_zleceń"]


def pick(rng, weighted):
    return rng.choices([z for z, _ in weighted], weights=[w for _, w in weighted])[0]


def code(first, last):
    """„KOWALSKI JAN” — format kolumny `pracownik` z eksportu."""
    return f"{last.upper()} {first.upper()[:3]}"


def login(first, last):
    tr = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return (first[0] + last).translate(tr).upper()


def workdays():
    d = START
    while d <= END:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def shift_segments(rng, day, dept, shift):
    """Odcinki jednej zmiany: strefy robocze + przerwa w połowie; ~8 h."""
    start = datetime.combine(day, time(6 if shift == 1 else 14)) + timedelta(minutes=rng.randint(-10, 12))
    end = start + timedelta(hours=8, minutes=rng.randint(-15, 20))
    brk = start + timedelta(hours=4, minutes=rng.randint(-30, 30))
    t, rows, had_break = start, [], False
    while t < end:
        if not had_break and t >= brk:
            zone, dur = "STREFA_PRZERWA", rng.randint(14, 17)
            had_break = True
        else:
            zone = pick(rng, ZONES[dept] if rng.random() < 0.85 else SIDE)
            dur = max(3, int(rng.lognormvariate(3.3, 0.6)))  # mediana ~27 min
        exit_ = min(t + timedelta(minutes=dur, seconds=rng.randint(0, 59)), end)
        rows.append((zone, t, exit_))
        t = exit_ + timedelta(seconds=rng.randint(5, 90))
    return rows


def build(out):
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for first, last, dept, _, shift in WORKERS:
        who = code(first, last)
        for day in workdays():
            if rng.random() < 0.06:  # urlop / L4
                continue
            for zone, dt, dt_exit in shift_segments(rng, day, dept, shift):
                rows.append({"data": pd.Timestamp(day), "pracownik": who, "hu": "HU_" + who.replace(" ", "_"),
                             "strefa_docelowa": zone, "dt": dt, "dt_exit": dt_exit,
                             "czas_s": int((dt_exit - dt).total_seconds())})
    df = pd.DataFrame(rows)
    df.to_parquet(out / "czasy_calc.parquet", index=False)

    pw = generate_password_hash(DEMO_PASSWORD)
    users = {"admin": {"password": pw, "role": "kierownik", "name": "Administrator", "hu": "", "dzial": "",
                       "resource_group": "ALL", "aktualny": True}}
    for lg, name, role, dept in MANAGERS:
        users[lg] = {"password": pw, "role": role, "name": name, "hu": "", "dzial": dept,
                     "resource_group": "ALL", "aktualny": True}
    for first, last, dept, group, _ in WORKERS:
        who = code(first, last)
        users[login(first, last)] = {"password": pw, "role": "pracownik", "name": f"{first} {last}",
                                     "hu": "HU_" + who.replace(" ", "_"), "dzial": dept,
                                     "resource_group": group, "aktualny": rng.random() > 0.08}
    (out / "users.json").write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    days = sorted(df["data"].dt.date.unique())
    podstrefy = []
    for _ in range(10):
        first, last, dept, _, _ = rng.choice(WORKERS)
        d = rng.choice(days)
        podstrefy.append({
            "id": uuid.UUID(int=rng.getrandbits(128)).hex[:8],
            "timestamp": datetime.combine(d, time(15, rng.randint(0, 59))).isoformat(),
            "user": "lider.kpl", "user_name": "Jakub Lider", "dzial": dept, "data": d.isoformat(),
            "hu": "HU_" + code(first, last).replace(" ", "_"),
            "strefa_inne": f"00:{rng.randint(5, 40):02}:00", "strefa_zero": f"00:{rng.randint(0, 20):02}:00",
            "podstrefy": [{"podstrefa": p, "czas": f"00:{rng.randint(5, 30):02}:00"}
                          for p in rng.sample(PODSTREFY, rng.randint(1, 3))],
        })
    (out / "podstrefy.json").write_text(json.dumps(podstrefy, ensure_ascii=False, indent=2), encoding="utf-8")

    zgl = []
    for typ, status in [("bledna_strefa", "nowe"), ("brak_odbicia", "nowe"), ("nadmiar_czasu", "zaakceptowane"),
                        ("brak_czasu", "odrzucone"), ("bledna_strefa", "zaakceptowane"), ("inne", "nowe")]:
        first, last, dept, _, _ = rng.choice(WORKERS)
        d = rng.choice(days)
        done = status != "nowe"
        zgl.append({
            "id": uuid.UUID(int=rng.getrandbits(128)).hex[:8],
            "timestamp": datetime.combine(d, time(12, rng.randint(0, 59))).isoformat(),
            "zglaszajacy": login(first, last), "zglaszajacy_name": f"{first} {last}",
            "data_pracy": d.isoformat(), "pracownik": code(first, last), "typ_problemu": typ,
            "strefa_z": pick(rng, ZONES[dept]) if typ == "bledna_strefa" else "",
            "strefa_do": "STREFA_PICKING" if typ == "bledna_strefa" else "",
            "czas_korekty": "00:20:00" if typ == "bledna_strefa" else "",
            "strefa_brak": "STREFA_INNE" if typ in ("brak_odbicia", "brak_czasu") else "",
            "godz_wejscia": "09:10:00" if typ == "brak_odbicia" else "",
            "godz_wyjscia": "09:45:00" if typ == "brak_odbicia" else "",
            "strefa_nadmiar": "STREFA_ZERO" if typ == "nadmiar_czasu" else "",
            "czas_faktyczny": "00:10:00" if typ == "nadmiar_czasu" else "",
            "opis": "Przykładowe zgłoszenie (dane demo).", "status": status,
            "akceptowal": "kierownik" if done else None, "akceptowal_name": "Maria Kierownik" if done else None,
            "data_akceptacji": datetime.combine(d + timedelta(days=1), time(8, 30)).isoformat() if done else None,
        })
    (out / "zgloszenia.json").write_text(json.dumps(zgl, ensure_ascii=False, indent=2), encoding="utf-8")
    return df, users


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    df, users = build(ap.parse_args().out)
    print(f"czasy_calc.parquet: {len(df)} odcinków, {df['pracownik'].nunique()} pracowników, "
          f"{df['data'].min():%Y-%m-%d}…{df['data'].max():%Y-%m-%d}; users.json: {len(users)} kont "
          f"(hasło demo: {DEMO_PASSWORD})")
