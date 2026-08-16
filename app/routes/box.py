from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.models import db, Box, BoxFilm, Film
from app.utils import film_to_dict

box_bp = Blueprint("box", __name__)


@box_bp.route("/box")
def box_list():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    per_page = 12

    query = Box.query.filter_by(is_public=True)
    if q:
        query = query.filter(Box.nom.ilike(f"%{q}%"))
    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    boxs = query.order_by(Box.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return render_template("box_list.html", boxs=boxs, query=q, page=page, total_pages=total_pages)


@box_bp.route("/box/mine")
@login_required
def my_boxs():
    boxs = Box.query.filter_by(user_id=current_user.id).order_by(Box.created_at.desc()).all()
    return render_template("my_boxs.html", boxs=boxs)


@box_bp.route("/box/new", methods=["GET", "POST"])
@login_required
def box_new():
    if request.method == "POST":
        nom = (request.form.get("nom") or "").strip()[:200]
        if not nom:
            flash("Nom de la box requis.", "error")
            return redirect(url_for("box.box_new"))
        description = (request.form.get("description") or "").strip()[:1000]
        is_public = request.form.get("is_public") == "on"
        box = Box(nom=nom, description=description, is_public=is_public, user_id=current_user.id)
        db.session.add(box)
        db.session.commit()
        flash("Box créée avec succès !", "success")
        return redirect(url_for("box.my_boxs"))
    return render_template("box_new.html")


@box_bp.route("/box/<int:box_id>")
def box_view(box_id):
    box = db.session.get(Box, box_id)
    if not box:
        flash("Box introuvable.", "error")
        return redirect(url_for("box.box_list"))
    if not box.is_public and (not current_user.is_authenticated or box.user_id != current_user.id):
        flash("Box privée.", "error")
        return redirect(url_for("box.box_list"))
    films = []
    for bf in box.films:
        film = bf.film
        if film:
            fd = film_to_dict(film)
            fd["position"] = bf.position
            films.append(fd)
    return render_template("box_view.html", box=box, films=films)


@box_bp.route("/box/<int:box_id>/add-film", methods=["POST"])
@login_required
def box_add_film(box_id):
    if box_id == 0:
        box_id = request.form.get("box_id", type=int)
    box = db.session.get(Box, box_id)
    if not box or box.user_id != current_user.id:
        flash("Accès refusé", "error")
        return redirect(url_for("box.box_list"))
    film_id = request.form.get("film_id", type=int)
    if not film_id or not db.session.get(Film, film_id):
        return jsonify({"error": "Film introuvable"}), 404
    existing = BoxFilm.query.filter_by(box_id=box_id, film_id=film_id).first()
    if existing:
        return jsonify({"error": "Déjà dans la box"}), 409
    max_pos = db.session.query(db.func.max(BoxFilm.position)).filter_by(box_id=box_id).scalar() or 0
    bf = BoxFilm(box_id=box_id, film_id=film_id, position=max_pos + 1)
    db.session.add(bf)
    db.session.commit()
    return jsonify({"status": "ok", "message": "Film ajouté à la box"})


@box_bp.route("/box/<int:box_id>/remove-film/<int:film_id>", methods=["POST"])
@login_required
def box_remove_film(box_id, film_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != current_user.id:
        flash("Accès refusé", "error")
        return redirect(url_for("box.box_list"))
    BoxFilm.query.filter_by(box_id=box_id, film_id=film_id).delete()
    db.session.commit()
    flash("Film retiré de la box.", "success")
    return redirect(url_for("box.box_view", box_id=box_id))


@box_bp.route("/box/<int:box_id>/edit", methods=["GET", "POST"])
@login_required
def box_edit(box_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != current_user.id:
        flash("Accès refusé", "error")
        return redirect(url_for("box.box_list"))
    if request.method == "POST":
        box.nom = (request.form.get("nom") or "").strip()[:200]
        box.description = (request.form.get("description") or "").strip()[:1000]
        box.is_public = request.form.get("is_public") == "on"
        db.session.commit()
        flash("Box modifiée.", "success")
        return redirect(url_for("box.box_view", box_id=box_id))
    return render_template("box_edit.html", box=box)


@box_bp.route("/box/<int:box_id>/delete", methods=["POST"])
@login_required
def box_delete(box_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != current_user.id:
        flash("Accès refusé", "error")
        return redirect(url_for("box.box_list"))
    db.session.delete(box)
    db.session.commit()
    flash("Box supprimée.", "success")
    return redirect(url_for("box.my_boxs"))
