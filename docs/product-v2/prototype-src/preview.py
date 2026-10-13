"""Short-lived preview serving only public prototype artifacts on loopback."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'prototype'
class Preview(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(root),**kw)
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path.split('?',1)[0] not in ['/','/index.html','/app.js','/style.css','/THIRD-PARTY-NOTICES.md']:
   self.send_error(404);return
  super().do_GET()
ThreadingHTTPServer(('127.0.0.1',19864),Preview).serve_forever()
