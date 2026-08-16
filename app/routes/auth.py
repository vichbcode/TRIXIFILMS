from datetime import datetime
from urllib.parse import urlsplit

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, current_app
)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import login_user, logout_user, login_required, current_user

from app.models import db, User, Box, TopFilm

auth_bp = Blueprint("auth", __name__)

_login_attempts = {}
_register_attempts = {}

PASSWORD_MIN = 8
REGISTER_THRESHOLD = 5
REGISTER_WINDOW = 600


def _safe_next(target, default="main.index"):
    """Évite les open-redirect : ne redirige que vers un chemin local au site."""
    if not target:
        return url_for(default)
    parts = urlsplit(target)
    if parts.scheme and parts.scheme not in ("http", "https"):
        return url_for(default)
    if parts.netloc and parts.netloc != request.host:
        return url_for(default)
    return target


def record_login_attempt(ip, success=False):
    threshold = current_app.config.get("LOCKOUT_THRESHOLD", 8)
    window = current_app.config.get("LOCKOUT_WINDOW", 900)
    duration = current_app.config.get("LOCKOUT_DURATION", 1800)
    now = datetime.utcnow().timestamp()
    rec = _login_attempts.get(ip, {"attempts": [], "locked_until": 0})
    rec["attempts"] = [t for t in rec["attempts"] if now - t < window]
    rec["attempts"].append(now)
    if success:
        rec["attempts"] = []
        rec["locked_until"] = 0
    else:
        if len(rec["attempts"]) >= threshold:
            rec["locked_until"] = now + duration
    _login_attempts[ip] = rec


def is_locked_out(ip):
    rec = _login_attempts.get(ip)
    if not rec:
        return False
    now = datetime.utcnow().timestamp()
    return rec.get("locked_until", 0) > now


def _register_blocked(ip):
    now = datetime.utcnow().timestamp()
    rec = _register_attempts.get(ip, [])
    rec = [t for t in rec if now - t < REGISTER_WINDOW]
    _register_attempts[ip] = rec
    if len(rec) >= REGISTER_THRESHOLD:
        return True
    rec.append(now)
    _register_attempts[ip] = rec
    return False


@auth_bp.route("/auth/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    ip = request.remote_addr or "unknown"
    if is_locked_out(ip):
        flash("Trop d'essais échoués. Réessaye plus tard.", "error")
        return redirect(_safe_next(request.referrer))

    prenom = (request.form.get("prenom") or "").strip()
    password = (request.form.get("password") or "").strip()

    if not prenom or not password:
        record_login_attempt(ip, success=False)
        flash("Prénom et mot de passe requis.", "error")
        return redirect(_safe_next(request.referrer))

    user = User.query.filter_by(prenom=prenom).first()
    if not user or not check_password_hash(user.password_hash, password):
        record_login_attempt(ip, success=False)
        flash("Prénom ou mot de passe incorrect.", "error")
        return redirect(_safe_next(request.referrer))

    login_user(user, remember=True)
    record_login_attempt(ip, success=True)
    flash(f"Connecté(e) en tant que {user.prenom}.", "success")
    return redirect(_safe_next(request.referrer))


@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    logout_user()
    flash("Déconnecté(e).", "success")
    return redirect(_safe_next(request.referrer))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        prenom = (request.form.get("prenom") or "").strip()
        password = (request.form.get("password") or "").strip()
        if not prenom:
            flash("Le prénom ne peut pas être vide.", "error")
            return redirect(url_for("auth.account"))
        if len(prenom) < 2 or len(prenom) > 100:
            flash("Le prénom doit faire entre 2 et 100 caractères.", "error")
            return redirect(url_for("auth.account"))
        if prenom != current_user.prenom:
            existing = User.query.filter_by(prenom=prenom).first()
            if existing:
                flash("Ce prénom est déjà pris.", "error")
                return redirect(url_for("auth.account"))
        current_user.prenom = prenom
        if password:
            if len(password) < PASSWORD_MIN:
                flash(f"Le mot de passe doit faire au moins {PASSWORD_MIN} caractères.", "error")
                return redirect(url_for("auth.account"))
            current_user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash("Compte modifié avec succès.", "success")
        return redirect(url_for("auth.account"))
    box_count = Box.query.filter_by(user_id=current_user.id).count()
    top_count = TopFilm.query.filter_by(user_id=current_user.id).count()
    return render_template("account.html", box_count=box_count, top_count=top_count)


@auth_bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    uid = current_user.id
    user = db.session.get(User, uid)
    if user:
        db.session.delete(user)
        db.session.commit()
    logout_user()
    flash("Votre compte a été supprimé. Au revoir !", "success")
    return redirect(url_for("main.index"))


@auth_bp.route("/auth/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if _register_blocked(ip):
            flash("Trop d'inscriptions depuis cette IP. Réessaye plus tard.", "error")
            return redirect(url_for("auth.register"))
        prenom = (request.form.get("prenom") or "").strip()
        password = (request.form.get("password") or "").strip()
        if not prenom or not password:
            flash("Prénom et mot de passe requis.", "error")
            return redirect(url_for("auth.register"))
        if len(prenom) < 2 or len(prenom) > 100:
            flash("Le prénom doit faire entre 2 et 100 caractères.", "error")
            return redirect(url_for("auth.register"))
        if len(password) < PASSWORD_MIN:
            flash(f"Le mot de passe doit faire au moins {PASSWORD_MIN} caractères.", "error")
            return redirect(url_for("auth.register"))
        existing = User.query.filter_by(prenom=prenom).first()
        if existing:
            flash("Ce prénom est déjà pris.", "error")
            return redirect(url_for("auth.register"))
        user = User(prenom=prenom, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash(f"Bienvenue {prenom} ! Compte créé et connecté.", "success")
        return redirect(url_for("main.index"))
    return render_template("register.html")
