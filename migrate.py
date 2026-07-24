"""
Migration script: Excel (.xlsx) -> SQLite (.db)

Usage: python migrate.py
Requires pandas and openpyxl installed (already in requirements.txt).
"""

import os
import sys

import pandas as pd


APP_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_FILE = os.path.join(APP_DIR, "trixifilms.xlsx")
DB_PATH = os.path.join(APP_DIR, "trixifilms.db")


def migrate():
    if not os.path.exists(EXCEL_FILE):
        print(f"Aucun fichier Excel trouvé : {EXCEL_FILE}")
        print("Rien à migrer.")
        return

    print(f"Lecture de {EXCEL_FILE}...")
    xls = pd.read_excel(EXCEL_FILE, sheet_name=None, engine="openpyxl")

    from app import create_app
    from app.models import db, Film, Actor, Rating, Message

    app = create_app()

    with app.app_context():
        db.drop_all()
        db.create_all()

        df_films = xls.get("Films", pd.DataFrame())
        for _, row in df_films.iterrows():
            film = Film(
                nom=str(row.get("Nom", "") or "")[:200],
                resume=str(row.get("Résumé", "") or "")[:2000],
                realisateurs=str(row.get("Réalisateurs", "") or "")[:300],
                scenaristes=str(row.get("Scénaristes", "") or "")[:300],
                productions=str(row.get("Productions", "") or "")[:300],
                image=str(row.get("Image", "") or "")[:500],
                source=str(row.get("Source", "") or "")[:20],
            )
            db.session.add(film)
        db.session.commit()
        print(f"  Films: {len(df_films)} importés")

        df_acteurs = xls.get("Acteurs", pd.DataFrame())
        for _, row in df_acteurs.iterrows():
            film_id = row.get("Film_ID", "")
            try:
                film_id = int(film_id)
            except (ValueError, TypeError):
                continue
            # Check referenced film exists
            if not db.session.get(Film, film_id):
                continue
            actor = Actor(
                film_id=film_id,
                nom=str(row.get("Nom", "") or "")[:120],
                image=str(row.get("Image", "") or "")[:500],
                role=str(row.get("Role", "") or "Acteur")[:100],
            )
            db.session.add(actor)
        db.session.commit()
        print(f"  Acteurs: {len(df_acteurs)} importés")

        df_notations = xls.get("Notations", pd.DataFrame())
        for _, row in df_notations.iterrows():
            film_id = row.get("Film_ID", "")
            try:
                film_id = int(film_id)
            except (ValueError, TypeError):
                continue
            if not db.session.get(Film, film_id):
                continue
            try:
                note = float(row.get("Note", 0))
            except (ValueError, TypeError):
                note = 0.0
            rating = Rating(
                film_id=film_id,
                prenom=str(row.get("Prénom", "") or "")[:100],
                note=note,
            )
            db.session.add(rating)
        db.session.commit()
        print(f"  Notations: {len(df_notations)} importées")

        df_messages = xls.get("Messages", pd.DataFrame())
        for _, row in df_messages.iterrows():
            film_id = row.get("Film_ID", "")
            try:
                film_id = int(film_id)
            except (ValueError, TypeError):
                continue
            if not db.session.get(Film, film_id):
                continue
            msg = Message(
                film_id=film_id,
                prenom=str(row.get("Prénom", "") or "")[:100],
                message=str(row.get("Message", "") or ""),
                created_at=str(row.get("Created_At", "") or "")[:20],
            )
            db.session.add(msg)
        db.session.commit()
        print(f"  Messages: {len(df_messages)} importés")

    print(f"\nMigration terminée ! Base de données : {DB_PATH}")


if __name__ == "__main__":
    # Ensure the app directory is importable
    sys.path.insert(0, APP_DIR)
    migrate()
