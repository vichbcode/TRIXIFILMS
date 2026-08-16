"""
Reparation complete de la base TRIXIFILMS (web).

Pour chaque film (titre Wikipedia EN curse par id) :
  - resume       = intro FR Wikipedia (exintro) nettoyee
  - metadonnees  = infobox FR (titre original, langue, production, genre, pays)
                   + infobox EN (realisateurs, scenaristes) en secours
  - affiche      = image de l'infobox EN (vraie affiche, pas un logo),
                   redimensionnee a 500px de large (JPEG)
  - distribution = cast infobox EN (Acteur / Realisateur / Scenario),
                   en remplacant les acteurs errones
  - photos       = photos d'acteurs recuperees uniquement quand absentes

Usage :
  python fix_films.py                 # tout reparer
  python fix_films.py --limit 10      # seulement les 10 premiers
  python fix_films.py --only 1,2,3    # seulement certains ids
  python fix_films.py --photos        # seulement les photos d'acteurs manquantes
"""
import os
import sys
import re
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from app import create_app
from app.models import db, Film, Actor
from app.cloud import upload_image_bytes

WIKI_UA = "TRIXIFILMS-Repair/1.1 (data repair script)"
S = requests.Session()
S.headers.update({"User-Agent": WIKI_UA})

MIME_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}

# Titres Wikipedia EN exacts pour chaque film de la base (curation manuelle).
EN_TITLES = {
    1: "The Shawshank Redemption",
    2: "The Godfather",
    3: "The Godfather Part II",
    4: "Pulp Fiction",
    5: "The Dark Knight",
    6: "Interstellar (film)",
    7: "The Matrix",
    8: "Forrest Gump",
    9: "The Silence of the Lambs (film)",
    10: "Goodfellas",
    11: "Seven (1995 film)",
    12: "Memento (film)",
    13: "Django Unchained",
    14: "Inglourious Basterds",
    15: "Kill Bill: Volume 1",
    16: "Titanic (1997 film)",
    17: "Gladiator (2000 film)",
    18: "2001: A Space Odyssey (film)",
    19: "The Shining (film)",
    20: "Schindler's List",
    21: "Saving Private Ryan",
    22: "The Lord of the Rings: The Fellowship of the Ring",
    23: "Star Wars (film)",
    24: "Back to the Future",
    25: "Jurassic Park (film)",
    26: "Die Hard",
    27: "Léon: The Professional",
    28: "Casablanca (film)",
    29: "Inception",
    30: "The Prestige (film)",
    31: "The Terminator",
    32: "Taxi Driver",
    33: "Apocalypse Now",
    34: "One Flew Over the Cuckoo's Nest (film)",
    35: "Vertigo (film)",
    36: "Citizen Kane",
    37: "La La Land",
    38: "Mad Max: Fury Road",
    39: "Whiplash (2014 film)",
    40: "The Departed",
    41: "No Country for Old Men",
    42: "The Big Lebowski",
    43: "Amélie",
    44: "The Truman Show",
    45: "The Green Mile (film)",
}

# Titres FR explicites quand le langlink pointe vers une page d'homonymie
# ou est introuvable.
FR_TITLES = {
    6: "Interstellar (film)",
    9: "Le Silence des agneaux (film)",
    11: "Seven (film)",
    12: "Memento (film)",
    15: "Kill Bill : Volume 1",
    21: "Il faut sauver le soldat Ryan",
    43: "Le Fabuleux Destin d'Amélie Poulain",
}

# Productions non recuperables automatiquement (champ absent des infobox).
PROD_OVERRIDES = {
    5: "Warner Bros. Pictures, Legendary Pictures, Syncopy Entertainment",
    17: "DreamWorks Pictures, Universal Pictures, Scott Free Productions",
    22: "New Line Cinema, WingNut Films, Weta Digital",
    24: "Amblin Entertainment, Universal Pictures",
    43: "Claudie Ossard Productions, UGC Images, France 3 Cinéma",
}

