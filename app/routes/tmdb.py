from flask import (
    Blueprint, request, redirect, url_for, flash, jsonify, current_app
)
from flask_login import login_required

from app.models import db, Film, Actor
from app.cloud import upload_image_url

tmdb_bp = Blueprint("tmdb", __name__)


def tmdb_search_query(q, page=1):
    import requests
    api_key = current_app.config.get("TMDB_API_KEY", "")
    if not api_key:
        return {"error": "TMDB_API_KEY not configured"}
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": api_key, "query": q, "page": page, "include_adult": False, "language": "fr-FR"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


@tmdb_bp.route("/tmdb/search")
def tmdb_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "q required"}), 400
    try:
        res = tmdb_search_query(q)
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
            "poster_path": ("https://image.tmdb.org/t/p/w500" + it["poster_path"]) if it.get("poster_path") else None
        })
    return jsonify({"results": out})


@tmdb_bp.route("/tmdb/import/<int:tmdb_id>", methods=["POST"])
@login_required
def tmdb_import(tmdb_id):
    import requests
    api_key = current_app.config.get("TMDB_API_KEY", "")
    if not api_key:
        flash("TMDB API key non configurée (TMDB_API_KEY).", "error")
        return redirect(url_for("main.index"))

    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    params = {"api_key": api_key, "language": "fr-FR"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        current_app.logger.exception("TMDB import failed")
        flash("Impossible de récupérer les données TMDB.", "error")
        return redirect(url_for("main.index"))

    title = data.get("title") or data.get("original_title") or f"TMDB-{tmdb_id}"
    overview = data.get("overview") or ""
    productions = ", ".join([p.get("name", "") for p in data.get("production_companies", []) if p.get("name")])[:300]

    realisateurs = ""
    try:
        r2 = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits",
            params={"api_key": api_key}, timeout=10
        )
        r2.raise_for_status()
        credits = r2.json()
        directors = [c.get("name") for c in credits.get("crew", []) if c.get("job") == "Director"]
        if directors:
            realisateurs = ", ".join(directors)[:300]
    except Exception:
        pass

    poster_url = ("https://image.tmdb.org/t/p/w500" + data["poster_path"]) if data.get("poster_path") else None
    img_url = upload_image_url(poster_url) if poster_url else None

    film = Film(
        nom=title,
        resume=overview[:2000],
        realisateurs=realisateurs,
        scenaristes="",
        productions=productions,
        source="tmdb"
    )
    if img_url:
        film.image = img_url
    db.session.add(film)
    db.session.flush()

    try:
        cast = credits.get("cast", [])[:6] if "credits" in locals() else []
        for idx, c in enumerate(cast):
            name = c.get("name") or ""
            if not name:
                continue
            profile_url = ("https://image.tmdb.org/t/p/w200" + c["profile_path"]) if c.get("profile_path") else None
            ac_img = upload_image_url(profile_url) if profile_url else None
            role = c.get("character") or "Acteur"
            actor = Actor(film_id=film.id, nom=name, role=role[:100])
            if ac_img:
                actor.image = ac_img
            db.session.add(actor)
    except Exception:
        pass

    try:
        rv = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos",
            params={"api_key": api_key, "language": "fr-FR"}, timeout=10
        )
        rv.raise_for_status()
        vids = rv.json().get("results", [])
        trailers = [v for v in vids if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
        if not trailers:
            trailers = [v for v in vids if v.get("site") == "YouTube"]
        if trailers:
            film.trailer = (trailers[0].get("key") or "")[:100]
    except Exception:
        pass

    db.session.commit()
    flash(f"Import TMDB réussi : {title} (ID local {film.id}).", "success")
    return redirect(url_for("main.film_detail", film_id=film.id))
