import time
import logging
from functools import wraps

from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)

_stores = {}


def _get_store(name):
    if name not in _stores:
        _stores[name] = {}
    return _stores[name]


def _prune_store(store, now, window_seconds):
    """Nettoie les entrées expirées pour éviter que la mémoire ne grossisse indéfiniment."""
    if len(store) > 500:
        stale = [ip for ip, rec in store.items()
                 if rec.get("blocked_until", 0) <= now
                 and not any(t > now - window_seconds for t in rec.get("attempts", []))]
        for ip in stale:
            del store[ip]


def rate_limit(name, max_requests, window_seconds, block_duration=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            store = _get_store(name)
            ip = request.remote_addr or "unknown"
            now = time.time()
            _prune_store(store, now, window_seconds)
            rec = store.get(ip, {"attempts": [], "blocked_until": 0})
            if rec["blocked_until"] > now:
                remaining = int(rec["blocked_until"] - now)
                logger.warning(f"Rate limit blocked {ip} on {name}")
                return jsonify({
                    "error": f"Trop de requêtes. Réessaye dans {remaining}s.",
                    "retry_after": remaining,
                }), 429
            rec["attempts"] = [t for t in rec["attempts"] if now - t < window_seconds]
            rec["attempts"].append(now)
            if len(rec["attempts"]) > max_requests:
                if block_duration:
                    rec["blocked_until"] = now + block_duration
                logger.warning(f"Rate limit exceeded {ip} on {name}")
                store[ip] = rec
                return jsonify({
                    "error": "Trop de requêtes. Réessaye plus tard.",
                }), 429
            store[ip] = rec
            return f(*args, **kwargs)
        return decorated
    return decorator


def clear_rate_limit(name, ip):
    store = _get_store(name)
    store.pop(ip, None)
