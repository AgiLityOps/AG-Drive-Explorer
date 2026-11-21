#!/usr/bin/env python3
"""Tiny local web server for the AG Drive Track Explorer (forces correct MIME types, opens the browser)."""
import http.server, socketserver, os, sys, webbrowser, threading, functools
ROOT = os.path.dirname(os.path.abspath(__file__))
class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
        '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.glb': 'model/gltf-binary',
        '.webp': 'image/webp', '.jpg': 'image/jpeg', '.png': 'image/png', '.css': 'text/css', '.html': 'text/html', '.wasm': 'application/wasm'}
    def log_message(self, *a): pass
    def end_headers(self):
        self.send_header('Cache-Control', 'max-age=3600'); super().end_headers()
class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True
def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8642
    handler = functools.partial(H, directory=ROOT)
    for p in range(port, port + 20):
        try: srv = S(('127.0.0.1', p), handler); break
        except OSError: continue
    else: print('No free port found'); sys.exit(1)
    url = 'http://127.0.0.1:%d/' % p
    print('AG Drive Track Explorer running at', url); print('Close this window (or press Ctrl+C) to stop.')
    if '--no-browser' not in sys.argv: threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
if __name__ == '__main__': main()
