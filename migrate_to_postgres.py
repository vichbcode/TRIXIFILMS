# -*- coding: utf-8 -*-
"""
Migration de la base SQLite vers PostgreSQL.

Copie toutes les données (films, acteurs, notes, messages, users, boxs, tops)
de la base SQLite source vers la base PostgreSQL cible pointée par DATABASE_URL.
Les colonnes d'images en base (image_data / image_mime) ne sont PAS copiées :
les images doivent d'abord être migrées vers Cloudinary
(voir migrate_images_cloudinary.py) — seule la colonne `image` (URL) est copiée.

Prérequis :
- La base PostgreSQL cible doit exister (CREATE DATABASE ...).
- DATABASE_URL doit pointer vers PostgreSQL (variable du .env ou env).
- Optionnel : TRIXIFILMS_SQLITE_URL pour changer la source (défaut : sqlite:///trixifilms.db)

Usage :
    python migrate_to_postgres.py            # copie les données
    python migrate_to_postgres.py --reset    # vide d'abord la cible (drop tables)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import MetaData, create_engine, text

SRC_URL = os.environ.get("TRIXIFILMS_SQLITE_URL", "sqlite:///trixifilms.db")
TARGET_URL = os.environ.get("DATABASE_URL", "").strip()
if TARGET_URL.startswith("postgres://"):
    TARGET_URL = "postgresql://" + TARGET_URL[len("postgres://"):]

TABLE_ORDER = [
    "users", "films", "acteurs", "notations",
    "messages", "boxs", "box_films", "top_films",
]
EXCLUDE_COLS = {
    "films": ["image_data", "image_mime"],
    "acteurs": ["image_data", "image_mime"],
}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not TARGET_URL or "postgres" not in TARGET_URL:
        print("ERREUR : DATABASE_URL doit pointer vers PostgreSQL.")
        print("Exemple : postgresql+psycopg2://postgres:motdepasse@localhost:5432/trixifilms")
        sys.exit(1)

    from app import create_app
    from app import db

    app = create_app()  # db.create_all() crée le schéma sur le PostgreSQL cible

    if "--reset" in sys.argv:
        with app.app_context():
            db.metadata.drop_all(bind=db.engine)
            db.create_all()
        print("Cible vidée (--reset).")

    src_engine = create_engine(SRC_URL)
    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    with app.app_context():
        db.create_all()
        tgt_meta = MetaData()
        tgt_meta.reflect(bind=db.engine)

    with app.app_context():
        with src_engine.connect() as src_conn, db.engine.connect() as tgt_conn:
            for table_name in TABLE_ORDER:
                if table_name not in src_meta.tables:
                    print(f"[{table_name}] absente de la source — ignorée.")
                    continue
                src_table = src_meta.tables[table_name]
                tgt_table = tgt_meta.tables.get(table_name)
                if tgt_table is None:
                    print(f"[{table_name}] absente de la cible — ignorée.")
                    continue
                cols = [c.name for c in src_table.columns
                        if c.name not in EXCLUDE_COLS.get(table_name, [])]
                cols = [c for c in cols if c in tgt_table.c]
                rows = src_conn.execute(src_table.select()).fetchall()
                data = [{c: row._mapping[c] for c in cols} for row in rows]
                if data:
                    tgt_conn.execute(tgt_table.insert(), data)
                print(f"[{table_name}] {len(rows)} lignes copiées.")

            for table_name in TABLE_ORDER:
                seq = tgt_conn.execute(text(
                    f"SELECT pg_get_serial_sequence('{table_name}', 'id')"
                )).scalar()
                if seq:
                    max_id = tgt_conn.execute(text(
                        f"SELECT COALESCE(MAX(id), 1) FROM {table_name}"
                    )).scalar()
                    tgt_conn.execute(text(f"SELECT setval('{seq}', {max_id})"))
                    print(f"[{table_name}] séquence ajustée -> {max_id}")
            tgt_conn.commit()

    print("\nMigration terminée.")


if __name__ == "__main__":
    main()