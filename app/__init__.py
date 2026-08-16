import os
import logging
import click
from logging.handlers import RotatingFileHandler

from flask import Flask, redirect, request, url_for, flash, render_template
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
        "script-src": ["'self'", "https://cdn.tailwindcss.com",
                       "https://www.youtube.com", "https://www.youtube-nocookie.com", "'unsafe-inline'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "https://image.tmdb.org", "https://i.ytimg.com"],
        "connect-src": ["'self'"],
        "form-action": ["'self'"],
        "frame-src": ["https://www.youtube.com", "https://www.youtube-nocookie.com"],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'self'"],
    }
    Talisman(app, content_security_policy=csp, force_https=is_prod,
             strict_transport_security=is_prod)

    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.tmdb import tmdb_bp
    from app.routes.auth import auth_bp
    from app.routes.api import api_bp
    from app.routes.box import box_bp
    from app.routes.top import top_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tmdb_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    csrf.exempt(api_bp)
    app.register_blueprint(box_bp)
    app.register_blueprint(top_bp)

    @app.after_request
    def set_additional_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        response.headers.setdefault("Pragma", "no-cache")
        return response

    @app.before_request
    def enforce_https():
        if is_prod and request.headers.get("X-Forwarded-Proto", "http") != "https" and request.scheme != "https":
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_err(e):
        app.logger.exception("Internal server error")
        return render_template("500.html"), 500

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

        if db.engine.dialect.name == "sqlite":
            from sqlalchemy import inspect, text as sa_text
            inspector = inspect(db.engine)
            film_cols = [c["name"] for c in inspector.get_columns("films")]
            user_cols = [c["name"] for c in inspector.get_columns("users")]
            if "categorie" not in film_cols:
                db.session.execute(sa_text("ALTER TABLE films ADD COLUMN categorie VARCHAR(100) DEFAULT ''"))
            if "origine" not in film_cols:
                db.session.execute(sa_text("ALTER TABLE films ADD COLUMN origine VARCHAR(100) DEFAULT ''"))
            if "trailer" not in film_cols:
                db.session.execute(sa_text("ALTER TABLE films ADD COLUMN trailer VARCHAR(100) DEFAULT ''"))
            if "created_at" not in user_cols:
                db.session.execute(sa_text("ALTER TABLE users ADD COLUMN created_at DATETIME"))
            if "is_admin" not in user_cols:
                db.session.execute(sa_text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))

        admin_prenom = os.environ.get("ADMIN_PRENOM", "").strip()
        admin_pass = os.environ.get("ADMIN_PASS", "").strip()
        if admin_prenom and admin_pass:
            existing = User.query.filter_by(prenom=admin_prenom).first()
            if not existing:
                from werkzeug.security import generate_password_hash
                user = User(prenom=admin_prenom, password_hash=generate_password_hash(admin_pass), is_admin=True)
                db.session.add(user)
                db.session.commit()
                app.logger.info(f"Utilisateur '{admin_prenom}' créé depuis les variables d'environnement.")
            elif not existing.is_admin:
                existing.is_admin = True
                db.session.commit()
                app.logger.info(f"Utilisateur '{admin_prenom}' promu administrateur depuis les variables d'environnement.")

    @app.context_processor
    def inject_globals():
        from app.models import Film
        try:
            has = Film.query.filter(Film.trailer.isnot(None), Film.trailer != "").count() > 0
        except Exception:
            has = False
        return {"has_trailers": has}

    is_vercel = os.environ.get("VERCEL") == "1"
    worker_enabled = os.environ.get("TRAILER_WORKER", "1") == "1" and not is_vercel
    if worker_enabled:
        from app.trailers import start_trailer_worker
        start_trailer_worker(app)

    @app.cli.command("create-user")
    @click.argument("prenom")
    @click.argument("password")
    def create_user(prenom, password):
        with app.app_context():
            if len(prenom) < 2 or len(prenom) > 100:
                click.echo("Erreur : le prénom doit faire entre 2 et 100 caractères.")
                return
            if len(password) < 8:
                click.echo("Erreur : le mot de passe doit faire au moins 8 caractères.")
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

    @app.cli.command("make-admin")
    @click.argument("prenom")
    @click.argument("password", required=False)
    def make_admin(prenom, password):
        with app.app_context():
            user = User.query.filter_by(prenom=prenom).first()
            if user:
                user.is_admin = True
                db.session.commit()
                click.echo(f"L'utilisateur '{prenom}' est maintenant administrateur.")
                return
            if not password:
                click.echo(
                    f"L'utilisateur '{prenom}' n'existe pas. "
                    f"Fournis un mot de passe pour le créer : flask make-admin {prenom} MOTDEPASSE"
                )
                return
            if len(prenom) < 2 or len(prenom) > 100:
                click.echo("Erreur : le prénom doit faire entre 2 et 100 caractères.")
                return
            if len(password) < 8:
                click.echo("Erreur : le mot de passe doit faire au moins 8 caractères.")
                return
            from werkzeug.security import generate_password_hash
            user = User(prenom=prenom, password_hash=generate_password_hash(password), is_admin=True)
            db.session.add(user)
            db.session.commit()
            click.echo(f"Utilisateur administrateur '{prenom}' créé avec succès.")

    return app
