#!/usr/bin/env python3
"""
Local collector for RTSports page text.

RTSports needs a logged-in browser session (cookies), so the pages are read
from Chrome and POSTed here as plain text. Runs on 127.0.0.1 only, writes
each POST body to <name>.txt in this folder, and exits once every expected
name has arrived (or after --timeout seconds).

    python3 collect.py rosters fa            # wait for rosters.txt and fa.txt

From the RTS page (same-origin, cookies attached), in the browser console:
    fetch('http://127.0.0.1:8765/rosters',{method:'POST',mode:'no-cors',body:document.querySelector('main').innerText})
"""
import os, sys, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith('--')]
timeout = int(next((a.split('=')[1] for a in sys.argv if a.startswith('--timeout=')), '600'))
expected = set(args)
got = set()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        name = self.path.strip('/').split('?')[0]
        if not name.replace('_', '').replace('-', '').isalnum():
            self.send_response(400); self.end_headers(); return
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n)
        with open(os.path.join(HERE, name + '.txt'), 'wb') as f:
            f.write(body)
        got.add(name)
        print(f'received {name} ({n} bytes)', flush=True)
        self.send_response(200); self.end_headers()

srv = HTTPServer(('127.0.0.1', 8765), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f'collector listening on 127.0.0.1:8765, waiting for: {sorted(expected)}', flush=True)
t0 = time.time()
while (expected - got) and time.time() - t0 < timeout:
    time.sleep(0.5)
srv.shutdown()
missing = expected - got
print('done' if not missing else f'timeout, missing: {sorted(missing)}', flush=True)
sys.exit(0 if not missing else 1)
