"""Family Movie Night proxy.

The movie page is served by this service so the public link lives on a normal
host (works in any browser). The data still lives in Tiram's Google Sheet;
this module talks to the Apps Script JSON API server-side, which avoids the
browser multi-Google-account failure that breaks script.google.com pages
when opened directly.
"""
import json, os, re, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

EXEC_URL = os.environ.get(
    "MOVIENIGHT_EXEC_URL",
    "https://script.google.com/macros/s/AKfycbzr_w09tL3HeFdDMg2f0wWP9V25EGDkFQgmxvUFykgKwwgtvn-exEGLZj58E6DB7yJSoA/exec",
)
API_KEY = os.environ.get("MOVIENIGHT_API_KEY", "fmnight-7f3ka9")
TIMEOUT = 25


def _call(payload):
    """Call the Apps Script API with a GET (Apps Script POST redirects hang
    in common HTTP clients; GET actions are reliable) and return its reply."""
    params = dict(payload or {})
    for key, value in list(params.items()):
        if isinstance(value, bool):
            params[key] = "true" if value else "false"
    params["api"] = "1"
    params["k"] = API_KEY
    url = EXEC_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---- Poster / trailer metadata (iTunes Search API, no key needed) ----
UA = "FamilyMovieNight/1.0 (https://family-movie-night-nybr.onrender.com)"
_meta_cache = {}

# Hand-picked posters (verified 2026-11-25) for titles the strict automatic
# matcher deliberately skips: remakes / same-name films (Resident Evil, Top
# Gun, Brewster's Millions, Twister), titles entered without their "The"
# (The Matrix, The Terminator, The Ballad of Songbirds and Snakes), and the
# obscure Christmas at the Kringles. Each URL was checked live (HTTP 200,
# image) against the film's Wikipedia poster file before being pinned here.
POSTER_OVERRIDES = {
    "christmas at the kringles": "https://upload.wikimedia.org/wikipedia/en/3/3c/Christmas_at_the_kringles.jpg",
    "resident evil": "https://upload.wikimedia.org/wikipedia/en/3/3c/Resident_Evil_2026_film_poster.png",  # Tiram 2026-11-25: the NEW (2026, Zach Cregger) film, not the 2002 one
    "vision quest first episode": "https://upload.wikimedia.org/wikipedia/en/d/d5/VisionQuest_logo.jpg",  # Tiram 2026-11-25: the Marvel TV series, not the 1985 film
    "vision quest": "https://upload.wikimedia.org/wikipedia/en/d/d5/VisionQuest_logo.jpg",
    "top gun": "https://upload.wikimedia.org/wikipedia/en/4/46/Top_Gun_Movie.jpg",
    "brewster's millions": "https://upload.wikimedia.org/wikipedia/en/5/5f/Brewsters_millions.jpg",
    "office space": "https://upload.wikimedia.org/wikipedia/en/8/8e/Office_space_poster.jpg",
    "pulp fiction": "https://upload.wikimedia.org/wikipedia/en/3/3b/Pulp_Fiction_%281994%29_poster.jpg",
    "matrix": "https://upload.wikimedia.org/wikipedia/en/d/db/The_Matrix.png",
    "the matrix": "https://upload.wikimedia.org/wikipedia/en/d/db/The_Matrix.png",
    "terminator": "https://upload.wikimedia.org/wikipedia/en/6/6d/The_Terminator.png",
    "the terminator": "https://upload.wikimedia.org/wikipedia/en/6/6d/The_Terminator.png",
    "planes trains and automobiles": "https://upload.wikimedia.org/wikipedia/en/d/d6/Planes_trains_and_automobiles.jpg",
    "twister": "https://upload.wikimedia.org/wikipedia/en/a/a5/Twistermovieposter.jpg",
    "ballad of the songbirds and snakes": "https://upload.wikimedia.org/wikipedia/en/9/96/The_Hunger_Games_-_The_Ballad_of_Songbirds_%26_Snakes_official_poster.jpg",
    "the ballad of the songbirds and snakes": "https://upload.wikimedia.org/wikipedia/en/9/96/The_Hunger_Games_-_The_Ballad_of_Songbirds_%26_Snakes_official_poster.jpg",
}


