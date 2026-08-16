from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.models import db, TopFilm, Film
from app.utils import film_to_dict, get_avg_rating

top_bp = Blueprint("top", __name__)

MAX_TOP = 20


@top_bp.route("/top")
@login_required
def top_list():
    tops = TopFilm.query.filter_by(user_id=current_user.id).order_by(TopFilm.position.asc()).all()
    top_films = []
    for t in tops:
        film = t.film
        if film:
            fd = film_to_dict(film)
            fd["top_position"] = t.position
            avg, votes = get_avg_rating(film.id)
            fd["avg_rating"] = avg
            fd["votes"] = votes
            top_films.append(fd)

    return render_template("top_list.html", top_films=top_films)


@top_bp.route("/top/add", methods=["POST"])
@login_required
def top_add():
    film_id = request.form.get("film_id", type=int)
    position = request.form.get("position", type=int)

    if not film_id or not position:
        flash("Paramètres manquants.", "error")
        return redirect(url_for("top.top_list"))
    if position < 1 or position > MAX_TOP:
        flash("Position invalide.", "error")
        return redirect(url_for("top.top_list"))

    film = db.session.get(Film, film_id)
    if not film:
        flash("Film introuvable.", "error")
        return redirect(url_for("top.top_list"))

    existing = TopFilm.query.filter_by(user_id=current_user.id, position=position).first()
    if existing:
        db.session.delete(existing)

    existing_film = TopFilm.query.filter_by(user_id=current_user.id, film_id=film_id).first()
    if existing_film:
        db.session.delete(existing_film)

    top = TopFilm(film_id=film_id, position=position, user_id=current_user.id)
    db.session.add(top)
    db.session.commit()

    flash(f"Film ajouté à votre Top {position} !", "success")
    return redirect(request.referrer or url_for("top.top_list"))


@top_bp.route("/top/remove/<int:film_id>", methods=["POST"])
@login_required
def top_remove(film_id):
    entry = TopFilm.query.filter_by(film_id=film_id, user_id=current_user.id).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
        flash("Film retiré de votre Top.", "success")
    return redirect(url_for("top.top_list"))


@top_bp.route("/top/search-json")
@login_required
def top_search_json():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    from app.utils import normalize_text
    from sqlalchemy import or_
    terms = [t for t in q.lower().split() if t]
    query = Film.query
    for t in terms:
        query = query.filter(or_(
            Film.nom.ilike(f"%{t}%"),
            Film.categorie.ilike(f"%{t}%"),
            Film.origine.ilike(f"%{t}%"),
        ))
    films = query.order_by(Film.nom.asc()).limit(20).all()
    results = []
    for f in films:
        fd = film_to_dict(f)
        avg, votes = get_avg_rating(f.id)
        fd["avg_rating"] = avg
        fd["votes"] = votes
        results.append(fd)
    return jsonify(results)
