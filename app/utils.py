import os
import re
import unicodedata
import tempfile

from flask import url_for, current_app
from markupsafe import Markup
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = False

MIME_MAP = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}


def normalize_text(s):
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def highlight_text(text, terms):
    try:
        s = str(text)
        terms = [t for t in (terms or []) if t]
        if not terms:
            return Markup(s)
        # Construit une version normalisée (sans accents) du texte avec la
        # correspondance des positions vers l'original pour matcher correctement
        # les recherches tapées sans accents (ex: "ecume" -> "L'Écume des jours").
        norm_chars = []
        orig_idx = []
        for i, ch in enumerate(s):
            n = normalize_text(ch)
            if not n:
                continue
            for c in n:
                norm_chars.append(c)
                orig_idx.append(i)
        norm_s = "".join(norm_chars)
        spans = []
        for t in terms:
            tn = normalize_text(t)
            if not tn:
                continue
            pat = re.escape(tn)
            for m in re.finditer(pat, norm_s):
                spans.append((orig_idx[m.start()], orig_idx[m.end() - 1] + 1))
        if not spans:
            return Markup(s)
        spans.sort()
        merged = []
        cur_s, cur_e = spans[0]
        for a, b in spans[1:]:
            if a <= cur_e:
                cur_e = max(cur_e, b)
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = a, b
        merged.append((cur_s, cur_e))
        from markupsafe import escape
        out = []
        last = 0
        for a, b in merged:
            out.append(escape(s[last:a]))
            out.append(Markup("<mark>"))
            out.append(escape(s[a:b]))
            out.append(Markup("</mark>"))
            last = b
        out.append(escape(s[last:]))
        return Markup("".join(out))
    except Exception:
        return Markup(text)


def _allowed_extension(filename):
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"png", "jpg", "jpeg", "gif"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def process_image(file_storage):
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    filename = file_storage.filename
    if not _allowed_extension(filename):
        return None
    _max_bytes = current_app.config.get("MAX_IMAGE_BYTES", 8 * 1024 * 1024)
    _max_pixels = current_app.config.get("MAX_PIXEL_COUNT", 6000 * 6000)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_name = tmp.name
        file_storage.save(tmp_name)
    try:
        if os.path.getsize(tmp_name) > _max_bytes:
            os.remove(tmp_name)
            return None
    except Exception:
        pass
    try:
        with Image.open(tmp_name) as img:
            img.verify()
        with Image.open(tmp_name) as img:
            w, h = img.size
            if w * h > _max_pixels:
                os.remove(tmp_name)
                return None
            fmt = (img.format or "").lower()
            if fmt == "jpeg":
                fmt = "jpg"
        mime = MIME_MAP.get(fmt, "image/jpeg")
        with open(tmp_name, "rb") as f:
            data = f.read()
        os.remove(tmp_name)
        return {"data": data, "mime": mime}
    except Exception:
        try:
            os.remove(tmp_name)
        except Exception:
            pass
        return None


def process_image_from_url(url):
    """Télécharge une image distante et l'upload sur Cloudinary.
    Renvoie {"url": ...} (URL Cloudinary) ou None en cas d'échec."""
    from app.cloud import upload_image_url
    if not url:
        return None
    uploaded = upload_image_url(url)
    if not uploaded:
        return None
    return {"url": uploaded}


import re


def parse_youtube_id(text):
    """Extrait l'ID vidéo YouTube depuis un lien (watch/short/embed/youtu.be) ou renvoie un ID brut."""
    text = (text or "").strip()
    if not text:
        return ""
    patterns = [
        r"(?:v=|vi=)([0-9A-Za-z_-]{11})",
        r"youtu\.be/([0-9A-Za-z_-]{11})",
        r"youtube(?:-nocookie)?\.com/(?:embed|shorts|live)/([0-9A-Za-z_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", text):
        return text
    return ""


def image_url(film_or_actor, type_name):
    img = (film_or_actor.image or "").strip()
    if not img:
        try:
            return url_for("static", filename="no_image.svg")
        except Exception:
            return "/static/no_image.svg"
    if img.startswith(("http://", "https://")):
        return img
    if not img.startswith("/"):
        img = "/" + img
    return img


def film_to_dict(film):
    d = film.to_dict()
    d["image"] = image_url(film, "film")
    return d


def get_avg_rating(film_id):
    from app.models import Rating
    ratings = Rating.query.filter_by(film_id=film_id).all()
    if not ratings:
        return None, 0
    notes = [r.note for r in ratings]
    avg_raw = sum(notes) / len(notes)
    avg = round(avg_raw * 2) / 2.0
    return avg, len(notes)
