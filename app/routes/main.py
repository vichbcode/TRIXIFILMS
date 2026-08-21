import os
import re
import math
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, Response, current_app
)
from flask_login import current_user, login_required

from app.models import db, Film, Actor, Rating, Message
from app.utils import (
    film_to_dict, normalize_text, highlight_text,
    process_image, image_url, get_avg_rating, parse_youtube_id
)
from app.cloud import upload_image_bytes

main_bp = Blueprint("main", __name__)

PER_PAGE = 24


def search_films(q_raw, filter_by="all", page=1):
    """Réutilisable par d'autres blueprints"""
    from app.utils import normalize_text
    from sqlalchemy import or_, and_, func

    _ACCENTS_FROM = "àáâãäåçèéêëìíîïñòóôõöùúûüýÿÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝ"
    _ACCENTS_TO = "aaaaaaceeeeiiiinooooouuuuyyAAAAAACEEEEIIIINOOOOOUUUUY"
    like_term = lambda col, t: func.translate(col, _ACCENTS_FROM, _ACCENTS_TO).ilike(f"%{t}%")

    q_norm = normalize_text(q_raw)
    terms = [t for t in re.split(r"\s+", q_norm) if t]
    if not terms:
        return []

    and_likes = lambda col: and_(*[like_term(col, t) for t in terms])

    if filter_by == "nom":
        query = Film.query.filter(or_(and_likes(Film.nom), and_likes(Film.titre_original)))
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
    elif filter_by == "categorie":
        query = Film.query.filter(and_likes(Film.categorie))
    elif filter_by == "origine":
        query = Film.query.filter(and_likes(Film.origine))
    else:
        like_all = []
        for t in terms:
            like_all.append(or_(
                like_term(Film.nom, t),
                like_term(Film.titre_original, t),
                like_term(Film.realisateurs, t),
                like_term(Film.scenaristes, t),
                like_term(Film.productions, t),
                like_term(Film.resume, t),
                like_term(Film.categorie, t),
                like_term(Film.origine, t),
                like_term(Actor.nom, t),
            ))
        query = Film.query.outerjoin(Actor).filter(and_(*like_all)).distinct()

    raw_films = query.order_by(Film.id.desc()).all()

    results = []
    for f in raw_films:
        fields = {
            "nom": normalize_text(f.nom or ""),
            "titre_original": normalize_text(f.titre_original or ""),
            "realisateurs": normalize_text(f.realisateurs or ""),
            "scenaristes": normalize_text(f.scenaristes or ""),
            "productions": normalize_text(f.productions or ""),
            "resume": normalize_text(f.resume or ""),
            "categorie": normalize_text(f.categorie or ""),
            "origine": normalize_text(f.origine or ""),
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
        elif filter_by == "nom":
            check_text = fields["nom"] + " " + fields["titre_original"]
        elif filter_by in {"productions", "resume", "categorie", "origine"}:
            check_text = fields[filter_by]
        else:
            check_text = " ".join(fields[k] for k in fields)

        if not all(t in check_text for t in terms):
            continue

        fd = film_to_dict(f)
        for key in ["nom", "titre_original", "realisateurs", "scenaristes", "productions", "resume", "categorie", "origine"]:
            fd[key] = highlight_text(fd.get(key, "") or "", terms)

        actors_joined = " ".join(a.nom or "" for a in f.acteurs)
        fd["acteurs"] = highlight_text(actors_joined, terms)

        matched_actors = []
        for a in f.acteurs:
            an = normalize_text(a.nom or "")
            if any(t in an for t in terms):
                matched_actors.append({"nom": a.nom, "role": a.role})
        fd["_matched_actors"] = matched_actors

        results.append(fd)

    return results

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


@main_bp.route("/healthz")
def healthz():
    return Response("ok", status=200)


@main_bp.route("/trailer/<string:video_id>")
def trailer_embed(video_id: str):
    if not re.match(r"^[A-Za-z0-9_-]{6,20}$", video_id):
        return Response("Not found", status=404)
    autoplay = 1 if request.args.get("autoplay") == "1" else 0
    return render_template("trailer.html", video_id=video_id, autoplay=autoplay)


@main_bp.route("/")
def index():
    q_raw = request.args.get("q", "").strip()
    filter_by = request.args.get("filter", "all").strip().lower()
    cat_filter = request.args.get("categorie", "").strip()
    orig_filter = request.args.get("origine", "").strip()
    page = request.args.get("page", 1, type=int)

    allowed_filters = {"all", "nom", "realisateurs", "scenaristes", "productions", "resume", "acteurs", "role"}
    if filter_by not in allowed_filters:
        filter_by = "all"

    query = Film.query
    from sqlalchemy import or_

    if cat_filter:
        query = query.filter(Film.categorie.ilike(f"%{cat_filter}%"))
    if orig_filter:
        query = query.filter(Film.origine.ilike(f"%{orig_filter}%"))

    if q_raw:
        results = search_films(q_raw, filter_by, page)

        def score_item(item):
            s = 0
            combined = " ".join(str(item.get(k, "")) for k in ("nom","realisateurs","scenaristes","productions","resume","categorie","origine","acteurs")).lower()
            for t in [x for x in re.split(r"\s+", normalize_text(q_raw)) if x]:
                s += combined.count(t)
            return s

        relaxed = False
        if cat_filter or orig_filter:
            strict = [r for r in results if
                      (not cat_filter or normalize_text(cat_filter) in normalize_text(r.get("categorie", ""))) and
                      (not orig_filter or normalize_text(orig_filter) in normalize_text(r.get("origine", "")))]
            if strict:
                results = strict
            elif results:
                relaxed = True

        results.sort(key=score_item, reverse=True)
        total = len(results)
        total_pages = max(1, math.ceil(total / PER_PAGE))
        start = (page - 1) * PER_PAGE
        results_page = results[start:start + PER_PAGE]
    else:
        films_query = query.order_by(Film.id.desc())
        total = films_query.count()
        total_pages = max(1, math.ceil(total / PER_PAGE))
        films = films_query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
        results_page = [film_to_dict(f) for f in films]
        relaxed = False

    return render_template("index.html", films=results_page, query=q_raw,
                           filter_by=filter_by, page=page, total_pages=total_pages,
                           categorie_filter=cat_filter, origine_filter=orig_filter,
                           relaxed=relaxed)


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
@login_required
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
        titre_original = (request.form.get("titre_original") or "").strip()[:300]
        langue_originale = (request.form.get("langue_originale") or "").strip()[:100]
        realisateurs = (request.form.get("realisateurs") or "").strip()[:300]
        scenaristes = (request.form.get("scenaristes") or "").strip()[:300]
        productions = (request.form.get("productions") or "").strip()[:300]
        categorie = (request.form.get("categorie") or "").strip()[:100]
        origine = (request.form.get("origine") or "").strip()[:100]
        trailer = parse_youtube_id(request.form.get("trailer"))

        film = Film(
            nom=title,
            resume=resume,
            titre_original=titre_original,
            langue_originale=langue_originale,
            realisateurs=realisateurs,
            scenaristes=scenaristes,
            productions=productions,
            categorie=categorie,
            origine=origine,
            trailer=trailer,
            source=""
        )
        db.session.add(film)
        db.session.flush()

        img_data = process_image(request.files.get("image_film"))
        if img_data:
            film.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""

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
                actor.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""
            db.session.add(actor)

        db.session.commit()
        record_add_attempt(ip, success=True)

        if not trailer:
            from app.trailers import enqueue_trailer
            enqueue_trailer(film.id)

        flash("Film ajouté avec succès !", "success")
        return redirect(url_for("main.index"))

    return render_template("add_movie.html")


@main_bp.route("/edit/<int:movie_id>", methods=["GET", "POST"])
@login_required
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
        acteurs_list.append({"nom": a.nom or "", "image": a.image or "", "role": a.role or "Acteur"})

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:200]
        if not title:
            flash("Nom du film requis.", "error")
            return redirect(url_for("main.edit_movie", movie_id=movie_id))

        film.nom = title
        film.resume = (request.form.get("description") or "").strip()[:2000]
        film.titre_original = (request.form.get("titre_original") or "").strip()[:300]
        film.langue_originale = (request.form.get("langue_originale") or "").strip()[:100]
        film.realisateurs = (request.form.get("directors") or "").strip()[:300]
        film.scenaristes = (request.form.get("writers") or "").strip()[:300]
        film.productions = (request.form.get("productions") or "").strip()[:300]
        film.categorie = (request.form.get("categorie") or "").strip()[:100]
        film.origine = (request.form.get("origine") or "").strip()[:100]
        film.trailer = parse_youtube_id(request.form.get("trailer"))

        img_data = process_image(request.files.get("image"))
        if img_data:
            film.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""

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
                actor.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""
            db.session.add(actor)

        db.session.commit()
        if not film.trailer:
            from app.trailers import enqueue_trailer
            enqueue_trailer(film.id)
        flash("Film modifié avec succès !", "success")
        return redirect(url_for("main.film_detail", film_id=movie_id))

    film_img = film.image or ""
    return render_template("edit_movie.html", movie=film, acteurs=acteurs_list, film_image=film_img)


