"""Extraction des credits (realisateur/scenario) par episode depuis Wikipedia.

Source gratuite (API MediaWiki, aucune cle). On lit les modeles
{{Episode list}} des articles de serie / listes d'episodes, en suivant les
transclusions ({{:List of X episodes}} -> {{:X season N}}) et en gerant les
modeles d'enrobage ({{nowrap}}, {{StoryTeleplay}}, ...).

Utilise par app/routes/api.py (endpoint /api/wd/series/<imdb>/episodes).
"""

import re
import time

import requests

UA = {"User-Agent": "TRIXIFILMS/1.0 (https://trixifilms.vercel.app)"}

_WRAPPERS = (
    "nowrap|nobr|small|smaller|font|em|strong|center|left|right|"
    "plainlist|plain list|ubl|unbulleted list|hlist|flatlist|cslist|"
    "nobold|big|mono|nowraplinks"
)


def _strip_refs(v):
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", v, flags=re.S | re.I)
    v = re.sub(r"<ref[^>]*/>", "", v, flags=re.I)
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)
    return v


def _expand_wrappers(v):
    prev = None
    while prev != v:
        prev = v
        v = re.sub(
            r"\{\{\s*StoryTeleplay\s*\|\s*s\s*=\s*([^}]*?)(?:\|\s*t\s*=\s*([^}]*?))?\s*\}\}",
            lambda m: " and ".join(x for x in [m.group(1), m.group(2)] if x),
            v, flags=re.I)
        v = re.sub(
            r"\{\{\s*(?:%s)\s*\|([^{}]*)\}\}" % _WRAPPERS,
            lambda m: m.group(1).replace("|", " & "), v, flags=re.I)
        v = re.sub(r"\{\{\s*[A-Za-z][\w .]*\s*\|\s*([^{}|=]+)\s*\}\}", r"\1", v)
    return v