# Mapping pays EN -> origine FR
COUNTRY_MAP = [
    ("united states", "Américaine"), ("u.s.", "Américaine"), ("america", "Américaine"),
    ("france", "Française"),
    ("united kingdom", "Britannique"), ("england", "Britannique"), ("britain", "Britannique"),
    ("scotland", "Britannique"), ("wales", "Britannique"),
    ("germany", "Allemande"), ("west germany", "Allemande"),
    ("italy", "Italienne"),
    ("spain", "Espagnole"),
    ("japan", "Japonaise"),
    ("south korea", "Coréenne"), ("korea", "Coréenne"),
    ("china", "Chinoise"), ("hong kong", "Chinoise"),
    ("india", "Indienne"),
    ("russia", "Russe"), ("soviet union", "Russe"),
    ("australia", "Australienne"),
    ("canada", "Canadienne"),
    ("belgium", "Belge"),
    ("switzerland", "Suisse"),
    ("new zealand", "Américaine"),
    ("brazil", "Brésilienne"),
    ("mexico", "Mexicaine"),
    ("sweden", "Suédoise"),
    ("denmark", "Danoise"),
    ("norway", "Norvégienne"),
    ("netherlands", "Néerlandaise"),
    ("turkey", "Turque"),
    ("iran", "Iranienne"),
    ("israel", "Israélienne"),
    ("poland", "Polonaise"),
]

# Mapping genre EN/FR -> categorie FR
GENRE_MAP = [
    ("science-fiction", "Science-Fiction"), ("science fiction", "Science-Fiction"), ("sci-fi", "Science-Fiction"),
    ("horreur", "Horreur"), ("horror", "Horreur"),
    ("thriller", "Thriller"),
    ("comédie dramatique", "Comédie dramatique"), ("comedy-drama", "Comédie dramatique"),
    ("comedy drama", "Comédie dramatique"),
    ("romance", "Romance"), ("romantique", "Romance"),
    ("romantic comedy", "Romance"), ("rom-com", "Romance"),
    ("comédie", "Comédie"), ("comedy", "Comédie"),
    ("drame", "Drame"), ("drama", "Drame"),
    ("action", "Action"),
    ("guerre", "Guerre"), ("war", "Guerre"),
    ("western", "Western"),
    ("musical", "Musical"),
    ("animation", "Animation"),
    ("aventure", "Aventure"), ("adventure", "Aventure"),
    ("fantastique", "Fantasy"), ("fantasy", "Fantasy"),
    ("policier", "Policier"), ("crime", "Policier"), ("gangster", "Policier"),
    ("film noir", "Policier"), ("noir", "Policier"), ("mob", "Policier"),
    ("mystère", "Mystère"), ("mystery", "Mystère"),
    ("biographique", "Biopic"), ("biographical", "Biopic"), ("biopic", "Biopic"),
    ("historique", "Historique"), ("historical", "Historique"), ("period", "Historique"),
    ("espionnage", "Espionnage"),
    ("catastrophe", "Catastrophe"), ("disaster", "Catastrophe"),
    ("famille", "Famille"), ("family", "Famille"),
    ("documentaire", "Documentaire"), ("documentary", "Documentaire"),
    ("péplum", "Historique"), ("peplum", "Historique"), ("sword and sandal", "Historique"),
    ("érotique", "Érotique"), ("erotic", "Érotique"),
    ("sport", "Sport"),
]


