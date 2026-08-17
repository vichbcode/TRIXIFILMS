import re, math
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, redirect
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import db, Film, Actor, Rating, Message, User, Box, BoxFilm, TopFilm
from app.utils import (
    normalize_text, process_image,
    get_avg_rating
)
from app.cloud import upload_image_bytes, upload_image_url
from app.api_auth import (
    create_access_token, create_refresh_token, decode_token,
    token_required, refresh_token_required
)
from app.api_rate_limit import rate_limit, clear_rate_limit

api_bp = Blueprint("api", __name__)

PER_PAGE = 24
MIME_MAP = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}


def _sanitize_str(val, maxlen=500):
    if not val:
        return ""
    s = str(val).strip()[:maxlen]
    for ch in ('<', '>', '"', "'", ';', '&'):
        s = s.replace(ch, '')
    return s


def _validate_pagination():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", PER_PAGE, type=int)
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = PER_PAGE
    if per_page > 100:
        per_page = 100
    return page, per_page


# ─── Auth ────────────────────────────────────────────────────────────

@api_bp.route("/api/auth/login", methods=["POST"])
@rate_limit("api_login", 8, 900, 1800)
def api_login():
    data = request.get_json(silent=True) or {}
    prenom = _sanitize_str(data.get("prenom", ""), 100)
    password = data.get("password", "")
    if not prenom or not password:
        return jsonify({"error": "Prénom et mot de passe requis."}), 400
    user = User.query.filter_by(prenom=prenom).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Prénom ou mot de passe incorrect."}), 401
    access_token = create_access_token(user.id, user.prenom)
    refresh_token = create_refresh_token(user.id, user.prenom)
    clear_rate_limit("api_login", request.remote_addr or "unknown")
    current_app.logger.info(f"API login: {prenom}")
    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user.id, "prenom": user.prenom},
    })


@api_bp.route("/api/auth/refresh", methods=["POST"])
@refresh_token_required
def api_refresh():
    user = request.current_user
    access_token = create_access_token(user.id, user.prenom)
    refresh_token = create_refresh_token(user.id, user.prenom)
    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
    })


@api_bp.route("/api/auth/register", methods=["POST"])
@rate_limit("api_register", 5, 600, 1800)
def api_register():
    data = request.get_json(silent=True) or {}
    prenom = _sanitize_str(data.get("prenom", ""), 100)
    password = data.get("password", "")
    if len(prenom) < 2 or len(prenom) > 100:
        return jsonify({"error": "Le prénom doit faire entre 2 et 100 caractères."}), 400
    if len(password) < 8:
        return jsonify({"error": "Le mot de passe doit faire au moins 8 caractères."}), 400
    existing = User.query.filter_by(prenom=prenom).first()
    if existing:
        return jsonify({"error": "Ce prénom est déjà pris."}), 409
    user = User(prenom=prenom, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    access_token = create_access_token(user.id, user.prenom)
    refresh_token = create_refresh_token(user.id, user.prenom)
    current_app.logger.info(f"API register: {prenom}")
    return jsonify({
        "message": f"Utilisateur '{prenom}' créé.",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user.id, "prenom": user.prenom},
    }), 201


# ─── Account ─────────────────────────────────────────────────────────

@api_bp.route("/api/auth/account", methods=["PUT"])
@token_required
def api_update_account():
    data = request.get_json(silent=True) or {}
    prenom = _sanitize_str(data.get("prenom", ""), 100)
    if not prenom or len(prenom) < 2:
        return jsonify({"error": "Le prénom doit faire au moins 2 caractères."}), 400
    if prenom != request.current_user.prenom:
        existing = User.query.filter_by(prenom=prenom).first()
        if existing:
            return jsonify({"error": "Ce prénom est déjà pris."}), 409
    request.current_user.prenom = prenom
    password = data.get("password", "")
    if password:
        if len(password) < 8:
            return jsonify({"error": "Le mot de passe doit faire au moins 8 caractères."}), 400
        request.current_user.password_hash = generate_password_hash(password)
    db.session.commit()
    return jsonify({"prenom": prenom, "message": "Compte mis à jour."})


@api_bp.route("/api/auth/account", methods=["DELETE"])
@token_required
def api_delete_account():
    user = request.current_user
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "Compte supprimé."})