def clean_names(raw):
    if not raw:
        return []
    v = _strip_refs(raw)
    v = _expand_wrappers(v)
    v = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", v)
    v = re.sub(r"\[\[([^\]|]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = v.replace("'''", "").replace("''", "")
    v = re.sub(r"<[^>]+>", "", v)
    v = v.replace("\u2022", " ").replace("\u2013", "-")
    v = re.sub(r"\s+", " ", v).strip(" ,;")
    parts = re.split(r"\s*&\s*|\s+and\s+|\s*,\s*(?=[A-Z])|\s*;\s*", v)
    out = []
    for p in parts:
        p = p.strip(" ,;")
        if len(p) > 1 and not re.fullmatch(r"[-\s]+", p) and p not in out:
            out.append(p)
    return out


def _extract_braced(wt, start):
    depth = 0
    i = start
    n = len(wt)
    while i < n:
        if wt.startswith("{{", i):
            depth += 1
            i += 2
        elif wt.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return wt[start:i]
        else:
            i += 1
    return wt[start:]


def _parse_template(block):
    assert block.startswith("{{")
    inner = block[2:-2]
    j = 0
    while j < len(inner) and inner[j] not in "|\n":
        j += 1
    params = {}
    depth = 0
    buf = []
    i = j
    n = len(inner)

    def flush(seg):
        seg = seg.strip()
        if not seg or "=" not in seg:
            return
        key, _, val = seg.partition("=")
        key = key.strip().lower()
        if key and key not in params:
            params[key] = val.strip()

    while i < n:
        if inner.startswith("{{", i) or inner.startswith("[[", i):
            depth += 1
            buf.append(inner[i:i + 2])
            i += 2
            continue
        if inner.startswith("}}", i) or inner.startswith("]]", i):
            depth = max(0, depth - 1)
            buf.append(inner[i:i + 2])
            i += 2
            continue
        if inner[i] == "|" and depth == 0:
            flush("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(inner[i])
        i += 1
    flush("".join(buf))
    return params


def _parse_episode_lists(wt, episodes, forced_season=None):
    heading_re = re.compile(r"^={2,}\s*(.{0,60}?)\s*={2,}\s*$", re.M)
    headings = []
    for m in heading_re.finditer(wt):
        num = re.search(r"(\d+)", m.group(1))
        if num and re.search(r"season|series|saison|part", m.group(1), re.I):
            headings.append((m.start(), int(num.group(1))))
    for m in re.finditer(r"\{\{\s*Episode list(?:/sublist)?\b", wt):
        block = _extract_braced(wt, m.start())
        params = _parse_template(block)
        season = forced_season if forced_season is not None else 1
        if forced_season is None:
            for hpos, hnum in headings:
                if hpos < m.start():
                    season = hnum
                else:
                    break
        num = re.sub(r"[^0-9]", "", params.get("episodenumber2", "")
                     or params.get("episodenumber", ""))
        if not num:
            continue
        key = "%s:%s" % (season, int(num))
        dirs = clean_names(params.get("directedby", ""))
        writers = clean_names(params.get("writtenby", ""))
        if not dirs and not writers:
            continue
        entry = episodes.setdefault(key, {"director": [], "writer": []})
        for d in dirs:
            if d not in entry["director"]:
                entry["director"].append(d)
        for w in writers:
            if w not in entry["writer"]:
                entry["writer"].append(w)


def _fetch_wikitext(title, ua=None, retries=3, timeout=20):
    headers = ua or UA
    for attempt in range(retries + 1):
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", params={
                "action": "parse", "page": title, "prop": "wikitext",
                "format": "json", "redirects": 1,
            }, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                return None
            return data["parse"]["wikitext"]["*"]
        except Exception:
            if attempt >= retries:
                return None
    return None


def _resolve(title, ua=None):
    episodes = {}
    wt = _fetch_wikitext(title, ua)
    if wt is None:
        return episodes
    trans = re.findall(r"\{\{\s*:\s*([^}|#\n]+)", wt)
    if trans:
        for t in dict.fromkeys(x.strip() for x in trans):
            sub = _fetch_wikitext(t, ua)
            if not sub:
                continue
            m = re.search(r"season\s*(\d+)", t, re.I)
            forced = int(m.group(1)) if m else None
            sub_trans = re.findall(r"\{\{\s*:\s*([^}|#\n]+)", sub)
            if sub_trans:
                for st in dict.fromkeys(x.strip() for x in sub_trans):
                    m2 = re.search(r"season\s*(\d+)", st, re.I)
                    forced2 = int(m2.group(1)) if m2 else forced
                    sub2 = _fetch_wikitext(st, ua)
                    if sub2:
                        _parse_episode_lists(sub2, episodes, forced_season=forced2)
            else:
                _parse_episode_lists(sub, episodes, forced_season=forced)
    else:
        _parse_episode_lists(wt, episodes)
    return episodes


def _candidate_titles(base):
    cands = [base]
    m = re.match(r"^(.*?)\s*\([^)]*\)\s*$", base)
    plain = m.group(1) if m else base
    if plain != base:
        cands.append(plain)
    for b in list(cands):
        cands.append("List of %s episodes" % b)
    out = []
    for c in cands:
        if c and c not in out:
            out.append(c)
    return out


def fetch_series_episodes(title, ua=None):
    """Retourne { "S:E": {"director": [...], "writer": [...]} } ou {}."""
    if not title:
        return {}
    for cand in _candidate_titles(title):
        eps = _resolve(cand, ua)
        if eps:
            return eps
    return {}


def enwiki_title_from_qid(qid, ua=None):
    """Titre de l'article en.wikipedia via le sitelink Wikidata du QID."""
    if not qid or not re.fullmatch(r"Q\d+", qid):
        return ""
    try:
        r = requests.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": qid, "props": "sitelinks",
            "sitefilter": "enwiki", "format": "json",
        }, headers=ua or UA, timeout=10)
        r.raise_for_status()
        data = r.json()
        ent = (data.get("entities") or {}).get(qid) or {}
        return ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title", "")
    except Exception:
        return ""
