"""Serve only the Plugin View assets for local prototype review."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    print("Prototype: http://127.0.0.1:8769/prototype.html?variant=B", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8769), handler).serve_forever()