# ─── Films ───────────────────────────────────────────────────────────

@api_bp.route("/api/films", methods=["GET"])
def api_list_films():
    q_raw = request.args.get("q", "").strip()
    filter_by = request.args.get("filter", "all").strip().lower()
    page, per_page = _validate_pagination()

    allowed_filters = {"all", "nom", "realisateurs", "scenaristes",
                       "productions", "resume", "acteurs", "role",
                       "categorie", "origine"}
    if filter_by not in allowed_filters:
        filter_by = "all"

    has_image = request.args.get("has_image", "").strip().lower()
    sort_by = request.args.get("sort", "id_desc").strip().lower()

    categorie = request.args.get("categorie", "").strip()
    origine = request.args.get("origine", "").strip()

    base_query = Film.query
    query = base_query

    if has_image == "yes":
        base_query = base_query.filter(Film.image.isnot(None), Film.image != "")
        query = query.filter(Film.image.isnot(None), Film.image != "")
    elif has_image == "no":
        base_query = base_query.filter((Film.image.is_(None)) | (Film.image == ""))
        query = query.filter((Film.image.is_(None)) | (Film.image == ""))

    if categorie:
        query = query.filter(Film.categorie.ilike(f"%{categorie}%"))
    if origine:
        query = query.filter(Film.origine.ilike(f"%{origine}%"))

    if not q_raw:
        query = _apply_sort(query, sort_by)
        total = query.count()
        total_pages = max(1, math.ceil(total / per_page))
        films = query.offset((page - 1) * per_page).limit(per_page).all()
        return jsonify({
            "films": [_film_to_api(f) for f in films],
            "page": page, "per_page": per_page,
            "total": total, "total_pages": total_pages,
        })

    q_norm = normalize_text(q_raw)
    terms = [t for t in re.split(r"\s+", q_norm) if t]
    if not terms:
        return jsonify({"films": [], "page": 1, "per_page": per_page,
                        "total": 0, "total_pages": 1})

    from sqlalchemy import or_, and_, func

    _ACCENTS_FROM = "àáâãäåçèéêëìíîïñòóôõöùúûüýÿÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝ"
    _ACCENTS_TO = "aaaaaaceeeeiiiinooooouuuuyyAAAAAACEEEEIIIINOOOOOUUUUY"
    like_term = lambda col, t: func.translate(col, _ACCENTS_FROM, _ACCENTS_TO).ilike(f"%{t}%")
    and_likes = lambda col: and_(*[like_term(col, t) for t in terms])

    def run_search(base_q):
        if filter_by == "nom":
            base_q = base_q.filter(and_likes(Film.nom))
        elif filter_by == "realisateurs":
            base_q = base_q.outerjoin(Actor, and_(Actor.film_id == Film.id, Actor.role == "Réalisateur"))
            base_q = base_q.filter(or_(and_likes(Film.realisateurs), and_likes(Actor.nom)))
            base_q = base_q.distinct()
        elif filter_by == "scenaristes":
            base_q = base_q.outerjoin(Actor, and_(Actor.film_id == Film.id, Actor.role == "Scénariste"))
            base_q = base_q.filter(or_(and_likes(Film.scenaristes), and_likes(Actor.nom)))
            base_q = base_q.distinct()
        elif filter_by == "acteurs":
            base_q = base_q.join(Actor).filter(and_likes(Actor.nom))
        elif filter_by == "role":
            base_q = base_q.join(Actor).filter(and_likes(Actor.role))
        elif filter_by == "productions":
            base_q = base_q.filter(and_likes(Film.productions))
        elif filter_by == "resume":
            base_q = base_q.filter(and_likes(Film.resume))
        elif filter_by == "categorie":
            base_q = base_q.filter(and_likes(Film.categorie))
        elif filter_by == "origine":
            base_q = base_q.filter(and_likes(Film.origine))
        else:
            like_all = []
            for t in terms:
                like_all.append(or_(
                    like_term(Film.nom, t),
                    like_term(Film.realisateurs, t),
                    like_term(Film.scenaristes, t),
                    like_term(Film.productions, t),
                    like_term(Film.resume, t),
                    like_term(Film.categorie, t),
                    like_term(Film.origine, t),
                    like_term(Actor.nom, t),
                ))
            base_q = base_q.outerjoin(Actor).filter(and_(*like_all)).distinct()

        raw_films = base_q.order_by(Film.id.desc()).all()

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
            elif filter_by in {"nom", "productions", "resume", "categorie", "origine"}:
                check_text = fields[filter_by]
            else:
                check_text = " ".join(fields[k] for k in fields)

            if not all(t in check_text for t in terms):
                continue

            results.append(_film_to_api(f))

        return results

    results = run_search(query)
    relaxed = False
    if not results and (categorie or origine):
        relaxed_results = run_search(base_query)
        if relaxed_results:
            results = relaxed_results
            relaxed = True

    def score_item(item):
        s = 0
        combined = " ".join(str(item.get(k, "")) for k in ("nom", "realisateurs", "scenaristes", "productions", "resume")).lower()
        for t in terms:
            s += combined.count(t)
        return s

    results.sort(key=score_item, reverse=True)
    total = len(results)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    results_page = results[start:start + per_page]

    return jsonify({
        "films": results_page,
        "page": page, "per_page": per_page,
        "total": total, "total_pages": total_pages,
        "query": q_raw, "filter": filter_by,
        "relaxed": relaxed,
    })


