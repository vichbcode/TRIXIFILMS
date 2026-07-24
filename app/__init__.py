import os
import logging
import click
from logging.handlers import RotatingFileHandler

from flask import Flask, redirect, request, url_for, flash
from flask_wtf.csrf import CSRFError
from flask_login import LoginManager
from flask_wtf import CSRFProtect

from app.models import db, User


login_manager = LoginManager()
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def create_app():
    from app.config import Config
    from flask_talisman import Talisman

    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    env = os.environ.get("FLASK_ENV", "development")
    is_prod = env == "production"

    app.config.from_object(Config)

    if Config.SECRET_KEY:
        app.secret_key = Config.SECRET_KEY
    else:
        import secrets
        app.secret_key = secrets.token_hex(32)
        app.logger.warning("FLASK_SECRET not set - using auto-generated key (sessions will reset on restart)")

    db.init_app(app)
    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."

    csp = {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://cdn.tailwindcss.com", "'unsafe-inline'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
    }
    Talisman(app, content_security_policy=csp, force_https=is_prod,
             strict_transport_security=is_prod)

    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.tmdb import tmdb_bp
    from app.routes.auth import auth_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tmdb_bp)
    app.register_blueprint(auth_bp)

    @app.after_request
    def set_additional_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=()")
        response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        response.headers.setdefault("Pragma", "no-cache")
        return response

    @app.before_request
    def enforce_https():
        if is_prod and request.headers.get("X-Forwarded-Proto", "http") != "https" and request.scheme != "https":
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    @app.errorhandler(404)
    def not_found(e):
        return app.jinja_env.get_template("404.html").render(), 404

    @app.errorhandler(500)
    def internal_err(e):
        app.logger.exception("Internal server error")
        return app.jinja_env.get_template("500.html").render(), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        app.logger.warning(f"CSRF error: {e.description}")
        flash("Formulaire invalide (CSRF). Recharge la page et réessaie.", "error")
        return redirect(request.referrer or url_for("main.index"))

    try:
        if not os.path.exists("logs"):
            os.makedirs("logs", exist_ok=True)
        handler = RotatingFileHandler("logs/app.log", maxBytes=10 * 1024 * 1024, backupCount=5)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
        ))
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
    except Exception:
        pass

    with app.app_context():
        db.create_all()

        from sqlalchemy import inspect, text as sa_text
        inspector = inspect(db.engine)
        film_cols = [c["name"] for c in inspector.get_columns("films")]
        actor_cols = [c["name"] for c in inspector.get_columns("acteurs")]
        if "image_data" not in film_cols:
            db.session.execute(sa_text("ALTER TABLE films ADD COLUMN image_data BLOB"))
            db.session.execute(sa_text("ALTER TABLE films ADD COLUMN image_mime VARCHAR(50) DEFAULT ''"))
        if "image_data" not in actor_cols:
            db.session.execute(sa_text("ALTER TABLE acteurs ADD COLUMN image_data BLOB"))
            db.session.execute(sa_text("ALTER TABLE acteurs ADD COLUMN image_mime VARCHAR(50) DEFAULT ''"))

        admin_prenom = os.environ.get("ADMIN_PRENOM", "").strip()
        admin_pass = os.environ.get("ADMIN_PASS", "").strip()
        if admin_prenom and admin_pass:
            existing = User.query.filter_by(prenom=admin_prenom).first()
            if not existing:
                from werkzeug.security import generate_password_hash
                user = User(prenom=admin_prenom, password_hash=generate_password_hash(admin_pass))
                db.session.add(user)
                db.session.commit()
                app.logger.info(f"Utilisateur '{admin_prenom}' créé depuis les variables d'environnement.")

    @app.cli.command("create-user")
    @click.argument("prenom")
    @click.argument("password")
    def create_user(prenom, password):
        with app.app_context():
            if len(prenom) < 2 or len(prenom) > 100:
                click.echo("Erreur : le prénom doit faire entre 2 et 100 caractères.")
                return
            if len(password) < 6:
                click.echo("Erreur : le mot de passe doit faire au moins 6 caractères.")
                return
            existing = User.query.filter_by(prenom=prenom).first()
            if existing:
                click.echo(f"Erreur : l'utilisateur '{prenom}' existe déjà.")
                return
            from werkzeug.security import generate_password_hash
            user = User(prenom=prenom, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            click.echo(f"Utilisateur '{prenom}' créé avec succès.")

    return app