def _fetch_meta(title):
    """Poster + trailer for a title. Trailer falls back to a YouTube search
    for the official trailer when iTunes has no preview clip."""
    key = re.sub(r"\s+", " ", title.strip().lower())
    if key in _meta_cache:
        return _meta_cache[key]
    meta = {
        "poster": None,
        "trailer": "https://www.youtube.com/results?search_query="
        + urllib.parse.quote_plus(title + " official trailer"),
    }
    if key in POSTER_OVERRIDES:
        meta["poster"] = POSTER_OVERRIDES[key]
        _meta_cache[key] = meta
        return meta
    try:
        q = urllib.parse.urlencode(
            {"term": title, "media": "movie", "limit": 1, "country": "US"}
        )
        req = urllib.request.Request(
            "https://itunes.apple.com/search?" + q,
            headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results") or []
        if results:
            item = results[0]
            art = item.get("artworkUrl100")
            if art:
                meta["poster"] = art.replace("100x100bb.jpg", "400x400bb.jpg")
            if item.get("previewUrl"):
                meta["trailer"] = item["previewUrl"]
    except Exception:
        pass
    if not meta["poster"]:
        try:
            meta["poster"] = _wiki_poster(title)
        except Exception:
            pass
    _meta_cache[key] = meta
    return meta


def _wiki_get(params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        "https://en.wikipedia.org/w/api.php?" + q,
        headers={"User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wiki_poster(title):
    """Poster from the film's Wikipedia article: find the article whose
    title matches the query, pick its image file named *poster*, and
    resolve a 400px thumbnail URL. Returns None when unsure — a missing
    poster beats a wrong one."""
    data = _wiki_get({
        "action": "query", "generator": "search",
        "gsrsearch": title + " film", "gsrlimit": 5,
        "prop": "images", "imlimit": 50, "format": "json",
    })
    pages = ((data.get("query") or {}).get("pages") or {}).values()
    stopwords = {"the", "a", "an", "film"}
    query_tokens = set(re.findall(r"[a-z0-9]+", title.lower())) - stopwords
    # Candidates: articles whose title matches the query exactly (modulo
    # stopwords), ignoring series/franchise/soundtrack pages. A poster is
    # used only when there is exactly ONE candidate article — with several
    # film versions (remakes, sequels sharing a name) a missing poster
    # beats a wrong one, and Wikipedia's search ranking is too unstable
    # to pick between versions.
    film_candidates, bare_candidates = [], []
    for page in pages:
        raw_title = page.get("title", "")
        paren_match = re.search(r"\(([^)]*)\)\s*$", raw_title)
        paren = paren_match.group(1).lower() if paren_match else ""
        page_title = re.sub(r"\s*\([^)]*\)\s*$", "", raw_title)
        page_tokens = set(re.findall(r"[a-z0-9]+", page_title.lower())) - stopwords
        if not page_tokens or page_tokens != query_tokens:
            continue
        if not paren:
            bare_candidates.append(page)
        elif "film" in paren and "series" not in paren and "franchise" not in paren:
            film_candidates.append(page)
        # Any other parenthetical (soundtrack, novel, musical...) is a
        # different work with the same name — not a candidate.
    # Pool choice: "(film)" articles first, bare titles second. Within a
    # pool, an article whose stripped title matches the query word-for-word
    # wins ("Twisters" the film, not "The Twisters"); otherwise the pool
    # must hold exactly one article. Several film versions of a name mean
    # no poster — a missing poster beats a wrong one.
    def _norm(text):
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()

    def _poster_of(page):
        for img in page.get("images", []):
            if "poster" in img.get("title", "").lower():
                return img["title"]
        return None

    poster_file = None
    for pool in (film_candidates, bare_candidates):
        if not pool:
            continue
        exact = [
            p for p in pool
            if _norm(re.sub(r"\s*\([^)]*\)\s*$", "", p.get("title", ""))) == _norm(title)
        ]
        if len(exact) == 1:
            poster_file = _poster_of(exact[0])
            break
        if len(pool) == 1:
            poster_file = _poster_of(pool[0])
            break
    if not poster_file:
        return None
    if True:
        info = _wiki_get({
            "action": "query", "titles": poster_file,
            "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 400,
            "format": "json",
        })
        info_pages = (info.get("query") or {}).get("pages") or {}
        for info_page in info_pages.values():
            entries = info_page.get("imageinfo") or []
            if entries:
                url = entries[0].get("thumburl") or entries[0].get("url")
                return url.split("?")[0] if url else None
    return None


def _enrich(result):
    """Attach poster/trailer to every movie in an Apps Script reply."""
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    movies = result.get("movies") or []
    if movies:
        with ThreadPoolExecutor(max_workers=5) as pool:
            metas = list(pool.map(lambda m: _fetch_meta(m["title"]), movies))
        for movie, meta in zip(movies, metas):
            movie["poster"] = meta["poster"]
            movie["trailer"] = meta["trailer"]
    return result


def list_movies():
    return _enrich(_call({"action": "list"}))


def add_movie(title):
    return _enrich(_call({"action": "add", "title": title}))


def vote_movie(row):
    return _enrich(_call({"action": "vote", "row": row}))


def unvote_movie(row):
    return _enrich(_call({"action": "unvote", "row": row}))


def set_watched(row, watched):
    return _enrich(_call({"action": "watched", "row": row, "watched": bool(watched)}))


def delete_movie(row):
    return _enrich(_call({"action": "delete", "row": row}))
