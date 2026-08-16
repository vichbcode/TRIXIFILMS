# -*- coding: utf-8 -*-
"""
Ajoute les images manquantes a TRIXIFILMS :
  - affiches de films reelles (portrait, pas de logo)
  - photos des acteurs sans image (Wikipedia FR puis EN)

Usage :
    python add_images.py                  # tout traiter
    python add_images.py --only posters   # seulement les affiches manquantes
    python add_images.py --only actors    # seulement les photos d'acteurs
    python add_images.py --repair         # re-verifie aussi les affiches non-portrait
"""

import sys
import os
import io
import time
import re
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from PIL import Image

from app import create_app
from app.models import db, Film, Actor
from app.cloud import upload_image_bytes
import import_wikipedia as wiki
from add_more_films import download_poster, is_good_poster

WIKI_UA = "TRIXIFILMS-Import/1.0 (Wikipedia image import)"
S = requests.Session()
S.headers.update({"User-Agent": WIKI_UA})

MIME_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
}


def api(lang, params, tries=4, pause=10):
    """Appel API MediaWiki avec retry et backoff (rate-limit 429)."""
    for a in range(tries):
        try:
            r = S.get(f"https://{lang}.wikipedia.org/w/api.php",
                      params=params, timeout=25)
            if r.status_code == 429:
                print(f"    [rate-limit] pause {pause * (a + 1)}s...", flush=True)
                time.sleep(pause * (a + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(3)
    return None


def download_image(url):
    """Telecharge une image valide depuis une URL."""
    if not url:
        return None
    try:
        r = S.get(url, timeout=30)
        if r.status_code == 429:
            time.sleep(8)
            r = S.get(url, timeout=30)
        r.raise_for_status()
        data = r.content
        if not data:
            return None
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        ct = r.headers.get("Content-Type", "").lower()
        if ct.startswith("image/"):
            mime = ct
        else:
            ext = url.rsplit(".", 1)[-1].lower().split("?")[0] if "." in url else ""
            mime = MIME_EXT.get(ext, "image/jpeg")
        return {"data": data, "mime": mime}
    except Exception:
        return None


def find_actor_photo(name):
    """Photo de l'acteur depuis Wikipedia (FR d'abord, sinon EN)."""
    q = re.sub(r"\s+", " ", (name or "").strip().replace(":", " "))
    if len(q) < 3:
        return None
    for lang in ("fr", "en"):
        d = api(lang, {"action": "query", "list": "search", "srsearch": q,
                       "srlimit": 5, "format": "json", "formatversion": "2"})
        if not d:
            continue
        results = d.get("query", {}).get("search", [])
        for res in results:
            title = res.get("title", "")
            low = title.lower()
            if any(bad in low for bad in ("(film)", "(serie)", " film)", " serie)")):
                continue
            d2 = api(lang, {"action": "query", "titles": title, "prop": "pageimages",
                            "pithumbsize": 300, "format": "json",
                            "formatversion": "2", "redirects": 1})
            if not d2:
                continue
            for p in d2.get("query", {}).get("pages", []):
                th = p.get("thumbnail")
                if th:
                    src = th.get("source")
                    if src and not src.lower().endswith(".svg"):
                        return src
        time.sleep(0.3)
    return None


def find_en_film_title(name):
    """Cherche le titre Wikipedia EN d'un film a partir de son nom affiche."""
    q = re.sub(r"\s+", " ", (name or "").strip().replace(":", " "))
    if not q:
        return None
    for sr in (q, q + " (film)"):
        d = api("en", {"action": "query", "list": "search", "srsearch": sr,
                       "srlimit": 5, "format": "json", "formatversion": "2"})
        if not d:
            continue
        for res in d.get("query", {}).get("search", []):
            title = res.get("title", "")
            low = title.lower()
            if low.replace(":", " ") == q.lower():
                return title
            if "(film)" in low and q.lower().split()[0] in low:
                return title
        if d.get("query", {}).get("search"):
            return d["query"]["search"][0]["title"]
        time.sleep(0.3)
    return None


def fetch_film_poster(film):
    """Vraie affiche de film (portrait). Retourne {"data","mime"} ou None."""
    en_title = None
    w = None
    fr_page = None
    try:
        fr_page = wiki.search_wikipedia_page(film.nom)
    except Exception:
        fr_page = None
    if fr_page:
        try:
            w = wiki.fetch_infobox(fr_page)
            if w:
                en_title = w.get("en_title")
        except Exception:
            w = None

    if not en_title:
        en_title = find_en_film_title(film.nom)

    # 1) Affiche Wikipedia EN (la plus fiable)
    if en_title:
        for url in wiki._get_en_poster_urls(en_title):
            img = download_poster(url)
            if img and is_good_poster(img["data"]):
                return img

    # 2) Affiche FR
    if w and w.get("image_url"):
        img = download_poster(w["image_url"])
        if img and is_good_poster(img["data"]):
            return img
    return None


def is_portrait(data):
    """True si l'image est une affiche portrait (et non un logo carre/large)."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if h <= 0 or w <= 0:
                return False
            ratio = w / h
            return 0.5 <= ratio <= 0.9
    except Exception:
        return False


def _film_has_poster(film):
    if not film.image:
        return False
    try:
        data = download_image(film.image)
        if data:
            return is_portrait(data["data"])
    except Exception:
        pass
    return False


def add_posters(repair=False):
    app = create_app()
    with app.app_context():
        if repair:
            films = [f for f in Film.query.order_by(Film.id).all()
                     if not _film_has_poster(f)]
        else:
            films = Film.query.filter((Film.image.is_(None)) | (Film.image == "")).order_by(Film.id).all()
        print(f"== Affiches a traiter : {len(films)} ==", flush=True)
        ok = 0
        for i, film in enumerate(films, 1):
            print(f"[{i}/{len(films)}] {film.nom} (id={film.id}) ...", flush=True)
            img = fetch_film_poster(film)
            if img:
                film.image = upload_image_bytes(img["data"], img["mime"]) or film.image
                db.session.commit()
                ok += 1
                print(f"    -> affiche OK ({len(img['data'])} octets)", flush=True)
            else:
                print(f"    -> pas d'affiche trouvee", flush=True)
            time.sleep(1)
        print(f"\nAffiches ajoutees : {ok}/{len(films)}", flush=True)
        still = Film.query.filter((Film.image.is_(None)) | (Film.image == "")).count()
        print(f"films sans affiche restants : {still}", flush=True)


def add_actor_photos():
    app = create_app()
    with app.app_context():
        actors = Actor.query.filter((Actor.image.is_(None)) | (Actor.image == "")).order_by(Actor.id).all()
        print(f"== Photos d'acteurs manquantes : {len(actors)} ==", flush=True)
        ok = 0
        for i, actor in enumerate(actors, 1):
            print(f"[{i}/{len(actors)}] {actor.nom} (id={actor.id}) ...", flush=True)
            src = find_actor_photo(actor.nom)
            if src:
                img = download_image(src)
                if img:
                    actor.image = upload_image_bytes(img["data"], img["mime"]) or ""
                    db.session.commit()
                    ok += 1
                    print(f"    -> photo OK ({len(img['data'])} octets)", flush=True)
                else:
                    print(f"    -> telechargement echoue", flush=True)
            else:
                print(f"    -> photo introuvable", flush=True)
            time.sleep(0.4)
        print(f"\nPhotos ajoutees : {ok}/{len(actors)}", flush=True)
        still = Actor.query.filter((Actor.image.is_(None)) | (Actor.image == "")).count()
        print(f"acteurs sans photo restants : {still}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["posters", "actors", "all"], default="all")
    parser.add_argument("--repair", action="store_true",
                        help="re-verifie et remplace les affiches non-portrait (logos)")
    args = parser.parse_args()

    if args.only in ("posters", "all"):
        add_posters(repair=args.repair)
    if args.only in ("actors", "all"):
        add_actor_photos()
