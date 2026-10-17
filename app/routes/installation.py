import hmac
import os
import time

import requests as http_req
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash)

from app.api_rate_limit import check_rate_limit
from app.models import db, Suggestion

installation_bp = Blueprint("installation", __name__)

_RELEASES_API = ("https://api.github.com/repos/vichbcode/TRIXIFILMS/"
                 "releases/latest")
_DOWNLOAD_URL = ("https://github.com/vichbcode/TRIXIFILMS/releases/"
                 "latest/download/TRIXIFILMS.apk")

_release_cache = {"data": None, "ts": 0.0}


def _admin_password():
    """Mot de passe admin lu depuis l'environnement (jamais code en dur)."""
    return os.environ.get("INSTALL_ADMIN_PASSWORD", "")


def _release_info():
    """(version, taille Mo) de la derniere release GitHub, cache 10 min."""
    now = time.time()
    if _release_cache["data"] is None or now - _release_cache["ts"] > 600:
        try:
            r = http_req.get(_RELEASES_API, timeout=8, headers={
                "Accept": "application/vnd.github+json"})
            r.raise_for_status()
            data = r.json()
            tag = (data.get("tag_name") or "").lstrip("vV")
            size = 0.0
            for a in data.get("assets") or []:
                if (a.get("name") or "").endswith(".apk"):
                    size = round((a.get("size") or 0) / (1024 * 1024), 1)
                    break
            if tag:
                _release_cache["data"] = (tag, size)
                _release_cache["ts"] = now
        except Exception:
            pass
    return _release_cache["data"] or (None, 0.0)


@installation_bp.route("/installation")
def installation():
    version, size_mb = _release_info()
    return render_template("installation.html",
                           title="Installer l'application",
                           apk_version=version, apk_size=size_mb)


@installation_bp.route("/installation/download")
def download():
    """Redirige toujours vers la derniere APK publiee en GitHub Releases."""
    return redirect(_DOWNLOAD_URL, code=302)


@installation_bp.route("/installation", methods=["POST"])
def suggest():
    allowed, retry = check_rate_limit("install_suggest", 5, 600, 1800)
    if not allowed:
        flash(f"Trop de suggestions envoyees. Reessaye dans {retry}s.", "error")
        return redirect(url_for("installation.installation") + "#suggestion")
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
    allowed, retry = check_rate_limit("install_admin", 5, 900, 1800)
    if not allowed:
        flash(f"Trop de tentatives. Reessaye dans {retry}s.", "error")
        return redirect(url_for("installation.admin"))
    expected = _admin_password()
    password = request.form.get("password", "")
    if not expected:
        flash("Administration desactivee (mot de passe non configure).", "error")
        return redirect(url_for("installation.admin"))
    if hmac.compare_digest(password, expected):
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
