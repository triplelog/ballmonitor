"""`ballmonitor preview`: the public site as ballmonitor.com shows it, straight from the sources.

It answers at once (no build first):

- every page address is its source file in web/site/ (web/pages.py), with index.html's shell
  blocks, so an edit shows on the next reload;
- /static/* (site.js, site.css, the logo...) and the icons come from web/static/;
- everything else (data/site.json and data/views/*, the games, the charts, editor.html) comes
  from a built copy of the site (`--out`, default dist/), which it builds in the background when
  there is none or when asked to (`--rebuild`); until that is done those requests answer 503.

Claude UI's Editor uses it as the "Ball Monitor" site's proxy: the Editor serves the page files
itself and asks this server for the rest.
"""

from __future__ import annotations

import mimetypes
import threading
import traceback
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from ballmonitor.web import builder, pages

ROOT_ICONS = set(builder.ROOT_ICONS)


class Preview:
    def __init__(self, out: Path) -> None:
        self.out = out.resolve()
        self.building = False
        self.error = ""

    @property
    def built(self) -> bool:
        return (self.out / "data" / "site.json").is_file()

    def build(self) -> None:
        self.building, self.error = True, ""
        try:
            builder.build_static_site(self.out, log=lambda *a: print(*a, flush=True))
        except Exception:  # noqa: BLE001 - shown on the 503 page, the server keeps running
            self.error = traceback.format_exc()
            print(self.error, flush=True)
        finally:
            self.building = False

    def build_in_background(self) -> None:
        if not self.building:
            threading.Thread(target=self.build, daemon=True).start()


def handler(preview: Preview) -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(preview.out), **kwargs)

        def end_headers(self) -> None:
            self.send_header("cache-control", "no-store")
            super().end_headers()

        def log_message(self, *args) -> None:   # quiet: the build's own lines are what matter
            pass

        def _file(self, path: Path, status: HTTPStatus = HTTPStatus.OK, body: bytes | None = None) -> None:
            data = body if body is not None else path.read_bytes()
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(status)
            self.send_header("content-type", f"{kind}; charset=utf-8" if kind.startswith("text/") else kind)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            path = unquote(urlparse(self.path).path)
            parts = [p for p in path.split("/") if p]
            static = builder.STATIC_DIR
            if len(parts) == 2 and parts[0] == "static" and (static / parts[1]).is_file():
                return self._file(static / parts[1])
            if len(parts) >= 2 and parts[0] == "static" and not any(p.startswith(".") for p in parts):
                f = static.joinpath(*parts[1:])
                if f.is_file():
                    return self._file(f)
            if len(parts) == 1 and parts[0] in ROOT_ICONS:
                return self._file(static / parts[0])
            if path.endswith("/") or parts[-1:] == ["index.html"]:
                # any page address (a forecast page, one of its options, a chart, a table): the
                # source file that serves it, as it is now; site.js fills it in
                source = pages.source_file(path)
                if source:
                    master = pages.address_file("").read_text(encoding="utf-8")
                    text = pages.with_shared(source.read_text(encoding="utf-8"), master)
                    return self._file(source, body=text.encode("utf-8"))
            if not preview.built:
                if not preview.building and not preview.error:
                    preview.build_in_background()
                note = (f"The site's data is being built into {preview.out} (about a minute). Reload then."
                        if not preview.error else f"The build failed:\n\n{preview.error}")
                return self._file(Path("x.txt"), HTTPStatus.SERVICE_UNAVAILABLE, note.encode("utf-8"))
            if not (preview.out / path.lstrip("/")).exists():
                f404 = pages.SITE_DIR / "404.html"
                return self._file(f404, HTTPStatus.NOT_FOUND)
            return super().do_GET()

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128   # a browser (or the Editor's proxy) opens many connections at once; the default 5 drops some


def serve(host: str = "127.0.0.1", port: int = 8790, out: Path = Path("dist"), rebuild: bool = False) -> None:
    preview = Preview(out)
    if rebuild or not preview.built:
        preview.build_in_background()
    httpd = Server((host, port), handler(preview))
    print(f"ballmonitor public site preview at http://{host}:{port}/ "
          f"(pages and /static from the sources; data from {preview.out}"
          f"{', building it now' if preview.building else ''})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
