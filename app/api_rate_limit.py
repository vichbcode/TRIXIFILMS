import os
import time
import logging
from functools import wraps

from flask import request, jsonify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stockage partage optionnel (Upstash Redis via REST).
# Sur Vercel (serverless) chaque instance a sa propre memoire : sans store
# partage, le rate-limit est contournable en visant une autre instance.
# Si UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN sont definis, on les
# utilise ; sinon on retombe sur le store memoire (comportement historique).
# ---------------------------------------------------------------------------

_mem = {}


def _redis_conf():
    url = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""
    if url and token:
        return url, token
    return None


def _redis_cmd(url, token, *args):
    import requests as http_req
    r = http_req.post(url, json=[str(a) for a in args],
                      headers={"Authorization": f"Bearer {token}"}, timeout=3)
    r.raise_for_status()
    return r.json().get("result")


def _prune_store(store, now, window_seconds):
    """Nettoie les entrees expirees pour eviter que la memoire ne grossisse indefiniment."""
    if len(store) > 500:
        stale = [ip for ip, rec in store.items()
                 if rec.get("blocked_until", 0) <= now
                 and not any(t > now - window_seconds for t in rec.get("attempts", []))]
        for ip in stale:
            del store[ip]


def _hit_memory(name, ip, max_requests, window_seconds, block_duration):
    store = _mem.setdefault(name, {})
    now = time.time()
    _prune_store(store, now, window_seconds)
    rec = store.get(ip, {"attempts": [], "blocked_until": 0})
    if rec["blocked_until"] > now:
        return False, int(rec["blocked_until"] - now)
    rec["attempts"] = [t for t in rec["attempts"] if now - t < window_seconds]
    rec["attempts"].append(now)
    if len(rec["attempts"]) > max_requests:
        if block_duration:
            rec["blocked_until"] = now + block_duration
        store[ip] = rec
        return False, int(block_duration or window_seconds)
    store[ip] = rec
    return True, 0


def _hit_redis(url, token, name, ip, max_requests, window_seconds, block_duration):
    block_key = f"rl:block:{name}:{ip}"
    ttl = _redis_cmd(url, token, "TTL", block_key)
    if isinstance(ttl, int) and ttl > 0:
        return False, ttl
    cnt_key = f"rl:cnt:{name}:{ip}"
    cnt = _redis_cmd(url, token, "INCR", cnt_key)
    if cnt == 1:
        _redis_cmd(url, token, "EXPIRE", cnt_key, max(int(window_seconds), 1))
    if isinstance(cnt, int) and cnt > max_requests:
        if block_duration:
            _redis_cmd(url, token, "SET", block_key, "1", "EX", int(block_duration))
            return False, int(block_duration)
        rem = _redis_cmd(url, token, "TTL", cnt_key)
        return False, rem if isinstance(rem, int) and rem > 0 else int(window_seconds)
    return True, 0


def _hit(name, ip, max_requests, window_seconds, block_duration):
    """Renvoie (autorise, secondes_avant_reessai)."""
    conf = _redis_conf()
    if conf:
        try:
            return _hit_redis(conf[0], conf[1], name, ip,
                              max_requests, window_seconds, block_duration)
        except Exception as e:
            logger.warning(f"Store rate-limit indisponible, repli memoire: {e}")
    return _hit_memory(name, ip, max_requests, window_seconds, block_duration)


def check_rate_limit(name, max_requests, window_seconds, block_duration=None,
                     identifier=None):
    """Verifie la limite sans decorer une fonction (utile pour les pages web).

    Renvoie (autorise: bool, secondes_avant_reessai: int).
    """
    ip = identifier or request.remote_addr or "unknown"
    return _hit(name, ip, max_requests, window_seconds, block_duration)


def rate_limit(name, max_requests, window_seconds, block_duration=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            allowed, retry = check_rate_limit(
                name, max_requests, window_seconds, block_duration)
            if not allowed:
                logger.warning(f"Rate limit blocked {request.remote_addr} on {name}")
                return jsonify({
                    "error": f"Trop de requetes. Reessaye dans {retry}s.",
                    "retry_after": retry,
                }), 429
            return f(*args, **kwargs)
        return decorated
    return decorator


def clear_rate_limit(name, ip):
    _mem.get(name, {}).pop(ip, None)
    conf = _redis_conf()
    if conf:
        try:
            _redis_cmd(conf[0], conf[1], "DEL", f"rl:cnt:{name}:{ip}")
            _redis_cmd(conf[0], conf[1], "DEL", f"rl:block:{name}:{ip}")
        except Exception as e:
            logger.warning(f"Effacement rate-limit Redis impossible: {e}")
