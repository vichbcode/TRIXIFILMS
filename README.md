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

## Migration depuis l'ancien format Excel

```bash
python migrate.py
```

## Lancement

```bash
python app.py
```

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