def api(lang, params, tries=4, pause=8):
    """Appel API MediaWiki avec retry (rate-limit 429)."""
    for a in range(tries):
        try:
            r = S.get(f"https://{lang}.wikipedia.org/w/api.php",
                      params=params, timeout=25)
            if r.status_code == 429:
                time.sleep(pause * (a + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            time.sleep(3)
    return None


# ── Textes / infobox ──────────────────────────────────────────────────

def get_fr_title(en_title):
    d = api("en", {"action": "query", "titles": en_title, "prop": "langlinks",
                   "lllang": "fr", "format": "json", "formatversion": "2", "redirects": 1})
    if not d:
        return None
    for p in d.get("query", {}).get("pages", []):
        for ll in p.get("langlinks", []):
            return ll["title"]
    return None


def get_wikitext(lang, title):
    d = api(lang, {"action": "parse", "page": title, "prop": "wikitext",
                   "section": 0, "format": "json", "formatversion": "2", "redirects": 1})
    if not d:
        return ""
    return d.get("parse", {}).get("wikitext", "") or ""


def get_exintro(lang, title):
    d = api(lang, {"action": "query", "titles": title, "prop": "extracts",
                   "explaintext": 1, "exintro": 1, "format": "json",
                   "formatversion": "2", "redirects": 1})
    if not d:
        return None
    for p in d.get("query", {}).get("pages", []):
        if p.get("extract"):
            return re.sub(r"\s+", " ", p["extract"]).strip()
    return None


def _get_field(wt, field):
    """Valeur d'un champ d'infobox (sur plusieurs lignes). Tolere l'apostrophe typographique."""
    pat = field.replace("'", r"['’]")
    m = re.search(r"^\s*\|\s*" + pat + r"\s*=\s*(.*)$", wt, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    val_lines = [m.group(1)]
    for line in wt[m.end():].split("\n"):
        if line.lstrip().startswith("|"):
            break
        val_lines.append(line)
    return "\n".join(val_lines)


_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}", re.DOTALL)


def _render_template(body):
    """Rend un template {{...}} : garde les arguments utiles."""
    parts = body.split("|")
    name = parts[0].strip().lower()
    args = [a.strip() for a in parts[1:] if a.strip()]
    if not args:
        return ""
    if name in ("lang", "langue", "lang-en", "lang-fr", "en", "fr"):
        return args[-1]
    if name in ("ubl", "unbulleted list", "hlist", "plainlist"):
        return ", ".join(args)
    positional = [a for a in args if "=" not in a]
    if positional:
        return positional[-1]
    return ""


def _flatten_templates(v):
    for _ in range(8):
        if "{{" not in v:
            break
        v = _TEMPLATE_RE.sub(lambda m: _render_template(m.group(1)), v)
    return v


def _strip_wiki_markup(v):
    if not v:
        return ""
    v = str(v)
    v = re.sub(r"<!--.*?-->", "", v, flags=re.DOTALL)
    v = _flatten_templates(v)
    v = re.sub(r"\[\[File:[^\]|]*\|", "", v)
    v = re.sub(r"\[\[(?:Image|File):[^\]]*\]\]", "", v)
    v = re.sub(r"\]\]\s*\[\[", ", ", v)
    v = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", v)
    v = re.sub(r"\[\[([^\]|]*)\]\]", r"\1", v)
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", v, flags=re.DOTALL)
    v = re.sub(r"<ref[^/>]*/>", "", v)
    v = re.sub(r"<br\s*/?>", ", ", v, flags=re.IGNORECASE)
    v = re.sub(r"</?[a-zA-Z][^>]*>", " ", v)
    v = v.replace("&nbsp;", " ")
    v = re.sub(r"&[a-zA-Z]+;", " ", v)
    v = re.sub(r"\s*\*\s*", ", ", v)
    v = v.replace("{{!}}", ",").replace("|", ", ")
    v = v.replace("]]", "").replace("[[", "")
    v = re.sub(r"\s+", " ", v)
    return v.strip(" .'\"-,;|")


def clean_names(v):
    """Liste de noms propres a partir d'un champ de cast multi-lignes
    ({{Plainlist| / {{ubl|}} / simples lignes)."""
    if not v:
        return []
    v = _flatten_templates(v)
    v = v.replace("}}", "").replace("{{", "")
    out = []
    for line in v.split("\n"):
        line = line.strip()
        if not line or line.startswith("<!--"):
            continue
        cleaned = _strip_wiki_markup(line)
        for piece in re.split(r",|\n", cleaned):
            p = re.sub(r"\s+", " ", piece).strip("* ")
            p = p.strip(" .'\"-}|")
            if p and len(p) > 2 and p.lower() not in (x.lower() for x in out):
                out.append(p)
    return out


def _map_genre(genre_text):
    g = (genre_text or "").lower()
    for key, val in GENRE_MAP:
        if key in g:
            return val
    return None


def _map_country(country_text):
    c = (country_text or "").lower()
    for key, val in COUNTRY_MAP:
        if key in c:
            return val
    return None


# ── Images ────────────────────────────────────────────────────────────

def _imageinfo_url(lang, filetitle):
    if not filetitle.startswith("File:"):
        filetitle = "File:" + filetitle
    d = api(lang, {"action": "query", "titles": filetitle, "prop": "imageinfo",
                   "iiprop": "url", "iiurlwidth": 500, "format": "json",
                   "formatversion": "2"})
    if not d:
        return None
    for p in d.get("query", {}).get("pages", []):
        ii = p.get("imageinfo", [])
        if ii:
            u = ii[0].get("thumburl") or ii[0].get("url")
            return u.split("?")[0] if u else None
    return None


def infobox_image(en_wt):
    """Fichier image de l'infobox (l'affiche du film)."""
    m = re.search(r"^\s*\|\s*image\s*=\s*(.*)$", en_wt, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    val = m.group(1).strip()
    val = re.sub(r"\[\[File:([^\]]*)\]\]", r"\1", val)
    val = val.split("|")[0].strip()
    if not val or val.lower().endswith((".svg", ".tif", ".tiff")):
        return None
    return val


def download_image(url):
    if not url:
        return None
    for a in range(3):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 429:
                time.sleep(6)
                continue
            r.raise_for_status()
            data = r.content
            if not data:
                return None
            ct = r.headers.get("Content-Type", "").lower()
            if ct.startswith("image/"):
                mime = ct
            else:
                ext = (url.rsplit(".", 1)[-1].lower().split("?")[0] if "." in url else "")
                mime = MIME_EXT.get(ext, "image/jpeg")
            return data, mime
        except Exception:
            time.sleep(3)
    return None


def normalize_image(data, mime, max_w, quality):
    """Redimensionne en JPEG RGB, taille max = max_w de large."""
    from PIL import Image, ImageOps
    import io
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (15, 20, 23))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")
        if img.width > max_w:
            h = max(1, round(img.height * max_w / img.width))
            img = img.resize((max_w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return None


# ── Distribution ──────────────────────────────────────────────────────

def get_cast(en_wt):
    cast = {
        "Acteur": clean_names(_get_field(en_wt, "starring")),
        "Realisateur": clean_names(_get_field(en_wt, "director")),
        "Scenario": clean_names(_get_field(en_wt, "writer")) or clean_names(_get_field(en_wt, "screenplay")),
    }
    return cast


def get_actor_photo(name):
    """Photo d'un acteur via pageimages (appel direct + fallback recherche)."""
    n = (name or "").strip()
    if not n or len(n) < 3:
        return None
    try:
        d = api("en", {"action": "query", "titles": n, "prop": "pageimages",
                       "pithumbsize": 300, "format": "json", "formatversion": "2", "redirects": 1})
        if d:
            pages = d.get("query", {}).get("pages", [])
            for p in pages:
                th = p.get("thumbnail")
                if th and th.get("source") and not th["source"].lower().endswith(".svg"):
                    return th["source"].split("?")[0]
        d = api("en", {"action": "query", "generator": "search", "gsrsearch": n,
                       "gsrlimit": 3, "gsrnamespace": 0, "prop": "pageimages",
                       "pithumbsize": 300, "format": "json", "formatversion": "2"})
        if d:
            pages = d.get("query", {}).get("pages", {})
            if isinstance(pages, dict):
                pages = pages.values()
            for p in pages:
                th = p.get("thumbnail")
                if th and th.get("source") and not th["source"].lower().endswith(".svg"):
                    return th["source"].split("?")[0]
    except Exception:
        pass
    return None


# ── Main ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", type=str, default=None)
    ap.add_argument("--photos", action="store_true", help="uniquement photos manquantes")
    ap.add_argument("--no-posters", action="store_true")
    ap.add_argument("--no-cast", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    only_ids = None
    if args.only:
        only_ids = {int(x) for x in args.only.split(",") if x.strip()}

    app = create_app()
    with app.app_context():
        films = Film.query.order_by(Film.id).all()
        if only_ids:
            films = [f for f in films if f.id in only_ids]
        if args.limit:
            films = films[:args.limit]

        photo_cache = {}
        for a in Actor.query.all():
            if a.image and a.nom:
                photo_cache.setdefault(a.nom.strip().lower(), a.image)

        print(f"{len(films)} film(s) a traiter.", flush=True)

        for i, film in enumerate(films, 1):
            en_title = EN_TITLES.get(film.id)
            if not en_title:
                print(f"[{i}/{len(films)}] #{film.id} {film.nom}: pas de titre EN connu, ignore", flush=True)
                continue
            print(f"\n[{i}/{len(films)}] #{film.id} {film.nom} -> {en_title}", flush=True)

            try:
                if args.photos:
                    # Mode photos uniquement : remplir les photos manquantes des acteurs existants
                    filled = 0
                    for actor in list(film.acteurs):
                        if actor.image:
                            key = (actor.nom or "").strip().lower()
                            photo_cache.setdefault(key, actor.image)
                            continue
                        key = (actor.nom or "").strip().lower()
                        if key in photo_cache:
                            actor.image = photo_cache[key]
                            filled += 1
                            continue
                        src = get_actor_photo(actor.nom)
                        if src:
                            raw = download_image(src)
                            if raw:
                                norm = normalize_image(raw[0], raw[1], 300, 80)
                                if norm:
                                    actor.image = upload_image_bytes(norm[0], norm[1]) or ""
                                    photo_cache[key] = actor.image
                                    filled += 1
                                    print(f"    photo {actor.nom}: OK", flush=True)
                        time.sleep(0.2)
                    if filled:
                        db.session.commit()
                        print(f"  photos ajoutees: {filled}", flush=True)
                    else:
                        print("  aucune photo manquante", flush=True)
                    time.sleep(0.2)
                    continue

                en_wt = get_wikitext("en", en_title)
                if not en_wt:
                    print("  ! infobox EN vide", flush=True)
                    continue

                fr_title = FR_TITLES.get(film.id) or get_fr_title(en_title)
                fr_wt = get_wikitext("fr", fr_title) if fr_title else ""
                print(f"  FR: {fr_title}", flush=True)

                # 1) Resume
                if not args.no_resume:
                    intro = get_exintro("fr", fr_title) if fr_title else None
                    if not intro:
                        intro = get_exintro("en", en_title)
                    if intro:
                        intro = intro.strip()
                        # coupe au 2e point pour garder un resume court et propre
                        film.resume = intro[:2000]
                        print(f"  resume: {intro[:70]}...", flush=True)
                    else:
                        print("  ! resume introuvable", flush=True)

                # 2) Metadonnees (infobox FR puis EN en secours)
                def fr_field(name):
                    return _strip_wiki_markup(_get_field(fr_wt, name)) if fr_wt else ""

                fr_to = fr_field("titre original")
                if not fr_to:
                    fr_to = _strip_wiki_markup(_get_field(en_wt, "name"))
                if not fr_to:
                    fr_to = en_title if en_title != film.nom else ""
                if fr_to:
                    film.titre_original = fr_to[:300]
                film.langue_originale = (fr_field("langue originale") or "en")[:100]

                genre = fr_field("genre") or _strip_wiki_markup(_get_field(en_wt, "genre")) or ""
                mapped = _map_genre(genre)
                if mapped:
                    film.categorie = mapped
                print(f"  categorie: {film.categorie} (genre brut: {genre[:40]})", flush=True)

                pays = fr_field("pays d'origine") or _strip_wiki_markup(_get_field(en_wt, "country")) or ""
                mapped = _map_country(pays)
                if mapped:
                    film.origine = mapped
                print(f"  origine: {film.origine} (pays brut: {pays[:40]})", flush=True)

                realisateurs = fr_field("réalisation") or fr_field("realisation") or clean_names(_get_field(en_wt, "director"))
                if isinstance(realisateurs, list):
                    realisateurs = ", ".join(realisateurs)
                if realisateurs:
                    film.realisateurs = realisateurs[:300]
                scenaristes = fr_field("scénario") or fr_field("scenario") or clean_names(_get_field(en_wt, "writer")) or clean_names(_get_field(en_wt, "screenplay"))
                if isinstance(scenaristes, list):
                    scenaristes = ", ".join(scenaristes)
                if scenaristes:
                    film.scenaristes = scenaristes[:300]
                production = PROD_OVERRIDES.get(film.id) or fr_field("société de production")
                if not production:
                    prod_en = (_strip_wiki_markup(_get_field(en_wt, "studio"))
                               or _strip_wiki_markup(_get_field(en_wt, "company"))
                               or _strip_wiki_markup(_get_field(en_wt, "production companies")))
                    production = prod_en
                if production:
                    film.productions = production[:300]
                print(f"  realisateurs: {film.realisateurs[:60]}", flush=True)
                print(f"  productions: {film.productions[:60]}", flush=True)

                # 3) Affiche (vraie affiche de l'infobox)
                if not args.no_posters:
                    imgfile = infobox_image(en_wt)
                    if imgfile:
                        url = _imageinfo_url("en", imgfile)
                        if url:
                            raw = download_image(url)
                            if raw:
                                norm = normalize_image(raw[0], raw[1], 500, 84)
                                if norm:
                                    film.image = upload_image_bytes(norm[0], norm[1]) or ""
                                    print(f"  affiche OK ({len(norm[0])} octets)", flush=True)
                                else:
                                    print("  ! affiche non normalisable", flush=True)
                            else:
                                print("  ! telechargement affiche echoue", flush=True)
                        else:
                            print("  ! pas d'URL pour l'affiche", flush=True)
                    else:
                        print("  ! pas d'image dans l'infobox", flush=True)

                # 4) Distribution correcte
                if not args.no_cast:
                    cast = get_cast(en_wt)
                    Actor.query.filter_by(film_id=film.id).delete()
                    db.session.flush()
                    for role in ("Acteur", "Realisateur", "Scenario"):
                        for name in cast[role]:
                            if not name:
                                continue
                            a = Actor(film_id=film.id, nom=name[:120], role=role)
                            db.session.add(a)
                    db.session.flush()
                    print(f"  cast: {len(cast['Acteur'])} acteurs, "
                          f"{len(cast['Realisateur'])} real., {len(cast['Scenario'])} scen.", flush=True)

                    # 5) Photos acteurs manquantes
                    for actor in list(film.acteurs):
                        key = (actor.nom or "").strip().lower()
                        if key in photo_cache:
                            actor.image = photo_cache[key]
                            continue
                        src = get_actor_photo(actor.nom)
                        if src:
                            raw = download_image(src)
                            if raw:
                                norm = normalize_image(raw[0], raw[1], 300, 80)
                                if norm:
                                    actor.image = upload_image_bytes(norm[0], norm[1]) or ""
                                    photo_cache[key] = actor.image
                                    print(f"    photo {actor.nom}: OK", flush=True)
                        time.sleep(0.2)

                db.session.commit()
                print("  [commit]", flush=True)
                time.sleep(0.4)
            except Exception as e:
                db.session.rollback()
                print(f"  ! erreur film #{film.id}: {e}", flush=True)

        print(f"\nTermine. {Film.query.count()} films en base.", flush=True)


if __name__ == "__main__":
    main()
