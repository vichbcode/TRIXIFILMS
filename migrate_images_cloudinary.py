# -*- coding: utf-8 -*-
"""
Migration des images existantes (BLOB en base) vers Cloudinary.

À lancer UNE SEULE FOIS, pendant que la base est encore SQLite (ou avant
de migrer vers PostgreSQL). Pour chaque film / acteur possédant une image
dans les colonnes image_data / image_mime, l'image est uploadée sur
Cloudinary et l'URL est stockée dans la colonne `image` (les colonnes
image_data / image_mime sont ensuite vidées).

Prérequis : les variables CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY,
CLOUDINARY_API_SECRET doivent être renseignées (dans .env).

Usage :
    python migrate_images_cloudinary.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import inspect, text

from app import create_app
from app import db
from app.cloud import is_configured, upload_image_bytes


def _has_column(table, col):
    inspector = inspect(db.engine)
    return col in [c["name"] for c in inspector.get_columns(table)]


def migrate_table(table):
    if not _has_column(table, "image_data"):
        print(f"[{table}] colonne image_data absente — rien à migrer.")
        return 0, 0, 0
    rows = db.session.execute(text(
        f"SELECT id, image, image_data, image_mime FROM {table} "
        "WHERE image_data IS NOT NULL AND length(image_data) > 0"
    )).fetchall()
    done = skipped = failed = 0
    for rid, cur_img, data, mime in rows:
        if cur_img and cur_img.startswith("http"):
            skipped += 1
            continue
        url = upload_image_bytes(data, mime or "image/jpeg")
        if url:
            db.session.execute(text(
                f"UPDATE {table} SET image = :url, image_data = NULL, image_mime = '' "
                "WHERE id = :id"
            ), {"url": url, "id": rid})
            done += 1
            if done % 25 == 0:
                db.session.commit()
        else:
            failed += 1
    db.session.commit()
    return done, skipped, failed


def main():
    if not is_configured():
        print("ERREUR : Cloudinary n'est pas configuré. Renseigne les variables")
        print("CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET dans .env")
        sys.exit(1)

    app = create_app()
    with app.app_context():
        for table in ("films", "acteurs"):
            done, skipped, failed = migrate_table(table)
            print(f"[{table}] uploadés : {done} | déjà en ligne : {skipped} | échecs : {failed}")
        remaining = db.session.execute(text(
            "SELECT (SELECT COUNT(*) FROM films WHERE image_data IS NOT NULL AND length(image_data)>0)"
            " + (SELECT COUNT(*) FROM acteurs WHERE image_data IS NOT NULL AND length(image_data)>0)"
        )).scalar()
        print(f"\nRestant en base (image_data) : {remaining}")
        print("Terminé.")


if __name__ == "__main__":
    main()