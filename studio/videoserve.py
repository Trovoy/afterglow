"""Serve one local video file to the Studio page over http://127.0.0.1.

The page is loaded from pywebview's local http server, so it may not read file:// URLs (the <video> fails
with MEDIA_ERR_SRC_NOT_SUPPORTED). This server only listens on 127.0.0.1, only serves the file registered
last, behind a random token, and supports Range requests so seeking works on multi-GB recordings.
"""
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

CHUNK = 256 * 1024


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        srv = self.server
        path = srv.files.get(self.path.split('/')[2] if self.path.count('/') >= 2 else '')
        if not path or not path.is_file():
            self.send_error(404); return
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get('Range', '')
        if rng.startswith('bytes='):
            a, _, b = rng[6:].split(',')[0].partition('-')
            try:
                if a:
                    start = int(a); end = int(b) if b else end
                else:                                  # bytes=-N: the last N bytes
                    start = max(0, size - int(b))
            except ValueError:
                self.send_error(416); return
            if start > end or start >= size:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.end_headers(); return
            end = min(end, size - 1)
            self.send_response(206); self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        else:
            self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        left = end - start + 1
        try:
            with open(path, 'rb') as f:
                f.seek(start)
                while left > 0:
                    data = f.read(min(CHUNK, left))
                    if not data:
                        break
                    self.wfile.write(data); left -= len(data)
        except (ConnectionError, OSError):
            pass                                       # the player cancels requests while seeking


class VideoServer:
    def __init__(self):
        self._srv = None

    def url(self, path):
        """Start on first use; register `path` (replacing the previous one) and return its URL."""
        if self._srv is None:
            self._srv = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
            self._srv.daemon_threads = True
            self._srv.files = {}
            threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        token = secrets.token_urlsafe(12)
        self._srv.files = {token: Path(path)}
        return f'http://127.0.0.1:{self._srv.server_address[1]}/v/{token}/{quote(Path(path).name)}'
