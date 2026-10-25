"""Customer registration, login and logout views."""

from __future__ import annotations

import hmac
import re
import sqlite3
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from auth import create_customer, find_customer, normalize_phone, public_customer, verify_password

auth = Blueprint("auth", __name__)


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        import secrets

        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> None:
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="Your form expired. Please reload the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user is None:
            flash("Please log in to open your dashboard.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def _safe_next(value: str | None) -> str:
    if value:
        try:
            target = urlsplit(value)
        except ValueError:
            target = None
        if target and not target.scheme and not target.netloc and target.path.startswith("/"):
            if not target.path.startswith("//") and "\\" not in target.path and not any(ord(char) < 32 for char in value):
                return value
    return url_for("dashboard")


@auth.app_context_processor
def inject_auth_helpers():
    return {"csrf_token": csrf_token}


@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        validate_csrf()
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        customer = find_customer(identifier) if identifier else None
        if not verify_password(customer, password):
            flash("We couldn’t find a matching account and password. Check your details and try again.", "error")
        else:
            session.clear()
            session.permanent = request.form.get("remember") == "on"
            session["customer_id"] = customer["id"]
            session["csrf_token"] = csrf_token()
            return redirect(_safe_next(request.args.get("next") or request.form.get("next")))
    return render_template("login.html", next_url=request.args.get("next", ""))


@auth.route("/signup", methods=["GET", "POST"])
def signup():
    if g.current_user:
        return redirect(url_for("dashboard"))
    values = {"full_name": "", "phone": "", "email": ""}
    if request.method == "POST":
        validate_csrf()
        values = {key: request.form.get(key, "").strip() for key in values}
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        digits = normalize_phone(values["phone"]).lstrip("+")
        errors = []
        if not 2 <= len(values["full_name"]) <= 80 or any(ord(char) < 32 for char in values["full_name"]):
            errors.append("Enter your name (2–80 characters).")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"]) or len(values["email"]) > 254:
            errors.append("Enter a valid email address.")
        if not re.fullmatch(r"\+?[0-9\s().-]+", values["phone"]):
            errors.append("Enter a valid mobile number using digits and an optional leading +.")
        if not 7 <= len(digits) <= 15:
            errors.append("Enter a valid mobile number with 7–15 digits.")
        if len(password) < 10 or len(password) > 128:
            errors.append("Use a password between 10 and 128 characters.")
        if password != confirmation:
            errors.append("The passwords don’t match.")
        for error in errors:
            flash(error, "error")
        if not errors:
            try:
                customer_id = create_customer(values["full_name"], values["email"], values["phone"], password)
            except sqlite3.IntegrityError:
                flash("An account with that email or mobile number already exists. Try logging in instead.", "error")
            else:
                session.clear()
                session.permanent = True
                session["customer_id"] = customer_id
                session["csrf_token"] = csrf_token()
                flash("Your account is ready. Welcome to TransitIQ!", "success")
                return redirect(url_for("dashboard"))
    return render_template("signup.html", values=values)


@auth.post("/logout")
def logout():
    validate_csrf()
    session.clear()
    flash("You’ve been logged out.", "success")
    return redirect(url_for("home"))
