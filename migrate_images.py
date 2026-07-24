"""
Script de migration : copie les images stockées sur le disque vers la base de données
(colonnes image_data / image_mime).

Usage : python migrate_images.py
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models import db, Film, Actor

app = create_app()

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}

with app.app_context():
    count_film = 0
    for film in Film.query.all():
        if film.image and not film.image_data:
            path = film.image.lstrip("/")
            full_path = os.path.join(app.root_path, "..", path)
            if os.path.exists(full_path):
                ext = os.path.splitext(full_path)[1].lower()
                mime = MIME_MAP.get(ext, "image/jpeg")
                with open(full_path, "rb") as f:
                    film.image_data = f.read()
                film.image_mime = mime
                count_film += 1
                print(f"  Film #{film.id}: {film.nom} ({len(film.image_data)} bytes)")
            else:
                print(f"  Film #{film.id}: fichier introuvable -> {full_path}")

    count_actor = 0
    for actor in Actor.query.all():
        if actor.image and not actor.image_data:
            path = actor.image.lstrip("/")
            full_path = os.path.join(app.root_path, "..", path)
            if os.path.exists(full_path):
                ext = os.path.splitext(full_path)[1].lower()
                mime = MIME_MAP.get(ext, "image/jpeg")
                with open(full_path, "rb") as f:
                    actor.image_data = f.read()
                actor.image_mime = mime
                count_actor += 1
                print(f"  Actor #{actor.id}: {actor.nom} ({len(actor.image_data)} bytes)")
            else:
                print(f"  Actor #{actor.id}: fichier introuvable -> {full_path}")

    db.session.commit()
    print(f"\nMigration terminée : {count_film} films, {count_actor} acteurs mis à jour.")
