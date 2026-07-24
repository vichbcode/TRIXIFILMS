from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, current_app
)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import login_user, logout_user, login_required, current_user

from app.models import db, User

auth_bp = Blueprint("auth", __name__)

_login_attempts = {}


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


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    if is_locked_out(ip):
        flash("Trop d'essais échoués. Réessaye plus tard.", "error")
        return redirect(request.referrer or url_for("main.index"))

    prenom = (request.form.get("prenom") or "").strip()
    password = (request.form.get("password") or "").strip()

    if not prenom or not password:
        record_login_attempt(ip, success=False)
        flash("Prénom et mot de passe requis.", "error")
        return redirect(request.referrer or url_for("main.index"))

    user = User.query.filter_by(prenom=prenom).first()
    if not user or not check_password_hash(user.password_hash, password):
        record_login_attempt(ip, success=False)
        flash("Prénom ou mot de passe incorrect.", "error")
        return redirect(request.referrer or url_for("main.index"))

    login_user(user, remember=True)
    record_login_attempt(ip, success=True)
    flash(f"Connecté(e) en tant que {user.prenom}.", "success")
    return redirect(request.referrer or url_for("main.index"))


@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    logout_user()
    flash("Déconnecté(e).", "success")
    return redirect(request.referrer or url_for("main.index"))


@auth_bp.route("/auth/register", methods=["GET", "POST"])
@login_required
def register():
    if request.method == "POST":
        prenom = (request.form.get("prenom") or "").strip()
        password = (request.form.get("password") or "").strip()
        if not prenom or not password:
            flash("Prénom et mot de passe requis.", "error")
            return redirect(url_for("auth.register"))
        if len(prenom) < 2 or len(prenom) > 100:
            flash("Le prénom doit faire entre 2 et 100 caractères.", "error")
            return redirect(url_for("auth.register"))
        if len(password) < 6:
            flash("Le mot de passe doit faire au moins 6 caractères.", "error")
            return redirect(url_for("auth.register"))
        existing = User.query.filter_by(prenom=prenom).first()
        if existing:
            flash("Ce prénom est déjà pris.", "error")
            return redirect(url_for("auth.register"))
        user = User(prenom=prenom, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash(f"Utilisateur '{prenom}' créé avec succès.", "success")
        return redirect(url_for("main.index"))
    return render_template("register.html")