def _apply_sort(query, sort_by):
    mapping = {
        "id_desc": Film.id.desc(),
        "id_asc": Film.id.asc(),
        "nom_asc": Film.nom.asc(),
        "nom_desc": Film.nom.desc(),
    }
    return query.order_by(mapping.get(sort_by, Film.id.desc()))


def _film_to_api(film):
    has_image = bool(film.image)
    d = {
        "id": film.id,
        "nom": film.nom,
        "titre_original": film.titre_original or "",
        "langue_originale": film.langue_originale or "",
        "resume": film.resume or "",
        "realisateurs": film.realisateurs or "",
        "scenaristes": film.scenaristes or "",
        "productions": film.productions or "",
        "categorie": film.categorie or "",
        "origine": film.origine or "",
        "source": film.source or "",
        "trailer": film.trailer or "",
        "has_image": has_image,
        "image_url": film.image if has_image else None,
        "avg_rating": None,
        "votes": 0,
        "acteurs": [
            {
                "id": a.id,
                "nom": a.nom,
                "role": a.role or "Acteur",
                "has_image": bool(a.image),
                "image_url": a.image if a.image else None,
            }
            for a in film.acteurs
        ],
    }
    avg, votes = get_avg_rating(film.id)
    d["avg_rating"] = avg
    d["votes"] = votes
    return d


