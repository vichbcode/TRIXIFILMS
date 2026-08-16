"""
Re-import Wikipedia pour TRIXIFILMS (web).
Met a jour les films EXISTANTS (meme id) avec :
  - un resume correct (intro officielle Wikipedia via l'API extracts/exintro)
  - une affiche reelle (fichier poster sur Wikipedia EN, ou affiche sur FR)
  - la VRAIE distribution (remplace les acteurs errones issus du 1er import)
  - des photos d'acteurs quand disponibles.

Les noms de films en base etant quasi exclusivement anglophones, on part de la
page Wikipedia EN pour trouver le film, puis on recupere le titre FR via langlinks.

Usage : python repopulate_wikipedia.py
"""
import os
import sys
import time
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from app import create_app
from app.models import db, Film, Actor
from app.cloud import upload_image_bytes

WIKI_UA = "TRIXIFILMS-Import/1.0 (Wikipedia film import script)"
S = requests.Session()
S.headers.update({"User-Agent": WIKI_UA})

MIME_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}


def api(lang, params, tries=5, pause=12):
    """Appel API MediaWiki avec retry et backoff (rate-limit 429)."""
    for a in range(tries):
        try:
            r = S.get(f"https://{lang}.wikipedia.org/w/api.php",
                      params=params, timeout=25)
            if r.status_code == 429:
                print(f"    [rate-limit] pause {pause * (a + 1)}s...", flush=True)
                time.sleep(pause * (a + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"    [retry {a+1}] {e}", flush=True)
            time.sleep(4)
    return None


# ── Page film (recherche) ───────────────────────────────────────────

def _get_infobox(lang, title):
    d = api(lang, {"action": "parse", "page": title, "prop": "wikitext",
                   "section": 0, "format": "json", "formatversion": "2", "redirects": 1})
    if not d:
        return ""
    return d.get("parse", {}).get("wikitext", "") or ""


def _is_film_page(lang, title):
    """La page est un article de film (infobox film). Un seul appel API."""
    low = _get_infobox(lang, title).lower()
    return "infobox" in low and "film" in low


def search(lang, query):
    """Trouve la page Wikipedia du film. Evite homonymies et mauvaises pages."""
    q = re.sub(r"\s+", " ", query.replace(":", " ")).strip()
    ql = q.lower()

    for cand in [q, f"{q} (film)", f"{q} (2000 film)"]:
        if _is_film_page(lang, cand):
            return cand

    best = None
    for suffix in ("", " film"):
        d = api(lang, {"action": "query", "list": "search",
                       "srsearch": q + suffix, "srlimit": 15,
                       "format": "json", "formatversion": "2"})
        if not d:
            continue
        results = d.get("query", {}).get("search", [])
        if not results:
            continue
        for res in results:
            t = res.get("title", "")
            tl = t.strip().lower().replace(":", " ")
            if tl == ql or ("(film)" in tl and (tl.startswith(ql) or ql in tl)):
                if _is_film_page(lang, t):
                    return t
        if best is None:
            best = results[0]["title"]
    if best and _is_film_page(lang, best):
        return best
    return None


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


def langlink(lang, title, target):
    d = api(lang, {"action": "query", "titles": title, "prop": "langlinks",
                   "lllang": target, "format": "json", "formatversion": "2", "redirects": 1})
    if not d:
        return None
    for p in d.get("query", {}).get("pages", []):
        for ll in p.get("langlinks", []):
            return ll["title"]
    return None


# ── Distribution (infobox EN) ───────────────────────────────────────

def _get_field(wt, field):
    m = re.search(r"^\s*\|\s*" + field + r"\s*=\s*(.*)$", wt, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    val_lines = [m.group(1)]
    for line in wt[m.end():].split("\n"):
        if line.lstrip().startswith("|"):
            break
        val_lines.append(line)
    return "\n".join(val_lines)


def _clean_names(v):
    if not v:
        return []
    out = []
    v = re.sub(r"<!--.*?-->", "", v)
    v = re.sub(r"\{\{\s*\S*\|?", "", v)
    v = v.replace("}}", "")
    v = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", v)
    v = re.sub(r"\[\[([^\]|]*)\]\]", r"\1", v)
    for line in v.split("\n"):
        p = line.strip("* ").strip()
        if p:
            p = re.sub(r"\s+", " ", p).strip(" .'\"-")
        if p and len(p) > 2 and p.lower() not in (x.lower() for x in out):
            out.append(p)
    return out


def get_cast(en_title):
    """Retourne dict {'Acteur': [...], 'Realisateur': [...], 'Scenario': [...]}."""
    wt = _get_infobox("en", en_title)
    cast = {
        "Acteur": _clean_names(_get_field(wt, "starring")),
        "Realisateur": _clean_names(_get_field(wt, "director")),
        "Scenario": _clean_names(_get_field(wt, "writer")) or _clean_names(_get_field(wt, "screenplay")),
    }
    # Un realisateur qui apparait aussi dans starring reste realisateur
    return cast


# ── Affiche ─────────────────────────────────────────────────────────

def _images(lang, title):
    imgs = []
    cont = {}
    for _ in range(6):
        params = {"action": "query", "titles": title, "prop": "images",
                  "imlimit": 500, "format": "json", "formatversion": "2"}
        params.update(cont)
        d = api(lang, params)
        if not d:
            break
        for p in d.get("query", {}).get("pages", []):
            imgs += [im["title"] for im in p.get("images", [])]
        cont = d.get("continue", {})
        if not cont:
            break
    return imgs


def _imageinfo(lang, filetitle):
    d = api(lang, {"action": "query", "titles": filetitle, "prop": "imageinfo",
                   "iiprop": "url", "iiurlwidth": 500, "format": "json",
                   "formatversion": "2"})
    if not d:
        return None
    for p in d.get("query", {}).get("pages", []):
        ii = p.get("imageinfo", [])
        if ii:
            return ii[0].get("thumburl") or ii[0].get("url")
    return None


def find_poster(en_title, fr_title):
    if en_title:
        for name in _images("en", en_title):
            low = name.lower()
            if "poster" in low and low.endswith((".jpg", ".jpeg", ".png")):
                url = _imageinfo("en", name)
                if url:
                    return url
    if fr_title:
        for name in _images("fr", fr_title):
            low = name.lower()
            if "affiche" in low and low.endswith((".jpg", ".jpeg", ".png")):
                url = _imageinfo("fr", name)
                if url:
                    return url
    return None


def download_image(url):
    if not url:
        return None
    try:
        r = S.get(url, timeout=30)
        if r.status_code == 429:
            time.sleep(8)
            r = S.get(url, timeout=30)
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
    except Exception as e:
        print(f"      [img-fail] {e}", flush=True)
        return None


# ── Photo acteur ────────────────────────────────────────────────────

def find_actor_photo(actor_name):
    q = actor_name.strip().replace(":", " ")
    if not q or len(q) < 3:
        return None
    d = api("en", {"action": "query", "list": "search", "srsearch": q,
                   "srlimit": 3, "format": "json", "formatversion": "2"})
    if not d:
        return None
    results = d.get("query", {}).get("search", [])
    if not results:
        return None
    title = results[0]["title"]
    d2 = api("en", {"action": "query", "titles": title, "prop": "pageimages",
                    "pithumbsize": 300, "format": "json", "formatversion": "2", "redirects": 1})
    if not d2:
        return None
    for p in d2.get("query", {}).get("pages", []):
        th = p.get("thumbnail")
        if th:
            src = th.get("source")
            if src and not src.lower().endswith(".svg"):
                return src
    return None


# ── Main ────────────────────────────────────────────────────────────

def main():
    app = create_app()
    with app.app_context():
        films = Film.query.order_by(Film.id).all()
        print(f"Films a traiter : {len(films)}", flush=True)

        skip = os.environ.get("SKIP_DONE", "1") == "1"
        for i, film in enumerate(films, 1):
            done = bool(film.resume) and bool(film.image) and any(
                a.role == "Acteur" for a in film.acteurs)
            if skip and done:
                print(f"[{i}/{len(films)}] {film.nom} : deja traite, ignore", flush=True)
                continue
            print(f"\n[{i}/{len(films)}] {film.nom} (id={film.id})", flush=True)

            en_title = search("en", film.nom)
            if not en_title:
                print("  ! page EN introuvable", flush=True)
                continue
            print(f"  EN: {en_title}", flush=True)
            fr_title = langlink("en", en_title, "fr")
            if fr_title:
                print(f"  FR: {fr_title}", flush=True)

            # 1) Resume
            intro = get_exintro("fr", fr_title) if fr_title else None
            if not intro:
                intro = get_exintro("en", en_title)
            if intro:
                film.resume = intro[:2000]
                print(f"  resume: {intro[:70]}...", flush=True)
            else:
                print("  ! resume introuvable", flush=True)

            # 2) Affiche
            poster = find_poster(en_title, fr_title)
            if poster:
                img = download_image(poster)
                if img:
                    film.image = upload_image_bytes(img[0], img[1]) or ""
                    print(f"  affiche OK ({len(img[0])} octets)", flush=True)
                else:
                    print("  ! telechargement affiche echoue", flush=True)
            else:
                print("  ! pas d'affiche", flush=True)

            # 3) Distribution correcte (remplace les acteurs)
            cast = get_cast(en_title)
            total_roles = sum(len(v) for v in cast.values())
            print(f"  cast: {total_roles} personnes "
                  f"(acteurs={len(cast['Acteur'])}, real={len(cast['Realisateur'])}, scen={len(cast['Scenario'])})",
                  flush=True)

            Actor.query.filter_by(film_id=film.id).delete()
            db.session.flush()
            for role, names in cast.items():
                for name in names:
                    db.session.add(Actor(film_id=film.id, nom=name[:120], role=role))
            db.session.flush()

            # 4) Photos acteurs (que le cast principal)
            nb_photo = 0
            for actor in list(film.acteurs):
                if actor.role != "Acteur":
                    continue
                src = find_actor_photo(actor.nom)
                if src:
                    img = download_image(src)
                    if img:
                        actor.image = upload_image_bytes(img[0], img[1]) or ""
                        nb_photo += 1
                        print(f"    {actor.nom}: photo OK", flush=True)
                    time.sleep(0.4)
            if cast["Acteur"]:
                print(f"  photos acteurs: {nb_photo}/{len(cast['Acteur'])}", flush=True)

            db.session.commit()
            print("  [commit]", flush=True)
            time.sleep(1)

        print(f"\nTermine. {Film.query.count()} films en base.", flush=True)


if __name__ == "__main__":
    main()
