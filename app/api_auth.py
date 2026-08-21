import os
import time
import hashlib
import logging
from functools import wraps

from flask import request, jsonify, current_app
import jwt as pyjwt

from app.models import db, User

logger = logging.getLogger(__name__)

ACCESS_TOKEN_EXP = 15 * 60
REFRESH_TOKEN_EXP = 7 * 24 * 3600

ALGORITHM = "HS256"


def _get_jwt_secret():
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    secret = os.environ.get("FLASK_SECRET")
    if secret:
        return secret
    # Fallback deterministe : derive un secret STABLE d'une variable d'env stable.
    # Indispensable en serverless (Vercel) : un secret aleatoire par instance
    # invaliderait tous les tokens a chaque cold start (deconnexions permanentes).
    base = os.environ.get("DATABASE_URL") or ""
    if base:
        return hashlib.sha256(("trixifilms-jwt-v1:" + base).encode("utf-8")).hexdigest()
    import secrets
    logger.warning("JWT_SECRET absent: generation d'une cle aleatoire (les tokens seront invalides au redemarrage).")
    return secrets.token_hex(32)


def _get_jwt_issuer():
    return os.environ.get("JWT_ISSUER", "trixifilms-api")


def create_access_token(user_id, prenom):
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "prenom": prenom,
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXP,
        "iss": _get_jwt_issuer(),
        "type": "access",
    }
    return pyjwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)


def create_refresh_token(user_id, prenom):
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "prenom": prenom,
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXP,
        "iss": _get_jwt_issuer(),
        "type": "refresh",
    }
    return pyjwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)


def decode_token(token):
    try:
        payload = pyjwt.decode(
            token, _get_jwt_secret(), algorithms=[ALGORITHM],
            issuer=_get_jwt_issuer(), options={"require": ["sub", "exp", "iat", "type"]}
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError as e:
        logger.warning(f"JWT invalid: {e}")
        return None


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token manquant ou invalide."}), 401
        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "Token expiré ou invalide."}), 401
        if payload.get("type") != "access":
            return jsonify({"error": "Type de token invalide."}), 401
        user = db.session.get(User, int(payload["sub"]))
        if not user:
            return jsonify({"error": "Utilisateur introuvable."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def refresh_token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Refresh token manquant."}), 401
        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "Refresh token expiré ou invalide."}), 401
        if payload.get("type") != "refresh":
            return jsonify({"error": "Type de token invalide."}), 401
        user = db.session.get(User, int(payload["sub"]))
        if not user:
            return jsonify({"error": "Utilisateur introuvable."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated
