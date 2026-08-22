import os
import secrets

from flask import (Blueprint, render_template, request, redirect,
                   url_for, send_from_directory, session, flash)

from app.models import db, Suggestion

installation_bp = Blueprint("installation", __name__)

_APK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "static", "downloads")
_APK_NAME = "trixifilms-1.0.0.apk"
_ADMIN_PASSWORD = "zogixa95@#"


def _apk_info():
    path = os.path.join(_APK_DIR, _APK_NAME)
    if not os.path.exists(path):
        return False, None
    return True, round(os.path.getsize(path) / (1024 * 1024), 1)


@installation_bp.route("/installation")
def installation():
    available, size_mb = _apk_info()
    return render_template("installation.html", title="Installer l'application",
                           apk_available=available, apk_size=size_mb)


@installation_bp.route("/installation", methods=["POST"])
def suggest():
    message = request.form.get("message", "").strip()
    if not message:
        flash("Tu dois ecrire quelque chose.", "error")
        return redirect(url_for("installation.installation") + "#suggestion")
    if len(message) > 2000:
        message = message[:2000]
    s = Suggestion(message=message)
    db.session.add(s)
    db.session.commit()
    flash("Merci pour ta suggestion !", "success")
    return redirect(url_for("installation.installation") + "#suggestion")


@installation_bp.route("/installation/admin")
def admin():
    if not session.get("inst_admin"):
        return render_template("installation_admin.html",
                               title="Administration")
    suggestions = Suggestion.query.order_by(Suggestion.created_at.desc()).all()
    return render_template("installation_admin.html",
                           title="Suggestions",
                           suggestions=suggestions,
                           logged_in=True)


@installation_bp.route("/installation/admin", methods=["POST"])
def admin_login():
    password = request.form.get("password", "")
    if password == _ADMIN_PASSWORD:
        session["inst_admin"] = True
        session.permanent = True
        suggestions = Suggestion.query.order_by(Suggestion.created_at.desc()).all()
        return render_template("installation_admin.html",
                               title="Suggestions",
                               suggestions=suggestions,
                               logged_in=True)
    flash("Mot de passe incorrect.", "error")
    return redirect(url_for("installation.admin"))


@installation_bp.route("/installation/admin/logout")
def admin_logout():
    session.pop("inst_admin", None)
    return redirect(url_for("installation.admin"))


@installation_bp.route("/installation/download")
def download():
    available, _ = _apk_info()
    if not available:
        return render_template("404.html"), 404
    return send_from_directory(
        _APK_DIR, _APK_NAME, as_attachment=True,
        download_name="TRIXIFILMS-1.0.0.apk",
        mimetype="application/vnd.android.package-archive")
