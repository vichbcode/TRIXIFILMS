import time

import requests as http_req
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash)

from app.models import db, Suggestion

installation_bp = Blueprint("installation", __name__)

_RELEASES_API = ("https://api.github.com/repos/vichbcode/TRIXIFILMS/"
                 "releases/latest")
_DOWNLOAD_URL = ("https://github.com/vichbcode/TRIXIFILMS/releases/"
                 "latest/download/TRIXIFILMS.apk")
_ADMIN_PASSWORD = "zogixa95@#"

_release_cache = {"data": None, "ts": 0.0}


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
