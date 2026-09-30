#!/usr/bin/env python3
"""🌐 Sirve reports/ (el panel y los informes) en el puerto 8899 de la red local. Lo arranca bot.sh."""
import functools
import http.server
from pathlib import Path

REPORTS = Path(__file__).resolve().parent.parent / "reports"
PORT = 8899

if __name__ == '__main__':
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(REPORTS))
    http.server.ThreadingHTTPServer(('0.0.0.0', PORT), handler).serve_forever()
