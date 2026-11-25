"""Local preview server for docs/ that tells browsers never to cache (so Safari always shows the latest edits)."""
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

class NoCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
ThreadingHTTPServer(("", port), partial(NoCache, directory="docs")).serve_forever()
