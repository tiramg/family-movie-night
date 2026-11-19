"""Family Movie Night — standalone web service.

Serves the movie-night page and proxies its API calls to the Apps Script
JSON API (which keeps Tiram's Google Sheet as the database). Plain stdlib
HTTP server, no dependencies. Runs on Render's Python runtime.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json, os

from movienight import (
    list_movies as mn_list,
    add_movie as mn_add,
    vote_movie as mn_vote,
    unvote_movie as mn_unvote,
    set_watched as mn_watched,
    delete_movie as mn_delete,
)

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "10000"))
PAGE = (ROOT / "movienight.html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.send_json(200, {"ok": True})
        if path in {"/", "/movienight"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
            return
        if path in {"/api/movies", "/movienight/api/movies"}:
            try:
                return self.send_json(200, mn_list())
            except Exception as exc:
                return self.send_json(502, {"ok": False, "error": str(exc)})
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        actions = {
            "/api/add": "add", "/movienight/api/add": "add",
            "/api/vote": "vote", "/movienight/api/vote": "vote",
            "/api/unvote": "unvote", "/movienight/api/unvote": "unvote",
            "/api/watched": "watched", "/movienight/api/watched": "watched",
            "/api/delete": "delete", "/movienight/api/delete": "delete",
        }
        if path not in actions:
            return self.send_json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            action = actions[path]
            if action == "add":
                result = mn_add(str(payload.get("title", "")))
            elif action == "vote":
                result = mn_vote(int(payload.get("row")))
            elif action == "unvote":
                result = mn_unvote(int(payload.get("row")))
            elif action == "watched":
                result = mn_watched(int(payload.get("row")), bool(payload.get("watched")))
            else:
                result = mn_delete(int(payload.get("row")))
            return self.send_json(200, result)
        except Exception as exc:
            return self.send_json(502, {"ok": False, "error": str(exc)})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
