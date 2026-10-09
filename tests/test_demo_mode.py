"""Publiczne demo (DEMO_MODE=1): jawne konto kierownika nie może ustawiać SMTP ani wysyłać poczty z serwera.

Uruchomienie: python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("FLASK_SECRET_KEY", "test")

import app as timer  # noqa: E402
from generate_demo_data import DEMO_PASSWORD, build  # noqa: E402


class DemoModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        build(data)
        self.patches = [mock.patch.multiple(timer, DATA_DIR=data, PARQUET=data / "czasy_calc.parquet",
                                            USERS_FILE=data / "users.json", SMTP_FILE=data / "smtp_config.json",
                                            DEMO_MODE=True)]
        for p in self.patches:
            p.start()
        timer._df_cache.update(df=None, mtime=0)
        self.c = timer.app.test_client()
        self.c.post("/", data={"username": "kierownik", "password": DEMO_PASSWORD})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_smtp_settings_cannot_be_saved(self):
        r = self.c.post("/ustawienia", data={"server": "10.0.0.1", "port": "25", "user": "x", "enabled": "1",
                                             "test": "1"}, follow_redirects=True)
        self.assertIn("demo", r.get_data(as_text=True).lower())
        self.assertFalse(timer.SMTP_FILE.exists() and "10.0.0.1" in timer.SMTP_FILE.read_text(encoding="utf-8"))

    def test_no_mail_leaves_the_server(self):
        timer.SMTP_FILE.write_text(json.dumps({"enabled": True, "user": "u", "server": "10.0.0.1", "port": 25,
                                               "password": "p", "from": "", "kierownicy_email": ["a@b.c"]}))
        with mock.patch("smtplib.SMTP") as smtp:
            self.assertFalse(timer.send_email_alert("x", "y"))
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
