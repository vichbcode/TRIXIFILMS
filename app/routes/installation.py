import os

from flask import Blueprint, render_template, send_from_directory, current_app

installation_bp = Blueprint("installation", __name__)

_APK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "static", "downloads")
_APK_NAME = "trixifilms-1.0.0.apk"


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


@installation_bp.route("/installation/download")
def download():
    available, _ = _apk_info()
    if not available:
        return render_template("404.html"), 404
    return send_from_directory(
        _APK_DIR, _APK_NAME, as_attachment=True,
        download_name="TRIXIFILMS-1.0.0.apk",
        mimetype="application/vnd.android.package-archive")
