"""Zakres widoczności danych wg roli: pracownik → tylko swoje, lider → swój dział, kierownik → wszyscy.

Uruchomienie: python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("FLASK_SECRET_KEY", "test")

import pandas as pd  # noqa: E402

import app as timer  # noqa: E402
from generate_demo_data import DEMO_PASSWORD, build  # noqa: E402

OWN = "KOWALSKI JAN"      # konto JKOWALSKI, Dział_Kompletacji
OTHER = "MAZUR KRZ"       # Dział_Wysyłek_B


class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        data = Path(cls.tmp.name)
        df, users = build(data)
        cls.all_workers = set(df["pracownik"])
        cls.kpl = {v["hu"][3:].replace("_", " ") for v in users.values()
                   if v["dzial"] == "Dział_Kompletacji" and v["role"] == "pracownik"}
        timer.DATA_DIR, timer.PARQUET = data, data / "czasy_calc.parquet"
        timer.USERS_FILE, timer.ZGLOS_FILE = data / "users.json", data / "zgloszenia.json"
        timer.PODSTR_FILE = data / "podstrefy.json"
        timer._df_cache.update(df=None, mtime=0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def client(self, login):
        c = timer.app.test_client()
        r = c.post("/", data={"username": login, "password": DEMO_PASSWORD})
        self.assertEqual(r.status_code, 302, login)
        return c

    def visible(self, c, path):
        body = c.get(path).get_data(as_text=True)
        return {w for w in self.all_workers if w in body}

    def test_worker_sees_only_own_data(self):
        c = self.client("JKOWALSKI")
        for path in ("/szczegoly", "/kpi", "/dashboard", f"/pracownik?q={OTHER.split()[0]}"):
            self.assertLessEqual(self.visible(c, path), {OWN}, path)
        csv = c.get("/eksport").get_data(as_text=True)
        self.assertNotIn(OTHER, csv)
        self.assertIn(OWN, csv)

    def test_worker_cannot_query_other_hu(self):
        c = self.client("JKOWALSKI")
        day = pd.read_parquet(timer.PARQUET).query("pracownik == @OTHER")["data"].iloc[0]
        r = c.get(f"/api/inne_zero?hu=HU_{OTHER.replace(' ', '_')}&data={day:%Y-%m-%d}").get_json()
        self.assertEqual(r["total_s"], 0)

    def test_worker_sees_only_own_complaints(self):
        c = self.client("JKOWALSKI")
        body = c.get("/zgloszenia").get_data(as_text=True)
        z = pd.read_json(timer.ZGLOS_FILE)
        others = z.query("zglaszajacy != 'JKOWALSKI' and pracownik != @OWN")
        self.assertFalse(others.empty)
        for name in others["zglaszajacy_name"]:
            self.assertNotIn(name, body)
        self.assertLessEqual(self.visible(c, "/zgloszenia"), {OWN})

    def test_leader_sees_own_department(self):
        c = self.client("lider.kpl")
        seen = self.visible(c, "/szczegoly")
        self.assertTrue(seen)
        self.assertLessEqual(seen, self.kpl)

    def test_manager_sees_everyone(self):
        c = self.client("kierownik")
        self.assertEqual(self.visible(c, "/szczegoly"), self.all_workers)

    # Regresja #1: odznaka „🔑 Lider” tylko dla roli lider.
    def test_worker_has_no_leader_badge(self):
        body = self.client("JKOWALSKI").get("/szczegoly").get_data(as_text=True)
        self.assertNotIn("🔑 Lider", body)

    def test_leader_has_leader_badge(self):
        body = self.client("lider.kpl").get("/szczegoly").get_data(as_text=True)
        self.assertIn("🔑 Lider", body)

if __name__ == "__main__":
    unittest.main()

