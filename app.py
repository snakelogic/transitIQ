"""Application entry point for the Smart Bus Operations dashboard."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, session, url_for
from dotenv import load_dotenv
from auth import get_customer, init_db, public_customer
from auth_routes import auth, login_required
from transit.routes import api

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        CUSTOMER_STORAGE=os.environ.get("CUSTOMER_STORAGE", "sqlite").lower(),
        CUSTOMER_DATABASE=os.environ.get("CUSTOMER_DATABASE_PATH", str(Path(app.instance_path) / "customers.sqlite3")),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
        or os.environ.get("APP_ENV", "development").lower() == "production",
    )
    secret_key = os.environ.get("SECRET_KEY") or (test_config or {}).get("SECRET_KEY")
    if not secret_key and os.environ.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("Set SECRET_KEY to a long random value in production.")
    if os.environ.get("APP_ENV", "development").lower() == "production" and (test_config or {}).get("CUSTOMER_STORAGE", os.environ.get("CUSTOMER_STORAGE", "sqlite")).lower() != "memory":
        raise RuntimeError("Set CUSTOMER_STORAGE=memory in production when using ephemeral hosting.")
    if secret_key and os.environ.get("APP_ENV", "development").lower() == "production" and len(secret_key) < 32:
        raise RuntimeError("SECRET_KEY must be at least 32 characters in production.")
    if not secret_key:
        # Persist a random local-development secret without committing it to source control.
        instance = Path(app.instance_path)
        instance.mkdir(parents=True, exist_ok=True)
        secret_file = instance / ".secret_key"
        try:
            secret_key = secret_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            generated = secrets.token_hex(32)
            try:
                with secret_file.open("x", encoding="utf-8") as handle:
                    handle.write(generated)
                secret_file.chmod(0o600)
                secret_key = generated
            except FileExistsError:
                secret_key = secret_file.read_text(encoding="utf-8").strip()
    app.config["SECRET_KEY"] = secret_key
    if test_config:
        app.config.update(test_config)
    if app.config["CUSTOMER_STORAGE"] not in {"sqlite", "memory"}:
        raise RuntimeError("CUSTOMER_STORAGE must be either 'sqlite' or 'memory'.")
    with app.app_context():
        init_db()
    app.register_blueprint(api, url_prefix="/api/v1")
    app.register_blueprint(auth)

    @app.before_request
    def load_current_customer():
        customer_id = session.get("customer_id")
        g.current_user = None
        if customer_id is None:
            return
        customer = get_customer(customer_id)
        if customer is None:
            session.clear()
        else:
            g.current_user = public_customer(customer)

    @app.context_processor
    def inject_current_customer():
        return {"current_user": g.get("current_user")}

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; font-src 'self' https://fonts.gstatic.com https://unpkg.com; script-src 'self' https://unpkg.com; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'")
        return response

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", message=getattr(error, "description", None)), 400

    @app.get("/")
    def home():
        if g.current_user:
            return redirect(url_for("dashboard"))
        return render_template("landing.html")

    @app.get("/dashboard")
    @login_required
    def dashboard():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="smart-bus-api", version="0.1.0")

    return app


app = create_app()


if __name__ == "__main__":
    # Debug mode is intentionally opt-in. Use a production WSGI server for deployment.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
