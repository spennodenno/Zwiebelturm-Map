"""Local preview:  python serve.py   → http://localhost:8000"""
import functools
import http.server
import pathlib
import webbrowser

site = pathlib.Path(__file__).resolve().parent / "site"
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
print("Serving the map at http://localhost:8000  (Ctrl+C to stop)")
webbrowser.open("http://localhost:8000")
http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler).serve_forever()
