from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import create_app
from auth import find_customer
from werkzeug.security import check_password_hash


class CustomerAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "customers.sqlite3"
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-not-for-production",
            "CUSTOMER_DATABASE": str(self.database),
            "SESSION_COOKIE_SECURE": False,
        })
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf(self, page: str) -> str:
        response = self.client.get(page)
        self.assertEqual(response.status_code, 200)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(token)
        return token.group(1).decode()

    def signup(self, **overrides):
        values = {
            "full_name": "Asha Sharma",
            "phone": "+91 98765 43210",
            "email": "asha@example.com",
            "password": "correct-horse-battery-17",
            "confirm_password": "correct-horse-battery-17",
        }
        values.update(overrides)
        values["csrf_token"] = self.csrf("/signup")
        return self.client.post("/signup", data=values, follow_redirects=False)

    def test_registration_hashes_password_and_redirects_to_protected_dashboard(self):
        response = self.signup()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

        with closing(sqlite3.connect(self.database)) as db:
            full_name, password_hash = db.execute(
                "SELECT full_name, password_hash FROM customers WHERE email = ?", ("asha@example.com",)
            ).fetchone()
        self.assertEqual(full_name, "Asha Sharma")
        self.assertNotEqual(password_hash, "correct-horse-battery-17")
        self.assertTrue(check_password_hash(password_hash, "correct-horse-battery-17"))

        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"WELCOME BACK, ASHA", dashboard.data)
        self.assertIn(b"id=\"transit-map\"", dashboard.data)

    def test_dashboard_redirects_unauthenticated_customer_to_login(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/dashboard", response.headers["Location"])

    def test_public_landing_page_offers_account_and_tracking_paths(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create account", response.data)
        self.assertIn(b"Log in", response.data)
        self.assertIn(b"Track your bus", response.data)

    def test_session_cookie_uses_http_only_and_same_site_defaults(self):
        with self.client.application.app_context():
            self.assertTrue(self.client.application.config["SESSION_COOKIE_HTTPONLY"])
            self.assertEqual(self.client.application.config["SESSION_COOKIE_SAMESITE"], "Lax")
            self.assertFalse(self.client.application.config["SESSION_COOKIE_SECURE"])

    def test_duplicate_email_is_rejected_with_friendly_message(self):
        self.signup()
        self.client.post("/logout", data={"csrf_token": self.csrf("/dashboard")})
        response = self.signup(phone="+91 91234 56789")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"An account with that email or mobile number already exists", response.data)

    def test_login_accepts_mobile_number_and_logout_clears_session(self):
        self.signup()
        self.client.post("/logout", data={"csrf_token": self.csrf("/dashboard")})
        response = self.client.post("/login", data={
            "csrf_token": self.csrf("/login"),
            "identifier": "+91 98765 43210",
            "password": "correct-horse-battery-17",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

        logout_token = self.csrf("/dashboard")
        response = self.client.post("/logout", data={"csrf_token": logout_token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_external_redirect_target_is_ignored(self):
        self.signup()
        self.client.post("/logout", data={"csrf_token": self.csrf("/dashboard")})
        token = self.csrf("/login?next=https://example.com")
        response = self.client.post(
            "/login?next=https://example.com",
            data={
                "csrf_token": token,
                "identifier": "asha@example.com",
                "password": "correct-horse-battery-17",
                "next": "https://example.com",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

    def test_invalid_csrf_is_rejected(self):
        response = self.client.post("/signup", data={"csrf_token": "bad"})
        self.assertEqual(response.status_code, 400)

    def test_memory_accounts_work_without_a_database_and_reset_with_the_process(self):
        database = Path(self.temp_dir.name) / "unused.sqlite3"
        memory_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-not-for-production",
            "CUSTOMER_STORAGE": "memory",
            "CUSTOMER_DATABASE": str(database),
            "SESSION_COOKIE_SECURE": False,
        })
        client = memory_app.test_client()
        page = client.get("/signup")
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        response = client.post("/signup", data={
            "csrf_token": token,
            "full_name": "Asha Sharma",
            "phone": "+91 98765 43210",
            "email": "asha@example.com",
            "password": "correct-horse-battery-17",
            "confirm_password": "correct-horse-battery-17",
        })
        self.assertEqual(response.headers["Location"], "/dashboard")
        self.assertEqual(client.get("/dashboard").status_code, 200)
        self.assertFalse(database.exists())

        restarted_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-not-for-production",
            "CUSTOMER_STORAGE": "memory",
            "CUSTOMER_DATABASE": str(database),
            "SESSION_COOKIE_SECURE": False,
        })
        with restarted_app.app_context():
            self.assertIsNone(find_customer("asha@example.com"))


if __name__ == "__main__":
    unittest.main()
