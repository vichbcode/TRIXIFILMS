import sys

sys.path.insert(0, r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
import os
import openpyxl
from sqlalchemy import text

os.chdir(r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS")
from app import create_app
from app.models import db, Film, Actor, Rating, Message

BACKUP = r"Q:\00 TRIXIFILMMSapp\TRIXIFILMS\trixifilms.xlsx.backup.20260305_150548.xlsx"

wb = openpyxl.load_workbook(BACKUP, read_only=True)


def rows(sheet):
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(it)]
    for r in it:
        yield dict(zip(header, r))


app = create_app()
with app.app_context():
    existing = Film.query.count()
    print(f"films avant restauration: {existing}")

    nb_films = nb_acteurs = nb_notes = nb_msgs = 0
    skipped = 0

    for d in rows("Films"):
        fid = d.get("ID")
        try:
            fid = int(fid)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if db.session.get(Film, fid):
            skipped += 1
            continue
        film = Film(
            id=fid,
            nom=str(d.get("Nom") or "")[:200],
            resume=str(d.get("Résumé") or "")[:2000],
            realisateurs=str(d.get("Réalisateurs") or "")[:300],
            scenaristes=str(d.get("Scénaristes") or "")[:300],
            productions=str(d.get("Productions") or "")[:300],
            image=str(d.get("Image") or "")[:500],
        )
        db.session.add(film)
        nb_films += 1
    db.session.commit()

    for d in rows("Acteurs"):
        fid = d.get("Film_ID")
        try:
            fid = int(fid)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not db.session.get(Film, fid):
            skipped += 1
            continue
        actor = Actor(
            film_id=fid,
            nom=str(d.get("Nom") or "")[:120],
            image=str(d.get("Image") or "")[:500],
            role=str(d.get("Role") or "Acteur")[:100],
        )
        db.session.add(actor)
        nb_acteurs += 1
    db.session.commit()

    for d in rows("Notations"):
        fid = d.get("Film_ID")
        try:
            fid = int(fid)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not db.session.get(Film, fid):
            skipped += 1
            continue
        try:
            note = float(d.get("Note") or 0)
        except (ValueError, TypeError):
            note = 0.0
        db.session.add(Rating(film_id=fid, prenom=str(d.get("Prénom") or "")[:100], note=note))
        nb_notes += 1
    db.session.commit()

    for d in rows("Messages"):
        fid = d.get("Film_ID")
        try:
            fid = int(fid)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not db.session.get(Film, fid):
            skipped += 1
            continue
        db.session.add(Message(
            film_id=fid,
            prenom=str(d.get("Prénom") or "")[:100],
            message=str(d.get("Message") or ""),
            created_at=str(d.get("Created_At") or "")[:20],
        ))
        nb_msgs += 1
    db.session.commit()

    print(f"films insérés: {nb_films}")
    print(f"acteurs insérés: {nb_acteurs}")
    print(f"notations insérées: {nb_notes}")
    print(f"messages insérés: {nb_msgs}")
    print(f"ignorés (déjà présents / références manquantes): {skipped}")
    print(f"total films maintenant: {Film.query.count()}")

wb.close()
