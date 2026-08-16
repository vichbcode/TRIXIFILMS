# TRIXIFILMS

Application Flask de catalogue de films avec notation, commentaires et import TMDB.

## Installation

```bash
python -m venv venv
source venv/bin/activate  # ou venv\Scripts\activate sous Windows
pip install -r requirements.txt
```

## Configuration

Copier `.env.example` vers `.env` et ajuster les variables :

```bash
cp .env.example .env
```

Variables requises :
- `FLASK_SECRET` — clé secrète Flask (obligatoire en production)
- `ADMIN_PASS` ou `ADMIN_PASS_HASH` — mot de passe admin

Variables optionnelles :
- `TMDB_API_KEY` — clé API TMDB pour l'import de films
- `FLASK_ENV` — `development` ou `production`
- `PORT` — port d'écoute (défaut : 5000)

## Clés API optionnelles (gratuites)

Les clés ne sont **pas obligatoires** : l'import depuis Wikipedia (`import_wikipedia.py`)
fonctionne sans aucune clé. Elles activent seulement l'import TMDB (web + app).

- **TMDB** (gratuit) : créer un compte sur https://www.themoviedb.org/ → Paramètres → API →
  « Créer une clé API ». Variable : `TMDB_API_KEY` dans `.env`.
- **OMDB** (gratuit, limité à 1 000 requêtes/jour) : https://www.omdbapi.com/apikey.aspx
  (une clé par email). Données structurées (genre, réalisateur, acteurs, pays, affiche).
  Variable : `OMDB_API_KEY`.

## Sécurité

- En production : définir `FLASK_SECRET` et `JWT_SECRET` (jetons JWT de l'API).
- XSS : les templates échappent tout contenu utilisateur (aucun `|safe`).
- CSRF activé partout (formulaires web), JWT pour l'API mobile.
- Rate-limiting + verrouillage sur login, inscription et ajouts.
- HTTPS forcé en production (Talisman + HSTS).

## Migration depuis l'ancien format Excel

```bash
python migrate.py
```

## Lancement

```bash
python app.py
```

## Stockage des images (Cloudinary)

Les images (affiches et photos d'acteurs) sont hébergées sur **Cloudinary**
et plus stockées en base. Chaque enregistrement possède une colonne `image`
contenant l'URL Cloudinary. Ajouter dans `.env` :

```
CLOUDINARY_CLOUD_NAME="..."
CLOUDINARY_API_KEY="..."
CLOUDINARY_API_SECRET="..."
CLOUDINARY_FOLDER="trixifilms"   # optionnel
```

Migrer les images déjà présentes en base (BLOB) vers Cloudinary (une seule fois) :

```bash
python migrate_images_cloudinary.py
```

## Migration SQLite → PostgreSQL

L'application lit la base via `DATABASE_URL`. En local, la valeur par défaut
reste SQLite ; en production (ou pour passer à PostgreSQL), pointer vers une
base PostgreSQL :

```
DATABASE_URL="postgresql+psycopg2://postgres:motdepasse@localhost:5432/trixifilms"
```

Étapes :
1. Créer la base cible : `CREATE DATABASE trixifilms;`
2. Migrer d'abord les images vers Cloudinary (voir plus haut).
3. Copier les données :

```bash
python migrate_to_postgres.py          # copie SQLite -> PostgreSQL
python migrate_to_postgres.py --reset  # vide d'abord la base cible
```

La recherche ignore les accents via `translate()` (compatible SQLite et PostgreSQL).

## Structure

```
app/
  __init__.py       → Factory create_app()
  config.py         → Configuration (classes Config/Dev/Prod)
  models.py         → Modèles SQLAlchemy (Film, Actor, Rating, Message)
  utils.py          → Helpers (images, texte, notation)
  routes/
    main.py         → Routes films (CRUD, notation, messages)
    admin.py        → Routes admin (login, logout, clear)
    tmdb.py         → Routes TMDB (search, import)
templates/          → Jinja2 templates
static/             → CSS, JS, images
data/uploads/       → Images uploadées (hors du web root)
migrate.py          → Script de migration Excel → SQLite
```

## Changements récents

- Migration Excel → SQLite (via SQLAlchemy)
- Modularisation en blueprints
- Pagination (24 films/page)
- Nettoyage des images orphelines à la suppression
- `.gitignore` + `requirements.txt` + `.env.example`
- Mots de passe : plus de fallback en dur (variables d'environnement)
- CSS inline déplacé dans `static/movie.css`
- Image placeholder `static/no_image.svg`
- Images déplacées vers Cloudinary (URL stockée dans la colonne `image`)
- Support PostgreSQL (recherche compatible via `translate()`, script `migrate_to_postgres.py`)
