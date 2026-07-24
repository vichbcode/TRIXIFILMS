import os
import re
import math
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, Response, current_app
)
from flask_login import current_user

from app.models import db, Film, Actor, Rating, Message
from app.utils import (
    film_to_dict, normalize_text, highlight_text,
    process_image, image_url, get_avg_rating
)

main_bp = Blueprint("main", __name__)

PER_PAGE = 24

# --- anti-abuse in-memory ---
_add_attempts = {}

def record_add_attempt(ip, success=False):
    cfg = current_app.config
    window = cfg.get("ADD_WINDOW", 600)
    threshold = cfg.get("ADD_THRESHOLD", 5)
    block_dur = cfg.get("ADD_BLOCK_DURATION", 1800)
    now = datetime.utcnow().timestamp()
    rec = _add_attempts.get(ip, {"attempts": [], "blocked_until": 0})
    rec["attempts"] = [t for t in rec["attempts"] if now - t < window]
    rec["attempts"].append(now)
    if success:
        rec["attempts"] = []
        rec["blocked_until"] = 0
    else:
        if len(rec["attempts"]) >= threshold:
            rec["blocked_until"] = now + block_dur
    _add_attempts[ip] = rec

def is_add_blocked(ip):
    rec = _add_attempts.get(ip)
    if not rec:
        return False
    now = datetime.utcnow().timestamp()
    return rec.get("blocked_until", 0) > now


