# -*- coding: utf-8 -*-
"""
Nettoyage des noms d'acteurs corrompus par l'import + dedoublonnage.
Usage : python cleanup_actors.py
"""
import sys, os, re, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import db, Actor

app = create_app()

FIXES = {
    "The WachowskisCredited as ''The Wachowski Brothers": "The Wachowskis",
    "screenplay = Eric Roth": "Eric Roth",
    "John Logan (writer)": "John Logan",
    "William Nicholson (writer)": "William Nicholson",
    "Joel CoenAlthough the Coen brothers co-directed this film": "Joel Coen",
    "Rufus (actor)": "Rufus",
}

DROPS = {
    "Joel received sole credit due to Directors Guild of America regulations",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


with app.app_context():
    changed = 0
    for a in Actor.query.all():
        n = (a.nom or "").strip()
        if n in FIXES:
            a.nom = FIXES[n]
            changed += 1
        elif n in DROPS:
            db.session.delete(a)
            changed += 1

    # Dedoublonnage par film + nom normalise
    seen = {}
    to_delete = []
    for a in Actor.query.order_by(Actor.id).all():
        key = (a.film_id, norm(a.nom))
        if key in seen:
            keep = seen[key]
            if not keep.image and a.image:
                keep.image = a.image
            to_delete.append(a)
        else:
            seen[key] = a
    for a in to_delete:
        db.session.delete(a)

    db.session.commit()
    print(f"Nettoyage termine : {changed} noms corriges, {len(to_delete)} doublons supprimes.")
    print(f"Acteurs en base : {Actor.query.count()}")
