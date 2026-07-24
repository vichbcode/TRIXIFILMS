from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from app.models import db, Film, Actor, Rating, Message

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    flash("Utilisez le formulaire d'authentification sur la page du film pour vous connecter.", "error")
    return redirect(url_for("main.index"))


@admin_bp.route("/admin/logout")
@login_required
def logout():
    flash("Utilisez le bouton de déconnexion sur la page du film.", "error")
    return redirect(url_for("main.index"))


@admin_bp.route("/admin/clear_films", methods=["POST"])
@login_required
def clear_films():
    flash("Fonction désactivée.", "error")
    return redirect(url_for("main.index"))