@main_bp.route("/")
def index():
    q_raw = request.args.get("q", "").strip()
    filter_by = request.args.get("filter", "all").strip().lower()
    page = request.args.get("page", 1, type=int)

    allowed_filters = {"all", "nom", "realisateurs", "scenaristes", "productions", "resume", "acteurs", "role"}
    if filter_by not in allowed_filters:
        filter_by = "all"

    if not q_raw:
        films_query = Film.query.order_by(Film.id.desc())
        total = films_query.count()
        total_pages = max(1, math.ceil(total / PER_PAGE))
        films = films_query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
        films_data = [film_to_dict(f) for f in films]
        return render_template("index.html", films=films_data, query=q_raw,
                               filter_by=filter_by, page=page, total_pages=total_pages)

    q_norm = normalize_text(q_raw)
    terms = [t for t in re.split(r"\s+", q_norm) if t]
    if not terms:
        return render_template("index.html", films=[], query=q_raw, filter_by=filter_by,
                               page=1, total_pages=1)

    from sqlalchemy import or_, and_

    like_term = lambda col, t: col.ilike(f"%{t}%")
    and_likes = lambda col: and_(*[like_term(col, t) for t in terms])

    if filter_by == "nom":
        query = Film.query.filter(and_likes(Film.nom))
    elif filter_by == "realisateurs":
        query = Film.query.outerjoin(Actor, and_(Actor.film_id == Film.id, Actor.role == "Réalisateur"))
        query = query.filter(or_(and_likes(Film.realisateurs), and_likes(Actor.nom)))
        query = query.distinct()
    elif filter_by == "scenaristes":
        query = Film.query.outerjoin(Actor, and_(Actor.film_id == Film.id, Actor.role == "Scénariste"))
        query = query.filter(or_(and_likes(Film.scenaristes), and_likes(Actor.nom)))
        query = query.distinct()
    elif filter_by == "acteurs":
        query = Film.query.join(Actor).filter(and_likes(Actor.nom))
    elif filter_by == "role":
        query = Film.query.join(Actor).filter(and_likes(Actor.role))
    elif filter_by == "productions":
        query = Film.query.filter(and_likes(Film.productions))
    elif filter_by == "resume":
        query = Film.query.filter(and_likes(Film.resume))
    else:
        like_all = []
        for t in terms:
            like_all.append(or_(
                like_term(Film.nom, t),
                like_term(Film.realisateurs, t),
                like_term(Film.scenaristes, t),
                like_term(Film.productions, t),
                like_term(Film.resume, t),
                like_term(Actor.nom, t),
            ))
        query = Film.query.outerjoin(Actor).filter(and_(*like_all)).distinct()

    raw_films = query.order_by(Film.id.desc()).all()

    results = []
    for f in raw_films:
        fields = {
            "nom": normalize_text(f.nom or ""),
            "realisateurs": normalize_text(f.realisateurs or ""),
            "scenaristes": normalize_text(f.scenaristes or ""),
            "productions": normalize_text(f.productions or ""),
            "resume": normalize_text(f.resume or ""),
            "acteurs": " ".join(normalize_text(a.nom or "") for a in f.acteurs),
            "roles": " ".join(normalize_text(a.role or "") for a in f.acteurs),
        }

        if filter_by == "realisateurs":
            check_text = fields["realisateurs"] + " " + " ".join(
                normalize_text(a.nom or "") for a in f.acteurs if a.role == "Réalisateur"
            )
        elif filter_by == "scenaristes":
            check_text = fields["scenaristes"] + " " + " ".join(
                normalize_text(a.nom or "") for a in f.acteurs if a.role == "Scénariste"
            )
        elif filter_by == "acteurs":
            check_text = fields["acteurs"]
        elif filter_by == "role":
            check_text = fields["roles"]
        elif filter_by in {"nom", "productions", "resume"}:
            check_text = fields[filter_by]
        else:
            check_text = " ".join(fields[k] for k in fields)

        if not all(t in check_text for t in terms):
            continue

        fd = film_to_dict(f)
        for key in ["nom", "realisateurs", "scenaristes", "productions", "resume"]:
            fd[key] = highlight_text(fd.get(key, "") or "", terms)

        actors_joined = " ".join(a.nom or "" for a in f.acteurs)
        fd["acteurs"] = highlight_text(actors_joined, terms)

        matched_actors = []
        for a in f.acteurs:
            an = normalize_text(a.nom or "")
            if any(t in an for t in terms):
                matched_actors.append({"nom": a.nom, "role": a.role})
        fd["_matched_actors"] = matched_actors

        fn = normalize_text(f.realisateurs or "")
        fd["_matched_realisateurs_text"] = any(t in fn for t in terms)
        fn = normalize_text(f.scenaristes or "")
        fd["_matched_scenaristes_text"] = any(t in fn for t in terms)

        results.append(fd)

    def score_item(item):
        s = 0
        combined = " ".join(str(item.get(k, "")) for k in ("nom","realisateurs","scenaristes","productions","resume","acteurs")).lower()
        for t in terms:
            s += combined.count(t)
        return s

    results.sort(key=score_item, reverse=True)
    total = len(results)
    total_pages = max(1, math.ceil(total / PER_PAGE))
    start = (page - 1) * PER_PAGE
    results_page = results[start:start + PER_PAGE]
    return render_template("index.html", films=results_page, query=q_raw,
                           filter_by=filter_by, page=page, total_pages=total_pages)


