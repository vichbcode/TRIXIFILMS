# -*- coding: utf-8 -*-
"""
1) Reimporte les films qui ont echoue (limites de debit) lors de add_more_films.
2) Ajoute une vraie affiche de film aux films qui n'en ont pas.

Usage:
    python fix_posters.py
"""

import sys
import os
import time

sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp")
sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
os.chdir(r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")

import import_wikipedia as wiki
from app import create_app
from app.models import db, Film, Actor
from app.cloud import upload_image_bytes
from add_more_films import download_poster, is_good_poster, import_one

RETRY_FILMS = [
    ("Blade Runner", "Blade Runner", None),
    ("Les Sept Samouraïs", "Les Sept Samouraïs", None),
    ("La Cité de Dieu", "La Cité de Dieu", "La Cité de Dieu (film)"),
    ("Le Magicien d'Oz", "Le Magicien d'Oz", "Le Magicien d'Oz"),
    ("Le Réseau social", "The Social Network", "The Social Network"),
    ("Trainspotting", "Trainspotting", None),
]

# nom affiche -> titre EN Wikipedia connu (fiable pour l'affiche)
EN_TITLES = {
    "Parasite": "Parasite (2019 film)",
    "Joker": "Joker (2019 film)",
    "There Will Be Blood": "There Will Be Blood",
    "Le Bon, la Brute et le Truand": "The Good, the Bad and the Ugly",
    "Eternal Sunshine of the Spotless Mind": "Eternal Sunshine of the Spotless Mind",
    "Autant en emporte le vent": "Gone with the Wind (film)",
    "Requiem for a Dream": "Requiem for a Dream",
    "La Garçonnière": "The Apartment",
    "The Social Network": "The Social Network",
    "Trainspotting": "Trainspotting (film)",
    "Blade Runner 2049": "Blade Runner 2049",
    "Premier Contact": "Arrival (film)",
}


def fetch_poster_for(film):
    """Essaie d'attacher une vraie affiche au film donne. Retourne True si OK."""
    w = None
    try:
        w = wiki.fetch_infobox(film.nom)
    except Exception:
        w = None

    en_title = EN_TITLES.get(film.nom)
    if (not en_title) and w:
        en_title = w.get("en_title")

    img = None
    # 1) Affiche EN (la plus fiable) - plusieurs candidates
    if en_title:
        for en_url in wiki._get_en_poster_urls(en_title):
            img = download_poster(en_url)
            if img and is_good_poster(img["data"]):
                break
            img = None
    # 2) Affiche FR
    if not img and w and w.get("image_url"):
        img = download_poster(w["image_url"])
        if img and not is_good_poster(img["data"]):
            img = None

    if img:
        film.image = upload_image_bytes(img["data"], img["mime"]) or film.image
        db.session.commit()
        return True
    return False


def main():
    app = create_app()
    with app.app_context():
        # 1) Reimport des films echoues
        existing = {f.nom.lower() for f in Film.query.all()}
        todo = [(q, n, o) for q, n, o in RETRY_FILMS if n.lower() not in existing]
        if todo:
            print(f"== Reimport ({len(todo)}) ==", flush=True)
            for i, (q, n, o) in enumerate(todo, 1):
                print(f"[{i}/{len(todo)}] {n} ...", flush=True)
                try:
                    status, msg = import_one(q, n, o)
                    print(f"    -> {status}: {msg}", flush=True)
                except Exception as e:
                    db.session.rollback()
                    print(f"    -> E: {e}", flush=True)
                if i < len(todo):
                    time.sleep(8)

        # 2) Posters manquants
        nopost = Film.query.filter((Film.image.is_(None)) | (Film.image == "")).order_by(Film.id).all()
        if nopost:
            print(f"== Posters manquants ({len(nopost)}) ==", flush=True)
            for i, film in enumerate(nopost, 1):
                print(f"[{i}/{len(nopost)}] {film.nom} ...", flush=True)
                ok = fetch_poster_for(film)
                print(f"    -> {'poster OK' if ok else 'toujours sans affiche'}", flush=True)
                if i < len(nopost):
                    time.sleep(8)

        print(f"\ntotal films: {Film.query.count()}", flush=True)
        still = Film.query.filter((Film.image.is_(None)) | (Film.image == "")).count()
        print(f"films sans affiche restants: {still}", flush=True)


if __name__ == "__main__":
    main()
