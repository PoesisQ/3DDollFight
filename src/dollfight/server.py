"""Loopback-only evaluation app. Launch: uv run python -m dollfight.server."""

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from jsonschema import ValidationError

from dollfight.kinematics import PROFILES
from dollfight.pipeline import CATALOG, ROOT, export_poseframes, make_run

WEB = ROOT / "apps/motion-lab"


class Handler(BaseHTTPRequestHandler):
    def reply(self, value, status=200):
        payload = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/catalog":
            self.reply({"sources": CATALOG, "profiles": PROFILES})
            return
        target = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            self.send_error(404)
            return
        types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".txt": "text/plain",
        }
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", types.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path not in ("/api/run", "/api/export"):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 20 * 1024 * 1024:
                raise ValueError("请求体应为 1 B–20 MB")
            config = json.loads(self.rfile.read(length))
            if not isinstance(config, dict):
                raise ValueError("配置必须为 JSON 对象")
            run = make_run(config, include_duel=self.path == "/api/run")
            self.reply(run if self.path == "/api/run" else {"frames": export_poseframes(run)})
        except ValidationError as exc:
            self.reply({"error": f"协议字段 {list(exc.path)}: {exc.message}"}, 400)
        except (ValueError, KeyError, TypeError) as exc:
            self.reply({"error": str(exc)}, 400)
        except Exception as exc:
            self.log_error("Processing failed: %s", exc)
            self.reply({"error": f"处理失败：{type(exc).__name__}: {exc}"}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18943)
    parser.add_argument("--open", action="store_true", help="Open the local lab in your browser")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"DollFight Motion Lab: http://127.0.0.1:{args.port}", flush=True)
    print(f"Serving {Path(WEB)}; algorithms run locally on CPU.", flush=True)
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
