import json
import queue
import re
import threading
import time

import requests

from app.models import db, Film


_trailer_queue = queue.Queue()
_busy = set()
_tried = set()
_lock = threading.Lock()

_YT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
_YT_COOKIES = {"CONSENT": "YES+cb.20240401-11-p0.en+FX+000", "SOCS": "CAISHAgBEhIaAB"}
_TRAILER_WORDS = ("bande", "trailer", "b.a.", "officiel", "officielle", "official", "bande-annonce")


def _api_key(app=None):
    if app is not None:
        return (app.config.get("TMDB_API_KEY") or "").strip()
    from flask import current_app
    return (current_app.config.get("TMDB_API_KEY") or "").strip()


def _search_tmdb(title, api_key):
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": api_key, "query": title, "include_adult": False, "language": "fr-FR"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("results", [])


def _find_trailer_key(tmdb_id, api_key):
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos"
    params = {"api_key": api_key, "language": "fr-FR"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    vids = r.json().get("results", [])
    trailers = [v for v in vids if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if not trailers:
        trailers = [v for v in vids if v.get("site") == "YouTube"]
    return (trailers[0].get("key") or "")[:100] if trailers else ""


def _tmdb_trailer_key(title, api_key):
    for cand in _search_tmdb(title, api_key)[:3]:
        try:
            key = _find_trailer_key(cand.get("id"), api_key)
        except Exception:
            continue
        if key:
            return key
        time.sleep(0.2)
    return ""


def _extract_yt_initial_data(html):
    idx = html.find("ytInitialData")
    while idx != -1:
        start = html.find("{", idx)
        if start == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(html)):
            ch = html[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:i + 1])
                    except Exception:
                        return None
        idx = html.find("ytInitialData", idx + 1)
    return None


def _yt_video_items(data):
    out = []
    try:
        contents = data["contents"]["twoColumnSearchResultsRenderer"] \
            ["primaryContents"]["sectionListRenderer"]["contents"]
    except (KeyError, TypeError):
        return out
    for section in contents:
        for it in section.get("itemSectionRenderer", {}).get("contents", []):
            vr = it.get("videoRenderer")
            if not vr:
                continue
            vid = vr.get("videoId")
            if not vid:
                continue
            if vr.get("isShortsLike"):
                continue
            title = ""
            title_node = vr.get("title") or {}
            runs = title_node.get("runs")
            if runs:
                title = "".join(x.get("text", "") for x in runs)
            else:
                title = title_node.get("simpleText", "") or ""
            length = (vr.get("lengthText") or {}).get("simpleText", "") or ""
            out.append({"id": vid, "title": title, "length": length})
    return out


def _youtube_trailer_key(title):
    query = f"{title} bande annonce officielle"
    r = requests.get(
        "https://www.youtube.com/results",
        params={"search_query": query},
        headers=_YT_HEADERS,
        cookies=_YT_COOKIES,
        timeout=15,
    )
    r.raise_for_status()
    data = _extract_yt_initial_data(r.text)
    if not data:
        return ""
    items = _yt_video_items(data)
    if not items:
        return ""
    items.sort(
        key=lambda it: 1 if any(w in it["title"].lower() for w in _TRAILER_WORDS) else 0,
        reverse=True,
    )
    return items[0]["id"]


def fetch_trailer_for_film(film):
    """Trouve une bande-annonce pour un film (TMDB si clé dispo, sinon recherche YouTube) et met à jour film.trailer."""
    if not film or film.trailer:
        return False

    titles = [film.nom]
    original = (film.titre_original or "").strip()
    if original and original.lower() != (film.nom or "").strip().lower():
        titles.append(original)

    api_key = _api_key()
    for title in titles:
        key = ""
        if api_key:
            try:
                key = _tmdb_trailer_key(title, api_key)
            except Exception:
                key = ""
        if not key:
            try:
                key = _youtube_trailer_key(title)
            except Exception:
                key = ""
        if key:
            film.trailer = key
            db.session.commit()
            return True
        time.sleep(0.3)
    return False


def enqueue_trailer(film_id):
    with _lock:
        if film_id in _busy or film_id in _tried:
            return
        _busy.add(film_id)
    _trailer_queue.put(film_id)


def _tick(app):
    with app.app_context():
        missing = Film.query.filter(
            (Film.trailer.is_(None)) | (Film.trailer == "")
        ).order_by(Film.id.desc()).limit(200).all()
        for f in missing:
            enqueue_trailer(f.id)


def _worker(app):
    while True:
        try:
            film_id = _trailer_queue.get(timeout=10)
        except queue.Empty:
            try:
                _tick(app)
            except Exception:
                pass
            continue
        try:
            with app.app_context():
                film = db.session.get(Film, film_id)
                fetch_trailer_for_film(film)
        except Exception:
            pass
        finally:
            with _lock:
                _busy.discard(film_id)
                _tried.add(film_id)
            time.sleep(0.3)


def start_trailer_worker(app):
    app.logger.info("Démarrage du worker bandes-annonces automatique (YouTube / TMDB)")
    thread = threading.Thread(target=_worker, args=(app,), daemon=True, name="trailer-worker")
    thread.start()
    return thread