@main_bp.route("/film/<int:film_id>")
def film_detail(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        flash("Film introuvable.", "error")
        return redirect(url_for("main.index"))

    fd = film_to_dict(film)
    acteurs = []
    for a in film.acteurs:
        acteurs.append({"nom": a.nom or "", "image": image_url(a, "actor"), "role": a.role or "Acteur"})

    notes = []
    for r in film.notations:
        notes.append({"prenom": r.prenom or "", "note": r.note or 0.0})

    avg, votes = get_avg_rating(film_id)

    messages = []
    for m in film.messages:
        messages.append({"prenom": m.prenom or "", "message": m.message or "", "created_at": m.created_at or ""})

    return render_template("movie.html", film=fd, acteurs=acteurs, notes=notes,
                           avg=avg, votes=votes, messages=messages)


@main_bp.route("/add", methods=["GET", "POST"])
def add_movie():
    ip = request.remote_addr or "unknown"
    if is_add_blocked(ip):
        flash("Trop de soumissions depuis votre IP. Réessaye plus tard.", "error")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        record_add_attempt(ip, success=False)

        title = (request.form.get("nom") or "").strip()[:200]
        if not title:
            flash("Nom du film requis.", "error")
            return redirect(url_for("main.add_movie"))

        resume = (request.form.get("resume") or "").strip()[:2000]
        realisateurs = (request.form.get("realisateurs") or "").strip()[:300]
        scenaristes = (request.form.get("scenaristes") or "").strip()[:300]
        productions = (request.form.get("productions") or "").strip()[:300]

        film = Film(
            nom=title,
            resume=resume,
            realisateurs=realisateurs,
            scenaristes=scenaristes,
            productions=productions,
            source=""
        )
        db.session.add(film)
        db.session.flush()

        img_data = process_image(request.files.get("image_film"))
        if img_data:
            film.image_data = img_data["data"]
            film.image_mime = img_data["mime"]
            film.image = ""

        actor_names = request.form.getlist("actor_name[]")
        actor_roles = request.form.getlist("actor_role[]")
        actor_files = request.files.getlist("actor_image[]")

        for idx, raw_name in enumerate(actor_names):
            name = (raw_name or "").strip()[:120]
            if not name:
                continue
            img_data = None
            if idx < len(actor_files) and getattr(actor_files[idx], "filename", ""):
                img_data = process_image(actor_files[idx])
            role = (actor_roles[idx].strip() if idx < len(actor_roles) and actor_roles[idx] else "Acteur")
            if role not in {"Acteur", "Réalisateur", "Scénariste"}:
                role = "Acteur"
            actor = Actor(film_id=film.id, nom=name, role=role)
            if img_data:
                actor.image_data = img_data["data"]
                actor.image_mime = img_data["mime"]
                actor.image = ""
            db.session.add(actor)

        db.session.commit()
        record_add_attempt(ip, success=True)

        flash("Film ajouté avec succès !", "success")
        return redirect(url_for("main.index"))

    return render_template("add_movie.html")


@main_bp.route("/edit/<int:movie_id>", methods=["GET", "POST"])
def edit_movie(movie_id):
    film = db.session.get(Film, movie_id)
    if not film:
        flash("Film introuvable", "error")
        return redirect(url_for("main.index"))

    if (film.source or "").strip().lower() == "tmdb":
        flash("Les films importés depuis TMDB ne peuvent pas être modifiés.", "error")
        return redirect(url_for("main.film_detail", film_id=movie_id))

    acteurs_list = []
    for a in film.acteurs:
        actor_img = url_for("main.serve_image", type="actor", id=a.id) if a.image_data else ""
        acteurs_list.append({"nom": a.nom or "", "image": actor_img, "role": a.role or "Acteur"})

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:200]
        if not title:
            flash("Nom du film requis.", "error")
            return redirect(url_for("main.edit_movie", movie_id=movie_id))

        film.nom = title
        film.resume = (request.form.get("description") or "").strip()[:2000]
        film.realisateurs = (request.form.get("directors") or "").strip()[:300]
        film.scenaristes = (request.form.get("writers") or "").strip()[:300]
        film.productions = (request.form.get("productions") or "").strip()[:300]

        img_data = process_image(request.files.get("image"))
        if img_data:
            film.image_data = img_data["data"]
            film.image_mime = img_data["mime"]
            film.image = ""

        noms_acteurs = request.form.getlist("actor_name[]")
        images_acteurs = request.files.getlist("actor_image[]")
        roles_acteurs = request.form.getlist("actor_role[]")

        Actor.query.filter_by(film_id=movie_id).delete()

        for idx, nom in enumerate(noms_acteurs):
            nm = (nom or "").strip()[:120]
            if not nm:
                continue
            img_data = None
            if idx < len(images_acteurs):
                img_file = images_acteurs[idx]
                if img_file and img_file.filename:
                    img_data = process_image(img_file)
            role = (roles_acteurs[idx].strip() if idx < len(roles_acteurs) and roles_acteurs[idx] else "Acteur")
            if role not in {"Acteur", "Réalisateur", "Scénariste"}:
                role = "Acteur"
            actor = Actor(film_id=movie_id, nom=nm, role=role)
            if img_data:
                actor.image_data = img_data["data"]
                actor.image_mime = img_data["mime"]
                actor.image = ""
            db.session.add(actor)

        db.session.commit()
        flash("Film modifié avec succès !", "success")
        return redirect(url_for("main.film_detail", film_id=movie_id))

    film_img = url_for("main.serve_image", type="film", id=film.id) if film.image_data else ""
    return render_template("edit_movie.html", movie=film, acteurs=acteurs_list, film_image=film_img)


