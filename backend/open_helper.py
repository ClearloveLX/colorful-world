import base64
import os
import sys
import subprocess
import ctypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        data = ('{"ok":true}' if code == 200 else '{"ok":false}').encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST,OPTIONS')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST,OPTIONS')
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/open":
            qs = parse_qs(parsed.query)
            b64 = (qs.get("path", [""])[0]) or ""
            try:
                pad = (4 - (len(b64) % 4)) % 4
                p = base64.urlsafe_b64decode(b64 + ("=" * pad)).decode('utf-8')
            except Exception:
                self._send_json({"ok": False}, code=400)
                return
            p = os.path.normpath(p.replace("/", os.sep))
            if not os.path.isfile(p):
                self._send_json({"ok": False}, code=404)
                return
            try:
                ok = False
                try:
                    r = ctypes.windll.shell32.ShellExecuteW(None, "open", p, None, os.path.dirname(p), 1)
                    ok = True if r and r > 32 else False
                except Exception:
                    pass
                if ok:
                    self._send_json({"ok": True}, code=200)
                    return
                try:
                    os.startfile(p)  # type: ignore
                    ok = True
                except Exception:
                    pass
                if not ok:
                    try:
                        subprocess.Popen(f'start "" "{p}"', shell=True)
                        ok = True
                    except Exception:
                        pass
                if not ok:
                    try:
                        subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", f'Start-Process -Verb Open -FilePath "{p}"'])
                        ok = True
                    except Exception:
                        pass
                if not ok:
                    try:
                        subprocess.Popen(["rundll32.exe", "url.dll,FileProtocolHandler", p])
                        ok = True
                    except Exception:
                        pass
                if not ok:
                    subprocess.Popen(["explorer.exe", p])
                self._send_json({"ok": True}, code=200)
            except Exception:
                self._send_json({"ok": False}, code=500)
            return
        self._send_json({"ok": False}, code=404)


def main():
    port = 8001
    server = HTTPServer(('127.0.0.1', port), Handler)
    print(f"Open helper listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == '__main__':
    main()
