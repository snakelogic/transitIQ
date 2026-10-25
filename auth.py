"""Customer account storage and authentication helpers."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

_DUMMY_PASSWORD_HASH = generate_password_hash("transit-iq-invalid-account")


def connect():
    path = Path(current_app.config["CUSTOMER_DATABASE"])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 10000")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def execute(db, sql: str, params=()):
    """Run a local SQLite query."""
    return db.execute(sql, params)


def _memory_store() -> dict:
    return current_app.extensions["customer_memory_store"]


@contextmanager
def connection():
    db = connect()
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db() -> None:
    if current_app.config["CUSTOMER_STORAGE"] == "memory":
        current_app.extensions["customer_memory_store"] = {
            "customers": {}, "email_index": {}, "phone_index": {}, "next_id": 1, "lock": RLock()
        }
        return
    with connection() as db:
        execute(db, """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                phone TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def normalize_phone(value: str) -> str:
    value = value.strip()
    if value.startswith("+"):
        return "+" + re.sub(r"\D", "", value)
    return re.sub(r"\D", "", value)


def find_customer(identifier: str):
    identifier = identifier.strip()
    if current_app.config["CUSTOMER_STORAGE"] == "memory":
        store = _memory_store()
        key = identifier.casefold() if "@" in identifier else normalize_phone(identifier)
        index = store["email_index"] if "@" in identifier else store["phone_index"]
        with store["lock"]:
            customer_id = index.get(key)
            return dict(store["customers"][customer_id]) if customer_id else None
    if "@" in identifier:
        query, value = "email = ? COLLATE NOCASE", identifier.casefold()
    else:
        query, value = "phone = ?", normalize_phone(identifier)
    with connection() as db:
        customer = execute(
            db,
            f"SELECT id, full_name, email, phone, password_hash FROM customers WHERE {query}",
            (value,),
        ).fetchone()
    return customer


def create_customer(full_name: str, email: str, phone: str, password: str) -> int:
    if current_app.config["CUSTOMER_STORAGE"] == "memory":
        store = _memory_store()
        normalized_email = email.casefold()
        normalized_phone = normalize_phone(phone)
        password_hash = generate_password_hash(password)
        with store["lock"]:
            if normalized_email in store["email_index"] or normalized_phone in store["phone_index"]:
                raise sqlite3.IntegrityError("A customer with that email or phone already exists.")
            customer_id = store["next_id"]
            store["next_id"] += 1
            store["customers"][customer_id] = {
                "id": customer_id,
                "full_name": full_name,
                "email": normalized_email,
                "phone": normalized_phone,
                "password_hash": password_hash,
            }
            store["email_index"][normalized_email] = customer_id
            store["phone_index"][normalized_phone] = customer_id
            return customer_id
    with connection() as db:
        query = "INSERT INTO customers (full_name, email, phone, password_hash) VALUES (?, ?, ?, ?)"
        cursor = execute(
            db,
            query,
            (full_name, email.casefold(), normalize_phone(phone), generate_password_hash(password)),
        )
        return int(cursor.lastrowid)


def get_customer(customer_id: int):
    if current_app.config["CUSTOMER_STORAGE"] == "memory":
        store = _memory_store()
        with store["lock"]:
            customer = store["customers"].get(customer_id)
            return dict(customer) if customer else None
    with connection() as db:
        return execute(
            db, "SELECT id, full_name, email FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()


def verify_password(customer, password: str) -> bool:
    candidate = password[:128]
    stored_hash = customer["password_hash"] if customer else _DUMMY_PASSWORD_HASH
    valid = check_password_hash(stored_hash, candidate)
    return bool(customer and len(password) <= 128 and valid)


def public_customer(customer) -> dict:
    return {"id": customer["id"], "full_name": customer["full_name"], "email": customer["email"]}
