"""
TRIXIFILMS — Stockage des images sur Cloudinary.

Remplace le stockage BLOB en base de données. Chaque upload renvoie
l'URL Cloudinary publique qui est stockée dans la colonne `image`.
"""
import os
import re
import tempfile

import cloudinary
import cloudinary.uploader

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
_DEFAULT_FOLDER = "trixifilms"


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def is_configured():
    """True si les variables Cloudinary sont toutes définies."""
    return bool(
        _env("CLOUDINARY_CLOUD_NAME")
        and _env("CLOUDINARY_API_KEY")
        and _env("CLOUDINARY_API_SECRET")
    )


def _configure():
    cloudinary.config(
        cloud_name=_env("CLOUDINARY_CLOUD_NAME"),
        api_key=_env("CLOUDINARY_API_KEY"),
        api_secret=_env("CLOUDINARY_API_SECRET"),
        secure=True,
    )


def _folder():
    return _env("CLOUDINARY_FOLDER", _DEFAULT_FOLDER) or _DEFAULT_FOLDER


def _result_url(result):
    return result.get("secure_url") or result.get("url") or ""


def upload_image_bytes(data, mime, folder=None):
    """Upload des octets d'image vers Cloudinary. Renvoie l'URL ou None."""
    if not is_configured() or not data:
        return None
    ext = _MIME_EXT.get((mime or "").lower(), "jpg")
    _configure()
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(data)
            tmp_name = tmp.name
        result = cloudinary.uploader.upload(
            tmp_name,
            resource_type="image",
            folder=folder or _folder(),
            overwrite=False,
            unique_filename=True,
        )
        return _result_url(result) or None
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp_name)
        except Exception:
            pass


def upload_image_url(remote_url, folder=None):
    """Upload d'une image distante (Cloudinary la télécharge). Renvoie l'URL ou None."""
    if not is_configured() or not remote_url:
        return None
    _configure()
    try:
        result = cloudinary.uploader.upload(
            remote_url,
            resource_type="image",
            folder=folder or _folder(),
            overwrite=False,
            unique_filename=True,
        )
        return _result_url(result) or None
    except Exception:
        return None


def upload_image_file(file_storage, folder=None):
    """Upload depuis un objet FileStorage Flask. Renvoie l'URL ou None."""
    if not is_configured() or not file_storage:
        return None
    _configure()
    try:
        result = cloudinary.uploader.upload(
            file_storage.stream,
            resource_type="image",
            folder=folder or _folder(),
            overwrite=False,
            unique_filename=True,
        )
        return _result_url(result) or None
    except Exception:
        return None


def extract_public_id(url):
    """Extrait le public_id Cloudinary depuis une URL (ou None si ce n'est pas une URL Cloudinary)."""
    if not url:
        return None
    marker = "/image/upload/"
    idx = url.find(marker)
    if idx == -1:
        return None
    rest = url[idx + len(marker):].split("?", 1)[0]
    parts = [p for p in rest.split("/") if p]
    if parts and parts[0].startswith("v") and parts[0][1:].isdigit():
        parts = parts[1:]
    if parts:
        parts[-1] = re.sub(r"\.[A-Za-z0-9]+$", "", parts[-1])
    return "/".join(parts) or None


def delete_image(url):
    """Supprime une image Cloudinary depuis son URL. Renvoie True si supprimée."""
    public_id = extract_public_id(url)
    if not public_id:
        return False
    _configure()
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception:
        return False