@main_bp.route("/delete/<int:film_id>", methods=["POST"])
def delete_movie(film_id):
    if not current_user.is_authenticated:
        flash("Vous devez être connecté(e) pour supprimer un film.", "error")
        return redirect(url_for("main.film_detail", film_id=film_id))

    film = db.session.get(Film, film_id)
    if not film:
        flash("Film introuvable.", "error")
        return redirect(url_for("main.index"))

    if (film.source or "").strip().lower() == "tmdb":
        flash("Impossible : film importé depuis TMDB — suppression interdite.", "error")
        return redirect(url_for("main.film_detail", film_id=film_id))

    db.session.delete(film)
    db.session.commit()

    flash("Film supprimé avec succès !", "success")
    return redirect(url_for("main.index"))


@main_bp.route("/image/<string:img_type>/<int:img_id>")
def serve_image(img_type, img_id):
    if img_type == "film":
        obj = db.session.get(Film, img_id)
    elif img_type == "actor":
        obj = db.session.get(Actor, img_id)
    else:
        return Response("Type inconnu", status=404)
    if not obj or not obj.image_data:
        return Response("Image introuvable", status=404)
    return Response(obj.image_data, mimetype=obj.image_mime or "image/jpeg")


@main_bp.route("/film/<int:film_id>/rate", methods=["POST"])
def film_rate(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Film introuvable."}), 404
        flash("Film introuvable.", "error")
        return redirect(url_for("main.index"))

    prenom = (request.form.get("prenom") or "").strip()[:100]
    note = (request.form.get("note") or "").strip()
    if not prenom or not note:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Prénom et note requis."}), 400
        flash("Prénom et note requis.", "error")
        return redirect(url_for("main.film_detail", film_id=film_id))

    try:
        note_val = float(note)
        if note_val < 0.5 or note_val > 5:
            raise ValueError
        note_val = round(note_val * 2) / 2.0
    except Exception:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Note invalide (0.5 - 5)."}), 400
        flash("Note invalide (0.5 - 5).", "error")
        return redirect(url_for("main.film_detail", film_id=film_id))

    existing = Rating.query.filter_by(film_id=film_id).all()
    matched = [r for r in existing if (r.prenom or "").strip().lower() == prenom.lower()]
    if matched:
        matched[0].note = note_val
    else:
        new_rating = Rating(film_id=film_id, prenom=prenom, note=note_val)
        db.session.add(new_rating)

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        avg, votes = get_avg_rating(film_id)
        return jsonify({
            "status": "ok", "message": "Merci !",
            "avg": avg, "votes": votes, "user_note": note_val
        })

    flash("Merci pour votre notation !", "success")
    return redirect(url_for("main.film_detail", film_id=film_id))


@main_bp.route("/film/<int:film_id>/message", methods=["POST"])
def film_message(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        flash("Film introuvable.", "error")
        return redirect(url_for("main.index"))

    prenom = (request.form.get("prenom_msg") or "").strip()[:100]
    message = (request.form.get("message") or "").strip()[:2000]
    if not prenom or not message:
        flash("Prénom et message requis.", "error")
        return redirect(url_for("main.film_detail", film_id=film_id))

    msg = Message(
        film_id=film_id,
        prenom=prenom,
        message=message,
        created_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    )
    db.session.add(msg)
    db.session.commit()

    flash("Message enregistré !", "success")
    return redirect(url_for("main.film_detail", film_id=film_id))
