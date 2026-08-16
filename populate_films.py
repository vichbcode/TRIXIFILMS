import sys, os, time

sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp")
os.chdir(r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")

import import_wikipedia as wiki
from app import create_app
from app.models import db, Film, Actor
from app.utils import process_image_from_url

FILMS = [
    "Inception", "Fight Club", "The Prestige", "Joker", "Alien",
    "Blade Runner", "The Terminator", "Taxi Driver", "Apocalypse Now",
    "One Flew Over the Cuckoo's Nest", "Psycho", "Vertigo", "Citizen Kane",
    "La La Land", "Mad Max: Fury Road", "Whiplash", "Parasite",
    "The Departed", "No Country for Old Men", "The Big Lebowski",
    "Le Fabuleux Destin d'Amelie Poulain", "The Truman Show",
    "The Green Mile", "Gladiator",
]

app = create_app()
with app.app_context():
    existing = {f.nom for f in Film.query.all()}
    todo = [n for n in FILMS if n not in existing]
    print(f"à traiter: {len(todo)}", flush=True)
    ok = 0
    failed = []
    for name in todo:
        try:
            page = wiki.search_wikipedia_page(name)
            if not page:
                failed.append((name, "page introuvable"))
                print(f"E {name}: page introuvable", flush=True)
                continue
            w = wiki.fetch_infobox(page)
            if not w:
                failed.append((name, "infobox"))
                print(f"E {name}: pas d'infobox", flush=True)
                continue
            data = wiki.parse_infobox_data(w["infobox"])
            film = Film(
                nom=name[:200],
                titre_original=(data.get("titre_original") or "")[:300],
                langue_originale=(data.get("langue_originale") or "")[:100],
                resume=(data.get("resume") or w.get("resume") or "")[:2000],
                realisateurs=(data.get("realisateurs") or "")[:300],
                scenaristes=(data.get("scenaristes") or "")[:300],
                productions=(data.get("productions") or "")[:300],
                categorie=(data.get("categorie") or "")[:100],
                origine=(data.get("origine") or "")[:100],
                source="wiki",
            )
            if w.get("image_url"):
                img = process_image_from_url(w["image_url"])
                if img:
                    film.image = img["url"]
            db.session.add(film)
            db.session.flush()
            nb_actors = 0
            for a in data.get("acteurs") or []:
                anom = (a.get("nom") or "").strip()[:120]
                if not anom:
                    continue
                db.session.add(Actor(film_id=film.id, nom=anom, role=(a.get("role") or "Acteur")[:100]))
                nb_actors += 1
            db.session.commit()
            ok += 1
            print(f"OK {name} (acteurs: {nb_actors})", flush=True)
        except Exception as e:
            db.session.rollback()
            failed.append((name, str(e)))
            print(f"E {name}: {e}", flush=True)

    print(f"\nRésultat: {ok} importés, {len(failed)} échecs", flush=True)
    for name, reason in failed:
        print(f"  - {name}: {reason}", flush=True)
    print(f"total films en base: {Film.query.count()}", flush=True)
