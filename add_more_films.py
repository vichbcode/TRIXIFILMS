# -*- coding: utf-8 -*-
"""
Ajoute de nouveaux films a TRIXIFILMS en utilisant l'import Wikipedia.
Criteres : vraie affiche de film (portrait, pas de logo), bonnes infos,
resume reel (pas de faux resume).

Usage:
    python add_more_films.py          # importe tous les films de la liste
    python add_more_films.py --limit 3  # n'importe que les 3 premiers (test)
"""

import sys
import os
import io
import time
import argparse

sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp")
sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
os.chdir(r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")

import import_wikipedia as wiki
from app import create_app
from app.models import db, Film, Actor
from app.cloud import upload_image_bytes

from PIL import Image

# (requete de recherche, nom affiche, page Wikipedia FR forcee ou None)
FILMS = [
    ("Fight Club", "Fight Club", None),
    ("Alien", "Alien", None),
    ("Blade Runner", "Blade Runner", None),
    ("Psycho", "Psycho", "Psychose (film)"),
    ("Parasite", "Parasite", None),
    ("Joker", "Joker", None),
    ("Les Sept Samouraïs", "Les Sept Samouraïs", None),
    ("Le Voyage de Chihiro", "Le Voyage de Chihiro", None),
    ("Old Boy", "Old Boy", None),
    ("La Cité de Dieu", "La Cité de Dieu", None),
    ("Douze Hommes en colère", "Douze Hommes en colère", None),
    ("Fenêtre sur cour", "Fenêtre sur cour", None),
    ("There Will Be Blood", "There Will Be Blood", None),
    ("Le Magicien d'Oz", "Le Magicien d'Oz", "Le Magicien d'Oz"),
    ("Lawrence d'Arabie", "Lawrence d'Arabie", None),
    ("Le Bon, la Brute et le Truand", "Le Bon, la Brute et le Truand", None),
    ("La Mort aux trousses", "La Mort aux trousses", None),
    ("Eternal Sunshine of the Spotless Mind", "Eternal Sunshine of the Spotless Mind", None),
    ("Donnie Darko", "Donnie Darko", None),
    ("Autant en emporte le vent", "Autant en emporte le vent", None),
    ("Requiem for a Dream", "Requiem for a Dream", None),
    ("Le Réseau social", "The Social Network", "The Social Network"),
    ("Blade Runner 2049", "Blade Runner 2049", None),
    ("Premier Contact", "Premier Contact", None),
    ("Trainspotting", "Trainspotting", None),
    ("La Haine", "La Haine", None),
    ("Assurance sur la mort", "Assurance sur la mort", None),
    ("La Garçonnière", "La Garçonnière", None),
]

DELAY = 8.0


def download_poster(url):
    """Telecharge une image et verifie que c'est bien une image valide."""
    try:
        r = wiki.WIKI_SESSION.get(url, timeout=30)
        if r.status_code != 200:
            return None
        ct = (r.headers.get("Content-Type") or "").lower()
        if not ct.startswith("image/"):
            return None
        try:
            with Image.open(io.BytesIO(r.content)) as im:
                im.verify()
        except Exception:
            return None
        return {"data": r.content, "mime": ct}
    except Exception:
        return None


def is_good_poster(data):
    """Vraie affiche = format portrait (ratio largeur/hauteur ~ 0.55 - 0.85).
    Un logo ou une image carree/large est rejete."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if h <= 0 or w <= 0:
                return False
            ratio = w / h
            return 0.55 <= ratio <= 0.85
    except Exception:
        return False


def pick_poster(w):
    """Retourne {"data","mime"} ou None. Priorite affiche FR, fallback affiches EN."""
    if w.get("image_url"):
        img = download_poster(w["image_url"])
        if img and is_good_poster(img["data"]):
            return img
    if w.get("en_title"):
        for en_url in wiki._get_en_poster_urls(w["en_title"]):
            img = download_poster(en_url)
            if img and is_good_poster(img["data"]):
                return img
    return None


def import_one(query, nom, override, dry=False):
    page = override or wiki.search_wikipedia_page(query)
    if not page:
        return ("E", f"page introuvable")
    w = wiki.fetch_infobox(page)
    if not w or not w.get("infobox"):
        return ("E", f"pas d'infobox ({page})")
    data = wiki.parse_infobox_data(w["infobox"])
    resume = (data.get("resume") or w.get("resume") or "").strip()[:2000]
    if len(resume) < 30:
        return ("E", f"resume trop court ({page})")

    poster = pick_poster(w)

    if dry:
        return ("OK(dry)", f"resume {len(resume)}c, poster {'oui' if poster else 'NON'}, cat={data.get('categorie') or '?'}, orig={data.get('origine') or '?'}, real={data.get('realisateurs') or '?'}")

    film = Film(
        nom=nom[:200],
        titre_original=(data.get("titre_original") or "")[:300],
        langue_originale=(data.get("langue_originale") or "")[:100],
        resume=resume,
        realisateurs=(data.get("realisateurs") or "")[:300],
        scenaristes=(data.get("scenaristes") or "")[:300],
        productions=(data.get("productions") or "")[:300],
        categorie=(data.get("categorie") or "")[:100],
        origine=(data.get("origine") or "")[:100],
        source="wiki",
    )
    if poster:
        film.image = upload_image_bytes(poster["data"], poster["mime"]) or ""
    db.session.add(film)
    db.session.flush()

    nb = 0
    for a in data.get("acteurs") or []:
        anom = (a.get("nom") or "").strip()[:120]
        if not anom:
            continue
        db.session.add(Actor(film_id=film.id, nom=anom, role=(a.get("role") or "Acteur")[:100]))
        nb += 1

    db.session.commit()
    return ("OK", f"poster={'oui' if poster else 'NON'}, acteurs={nb}, resume={len(resume)}c")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        existing = {f.nom.lower() for f in Film.query.all()}
        todo = [(q, n, o) for q, n, o in FILMS if n.lower() not in existing]
        if args.limit:
            todo = todo[:args.limit]

        print(f"{len(todo)} film(s) a traiter (deja presents: {len(FILMS) - len(todo)})", flush=True)
        ok = 0
        fails = []
        for i, (q, n, o) in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {n} ...", flush=True)
            try:
                status, msg = import_one(q, n, o, dry=args.dry)
                print(f"    -> {status}: {msg}", flush=True)
                if status.startswith("OK"):
                    ok += 1
                else:
                    fails.append((n, msg))
            except Exception as e:
                db.session.rollback()
                print(f"    -> E: {e}", flush=True)
                fails.append((n, str(e)))
            if i < len(todo):
                time.sleep(DELAY)

        print(f"\nResultat: {ok} OK, {len(fails)} echecs", flush=True)
        for n, r in fails:
            print(f"  - {n}: {r}", flush=True)
        print(f"total films en base: {Film.query.count()}", flush=True)


if __name__ == "__main__":
    main()