@api_bp.route("/api/films/<int:film_id>", methods=["GET"])
def api_get_film(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        return jsonify({"error": "Film introuvable."}), 404
    d = _film_to_api(film)
    d["messages"] = [
        {
            "id": m.id,
            "prenom": m.prenom or "",
            "message": m.message or "",
            "created_at": m.created_at or "",
        }
        for m in film.messages
    ]
    d["notations"] = [
        {"prenom": r.prenom or "", "note": r.note or 0.0}
        for r in film.notations
    ]
    return jsonify(d)


@api_bp.route("/api/films", methods=["POST"])
@token_required
@rate_limit("api_add_film", 5, 600, 1800)
def api_add_film():
    title = _sanitize_str(request.form.get("nom", ""), 200)
    if not title:
        return jsonify({"error": "Nom du film requis."}), 400

    resume = _sanitize_str(request.form.get("resume", ""), 2000)
    realisateurs = _sanitize_str(request.form.get("realisateurs", ""), 300)
    scenaristes = _sanitize_str(request.form.get("scenaristes", ""), 300)
    productions = _sanitize_str(request.form.get("productions", ""), 300)
    categorie = _sanitize_str(request.form.get("categorie", ""), 100)
    origine = _sanitize_str(request.form.get("origine", ""), 100)
    titre_original = _sanitize_str(request.form.get("titre_original", ""), 300)
    langue_originale = _sanitize_str(request.form.get("langue_originale", ""), 100)
    trailer = _sanitize_str(request.form.get("trailer", ""), 300)

    film = Film(
        nom=title, resume=resume,
        realisateurs=realisateurs, scenaristes=scenaristes,
        productions=productions, categorie=categorie,
        origine=origine, titre_original=titre_original,
        langue_originale=langue_originale, source="",
        trailer=trailer,
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
        name = _sanitize_str(raw_name, 120)
        if not name:
            continue
        img_data = None
        if idx < len(actor_files) and getattr(actor_files[idx], "filename", ""):
            img_data = process_image(actor_files[idx])
        role = _sanitize_str(actor_roles[idx] if idx < len(actor_roles) and actor_roles[idx] else "Acteur", 100)
        if role not in {"Acteur", "Réalisateur", "Scénariste"}:
            role = "Acteur"
        actor = Actor(film_id=film.id, nom=name, role=role)
        if img_data:
            actor.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""
        db.session.add(actor)

    db.session.commit()
    clear_rate_limit("api_add_film", request.remote_addr or "unknown")
    current_app.logger.info(f"API add film: {title}")
    return jsonify({"message": "Film ajouté.", "film": _film_to_api(film)}), 201


@api_bp.route("/api/films/<int:film_id>", methods=["PUT"])
@token_required
@rate_limit("api_edit_film", 10, 600, 1800)
def api_edit_film(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        return jsonify({"error": "Film introuvable."}), 404
    if (film.source or "").strip().lower() == "tmdb":
        return jsonify({"error": "Films TMDB non modifiables."}), 403

    title = _sanitize_str(request.form.get("nom", ""), 200)
    if not title:
        return jsonify({"error": "Nom du film requis."}), 400

    film.nom = title
    film.resume = _sanitize_str(request.form.get("resume", ""), 2000)
    film.realisateurs = _sanitize_str(request.form.get("realisateurs", ""), 300)
    film.scenaristes = _sanitize_str(request.form.get("scenaristes", ""), 300)
    film.productions = _sanitize_str(request.form.get("productions", ""), 300)
    film.categorie = _sanitize_str(request.form.get("categorie", ""), 100)
    film.origine = _sanitize_str(request.form.get("origine", ""), 100)
    film.titre_original = _sanitize_str(request.form.get("titre_original", ""), 300)
    film.langue_originale = _sanitize_str(request.form.get("langue_originale", ""), 100)
    film.trailer = _sanitize_str(request.form.get("trailer", ""), 300)

    img_data = process_image(request.files.get("image_film"))
    if img_data:
        film.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""

    Actor.query.filter_by(film_id=film_id).delete()

    actor_names = request.form.getlist("actor_name[]")
    actor_roles = request.form.getlist("actor_role[]")
    actor_files = request.files.getlist("actor_image[]")

    for idx, raw_name in enumerate(actor_names):
        name = _sanitize_str(raw_name, 120)
        if not name:
            continue
        img_data = None
        if idx < len(actor_files) and getattr(actor_files[idx], "filename", ""):
            img_data = process_image(actor_files[idx])
        role = _sanitize_str(actor_roles[idx] if idx < len(actor_roles) and actor_roles[idx] else "Acteur", 100)
        if role not in {"Acteur", "Réalisateur", "Scénariste"}:
            role = "Acteur"
        actor = Actor(film_id=film_id, nom=name, role=role)
        if img_data:
            actor.image = upload_image_bytes(img_data["data"], img_data["mime"]) or ""
        db.session.add(actor)

    db.session.commit()
    return jsonify({"message": "Film modifié.", "film": _film_to_api(film)})


@api_bp.route("/api/films/<int:film_id>", methods=["DELETE"])
@token_required
def api_delete_film(film_id):
    if not getattr(request.current_user, "is_admin", False):
        return jsonify({"error": "Accès refusé : administrateur requis."}), 403
    film = db.session.get(Film, film_id)
    if not film:
        return jsonify({"error": "Film introuvable."}), 404
    if (film.source or "").strip().lower() == "tmdb":
        return jsonify({"error": "Films TMDB non supprimables."}), 403
    db.session.delete(film)
    db.session.commit()
    current_app.logger.info(f"API delete film: {film_id}")
    return jsonify({"message": "Film supprimé."})


# ─── Images ──────────────────────────────────────────────────────────

@api_bp.route("/api/image/<string:img_type>/<int:img_id>")
def api_serve_image(img_type, img_id):
    if img_type == "film":
        obj = db.session.get(Film, img_id)
    elif img_type == "actor":
        obj = db.session.get(Actor, img_id)
    else:
        return jsonify({"error": "Type inconnu"}), 404
    if not obj or not obj.image:
        return jsonify({"error": "Image introuvable"}), 404
    return redirect(obj.image)


# ─── Rating ──────────────────────────────────────────────────────────

@api_bp.route("/api/films/<int:film_id>/rate", methods=["POST"])
@rate_limit("api_rate", 20, 60, 300)
def api_rate_film(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        return jsonify({"error": "Film introuvable."}), 404

    data = request.get_json(silent=True) or {}
    prenom = _sanitize_str(data.get("prenom", ""), 100)
    note_raw = data.get("note")
    if note_raw is None:
        return jsonify({"error": "Note requise."}), 400
    if not prenom:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_token(auth_header[7:])
            if payload and payload.get("type") == "access":
                user = db.session.get(User, int(payload["sub"]))
                if user:
                    prenom = user.prenom
        if not prenom:
            prenom = "Anonyme"

    try:
        note_val = float(note_raw)
        if note_val < 0.5 or note_val > 5:
            raise ValueError
        note_val = round(note_val * 2) / 2.0
    except (ValueError, TypeError):
        return jsonify({"error": "Note invalide (0.5 - 5)."}), 400

    existing = Rating.query.filter_by(film_id=film_id).all()
    matched = [r for r in existing if (r.prenom or "").strip().lower() == prenom.lower()]
    if matched:
        matched[0].note = note_val
    else:
        rating = Rating(film_id=film_id, prenom=prenom, note=note_val)
        db.session.add(rating)
    db.session.commit()

    avg, votes = get_avg_rating(film_id)
    return jsonify({"status": "ok", "avg": avg, "votes": votes, "user_note": note_val})


# ─── Messages ────────────────────────────────────────────────────────

@api_bp.route("/api/films/<int:film_id>/messages", methods=["POST"])
@rate_limit("api_message", 10, 60, 300)
def api_add_message(film_id):
    film = db.session.get(Film, film_id)
    if not film:
        return jsonify({"error": "Film introuvable."}), 404

    data = request.get_json(silent=True) or {}
    prenom = _sanitize_str(data.get("prenom", ""), 100)
    message = _sanitize_str(data.get("message", ""), 2000)
    if not prenom or not message:
        return jsonify({"error": "Prénom et message requis."}), 400

    msg = Message(
        film_id=film_id, prenom=prenom, message=message,
        created_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify({"message": "Message enregistré.", "id": msg.id}), 201


# ─── TMDB ────────────────────────────────────────────────────────────

@api_bp.route("/api/tmdb/search", methods=["GET"])
def api_tmdb_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q required"}), 400
    api_key = current_app.config.get("TMDB_API_KEY", "")
    if not api_key:
        return jsonify({"error": "TMDB_API_KEY not configured"}), 503
    import requests as http_req
    try:
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": api_key, "query": q, "page": 1,
                  "include_adult": False, "language": "fr-FR"}
        r = http_req.get(url, params=params, timeout=10)
        r.raise_for_status()
        res = r.json()
    except Exception as e:
        current_app.logger.exception("TMDB search failed")
        return jsonify({"error": "TMDB search failed", "details": str(e)}), 500
    out = []
    for it in res.get("results", [])[:20]:
        out.append({
            "id": it.get("id"),
            "title": it.get("title"),
            "overview": it.get("overview"),
            "release_date": it.get("release_date"),
            "poster_path": ("https://image.tmdb.org/t/p/w500" + it["poster_path"])
                           if it.get("poster_path") else None,
        })
    return jsonify({"results": out})


@api_bp.route("/api/tmdb/import/<int:tmdb_id>", methods=["POST"])
@token_required
@rate_limit("api_tmdb_import", 5, 300, 1800)
def api_tmdb_import(tmdb_id):
    api_key = current_app.config.get("TMDB_API_KEY", "")
    if not api_key:
        return jsonify({"error": "TMDB_API_KEY not configured"}), 503
    import requests as http_req
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    params = {"api_key": api_key, "language": "fr-FR"}
    try:
        r = http_req.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        current_app.logger.exception("TMDB import failed")
        return jsonify({"error": "TMDB fetch failed", "details": str(e)}), 500

    title = data.get("title") or data.get("original_title") or f"TMDB-{tmdb_id}"
    overview = _sanitize_str(data.get("overview", ""), 2000)
    productions = ", ".join([p.get("name", "") for p in data.get("production_companies", []) if p.get("name")])[:300]
    realisateurs = ""
    credits = None
    try:
        r2 = http_req.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits",
                          params={"api_key": api_key}, timeout=10)
        r2.raise_for_status()
        credits = r2.json()
        directors = [c.get("name") for c in credits.get("crew", []) if c.get("job") == "Director"]
        if directors:
            realisateurs = ", ".join(directors)[:300]
    except Exception:
        pass

    poster_url = ("https://image.tmdb.org/t/p/w500" + data["poster_path"]) if data.get("poster_path") else None
    img_url = upload_image_url(poster_url) if poster_url else None

    film = Film(nom=title, resume=overview, realisateurs=realisateurs,
                scenaristes="", productions=productions, source="tmdb")
    if img_url:
        film.image = img_url
    db.session.add(film)
    db.session.flush()

    try:
        cast = credits.get("cast", [])[:6] if credits else []
        for c in cast:
            name = _sanitize_str(c.get("name", ""), 120)
            if not name:
                continue
            profile_url = ("https://image.tmdb.org/t/p/w200" + c["profile_path"]) if c.get("profile_path") else None
            ac_img = upload_image_url(profile_url) if profile_url else None
            role = _sanitize_str(c.get("character", "Acteur"), 100)
            actor = Actor(film_id=film.id, nom=name, role=role)
            if ac_img:
                actor.image = ac_img
            db.session.add(actor)
    except Exception:
        pass

    db.session.commit()
    return jsonify({"message": "Import TMDB réussi.", "film": _film_to_api(film)}), 201


# ─── Box ────────────────────────────────────────────────────────────

@api_bp.route("/api/boxs", methods=["GET"])
def api_list_boxs():
    q = request.args.get("q", "").strip()
    page, per_page = _validate_pagination()
    query = Box.query.filter_by(is_public=True)
    if q:
        query = query.filter(Box.nom.ilike(f"%{q}%"))
    total = query.count()
    total_pages = max(1, math.ceil(total / per_page))
    boxs = query.order_by(Box.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "boxs": [_box_to_api(b) for b in boxs],
        "page": page, "per_page": per_page,
        "total": total, "total_pages": total_pages,
    })


@api_bp.route("/api/boxs", methods=["POST"])
@token_required
def api_create_box():
    data = request.get_json(silent=True) or {}
    nom = _sanitize_str(data.get("nom", ""), 200)
    if not nom:
        return jsonify({"error": "Nom requis."}), 400
    description = _sanitize_str(data.get("description", ""), 1000)
    is_public = data.get("is_public", True)
    box = Box(nom=nom, description=description, is_public=bool(is_public),
              user_id=request.current_user.id)
    db.session.add(box)
    db.session.commit()
    return jsonify({"box": _box_to_api(box)}), 201


@api_bp.route("/api/boxs/<int:box_id>", methods=["GET"])
def api_get_box(box_id):
    box = db.session.get(Box, box_id)
    if not box:
        return jsonify({"error": "Box introuvable."}), 404
    if not box.is_public:
        from flask_login import current_user
        if not current_user.is_authenticated or box.user_id != current_user.id:
            return jsonify({"error": "Box privée."}), 403
    films = []
    for bf in box.films:
        if bf.film:
            fd = _film_to_api(bf.film)
            fd["position"] = bf.position
            films.append(fd)
    return jsonify({"box": _box_to_api(box), "films": films})


@api_bp.route("/api/boxs/<int:box_id>/films", methods=["POST"])
@token_required
def api_box_add_film(box_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != request.current_user.id:
        return jsonify({"error": "Accès refusé."}), 403
    data = request.get_json(silent=True) or {}
    film_id = data.get("film_id", type=int)
    if not film_id or not db.session.get(Film, film_id):
        return jsonify({"error": "Film introuvable."}), 404
    existing = BoxFilm.query.filter_by(box_id=box_id, film_id=film_id).first()
    if existing:
        return jsonify({"error": "Déjà dans la box."}), 409
    max_pos = db.session.query(db.func.max(BoxFilm.position)).filter_by(box_id=box_id).scalar() or 0
    bf = BoxFilm(box_id=box_id, film_id=film_id, position=max_pos + 1)
    db.session.add(bf)
    db.session.commit()
    return jsonify({"status": "ok", "message": "Film ajouté à la box."})


@api_bp.route("/api/boxs/<int:box_id>/films/<int:film_id>", methods=["DELETE"])
@token_required
def api_box_remove_film(box_id, film_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != request.current_user.id:
        return jsonify({"error": "Accès refusé."}), 403
    BoxFilm.query.filter_by(box_id=box_id, film_id=film_id).delete()
    db.session.commit()
    return jsonify({"status": "ok", "message": "Film retiré."})


@api_bp.route("/api/boxs/<int:box_id>", methods=["PUT"])
@token_required
def api_edit_box(box_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != request.current_user.id:
        return jsonify({"error": "Accès refusé."}), 403
    data = request.get_json(silent=True) or {}
    if "nom" in data:
        box.nom = _sanitize_str(data["nom"], 200)
    if "description" in data:
        box.description = _sanitize_str(data["description"], 1000)
    if "is_public" in data:
        box.is_public = bool(data["is_public"])
    db.session.commit()
    return jsonify({"box": _box_to_api(box)})


@api_bp.route("/api/boxs/<int:box_id>", methods=["DELETE"])
@token_required
def api_delete_box(box_id):
    box = db.session.get(Box, box_id)
    if not box or box.user_id != request.current_user.id:
        return jsonify({"error": "Accès refusé."}), 403
    db.session.delete(box)
    db.session.commit()
    return jsonify({"status": "ok", "message": "Box supprimée."})


@api_bp.route("/api/my-boxs", methods=["GET"])
@token_required
def api_my_boxs():
    boxs = Box.query.filter_by(user_id=request.current_user.id).order_by(Box.created_at.desc()).all()
    return jsonify({"boxs": [_box_to_api(b) for b in boxs]})


def _box_to_api(box):
    return {
        "id": box.id,
        "nom": box.nom,
        "description": box.description or "",
        "is_public": box.is_public,
        "user_id": box.user_id,
        "user_prenom": box.owner.prenom if box.owner else "",
        "film_count": len(box.films),
        "created_at": box.created_at.isoformat() if box.created_at else None,
    }


# ─── Top ────────────────────────────────────────────────────────────

@api_bp.route("/api/top", methods=["GET"])
@token_required
def api_get_top():
    tops = TopFilm.query.filter_by(user_id=request.current_user.id).order_by(TopFilm.position.asc()).all()
    results = []
    for t in tops:
        if t.film:
            fd = _film_to_api(t.film)
            fd["top_position"] = t.position
            results.append(fd)
    return jsonify({"top": results})


@api_bp.route("/api/top", methods=["POST"])
@token_required
def api_add_top():
    data = request.get_json(silent=True) or {}
    film_id = data.get("film_id", type=int)
    position = data.get("position", type=int)
    if not film_id or not position:
        return jsonify({"error": "film_id et position requis."}), 400
    if position < 1 or position > 20:
        return jsonify({"error": "Position invalide (1-20)."}), 400
    if not db.session.get(Film, film_id):
        return jsonify({"error": "Film introuvable."}), 404
    existing = TopFilm.query.filter_by(user_id=request.current_user.id, position=position).first()
    if existing:
        db.session.delete(existing)
    existing_film = TopFilm.query.filter_by(user_id=request.current_user.id, film_id=film_id).first()
    if existing_film:
        db.session.delete(existing_film)
    top = TopFilm(film_id=film_id, position=position, user_id=request.current_user.id)
    db.session.add(top)
    db.session.commit()
    return jsonify({"status": "ok", "message": "Ajouté au top."}), 201


@api_bp.route("/api/top/<int:film_id>", methods=["DELETE"])
@token_required
def api_remove_top(film_id):
    entry = TopFilm.query.filter_by(film_id=film_id, user_id=request.current_user.id).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
    return jsonify({"status": "ok", "message": "Retiré du top."})


# ─── Health ──────────────────────────────────────────────────────────

@api_bp.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "version": "2.0", "time": datetime.utcnow().isoformat()})
