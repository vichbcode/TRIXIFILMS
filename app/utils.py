import os
import re
import unicodedata
import io
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
        s_low = s.lower()
        spans = []
        for t in terms:
            if not t:
                continue
            pat = re.escape(t)
            for m in re.finditer(pat, s_low):
                spans.append((m.start(), m.end()))
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
        out = []
        last = 0
        for a, b in merged:
            out.append(s[last:a])
            out.append("<mark>" + s[a:b] + "</mark>")
            last = b
        out.append(s[last:])
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
    import requests
    try:
        r = requests.get(url, stream=True, timeout=15)
        r.raise_for_status()
    except Exception:
        return None
    content_type = r.headers.get("Content-Type", "")
    mime = content_type if content_type.startswith("image/") else "image/jpeg"
    data = b""
    try:
        for chunk in r.iter_content(1024 * 16):
            if chunk:
                data += chunk
        if not data:
            return None
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        return {"data": data, "mime": mime}
    except Exception:
        return None


def image_url(film_or_actor, type_name):
    if film_or_actor.image_data:
        return url_for("main.serve_image", type=type_name, id=film_or_actor.id)
    if film_or_actor.image:
        img = film_or_actor.image
        if not img.startswith("/"):
            img = "/" + img
        return img
    try:
        return url_for("static", filename="no_image.svg")
    except Exception:
        return "/static/no_image.svg"


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