@main_bp.route("/delete/<int:film_id>", methods=["POST"])
def delete_movie(film_id):
    if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
        flash("Accès refusé : seuls les administrateurs peuvent supprimer un film.", "error")
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


@main_bp.route("/shorts")
def shorts():
    films = Film.query.filter(
        Film.trailer.isnot(None), Film.trailer != ""
    ).order_by(Film.id.desc()).all()
    items = []
    for f in films:
        fd = film_to_dict(f)
        items.append({"id": f.id, "nom": fd["nom"], "image": fd["image"], "trailer": f.trailer})
    return render_template("shorts.html", shorts=items, title="Bandes-annonces")


@main_bp.route("/image/<string:img_type>/<int:img_id>")
def serve_image(img_type, img_id):
    if img_type == "film":
        obj = db.session.get(Film, img_id)
    elif img_type == "actor":
        obj = db.session.get(Actor, img_id)
    else:
        return Response("Type inconnu", status=404)
    if not obj or not obj.image:
        return Response("Image introuvable", status=404)
    return redirect(obj.image)


@main_bp.route("/film/<int:film_id>/rate", methods=["POST"])
def film_rate(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Film introuvable."}), 404
        flash("Film introuvable.", "error")
        return redirect(url_for("main.index"))

    if current_user.is_authenticated:
        prenom = current_user.prenom
    else:
        prenom = (request.form.get("prenom") or "").strip()[:100] or "Anonyme"
    note = (request.form.get("note") or "").strip()
    if not prenom or not note:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Note requise."}), 400
        flash("Note requise.", "error")
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
