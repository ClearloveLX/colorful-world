import base64
import json
import os
import sys
import subprocess
import ctypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs


def _get_data_root():
    """与 server.py 保持一致：CW_DATA_ROOT 优先，否则 L:\\data，否则项目内 data。"""
    env = os.environ.get('CW_DATA_ROOT')
    if env and env.strip():
        return os.path.abspath(env.strip())
    candidate = r"L:\data"
    if os.path.isdir(candidate):
        return os.path.abspath(candidate)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))


def _is_local_origin(headers):
    """校验 Origin/Referer 至少存在一个且来自本机页面。

    全部缺失时拒绝：浏览器跨站 POST 必然携带 Origin，缺失说明请求非浏览器来源
    （如恶意脚本），不应放行。server.py 内部调用需显式携带 Origin 头。
    """
    saw_local = False
    for name in ("Origin", "Referer"):
        value = headers.get(name)
        if not value:
            continue
        try:
            host = urlparse(value).netloc.lower()
        except Exception:
            return False
        if host.startswith("localhost") or host.startswith("127.0.0.1"):
            saw_local = True
            continue
        return False
    return saw_local


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
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
            # CSRF 防护：Origin/Referer 缺失或非本机来源的请求直接拒绝
            # （server.py 内部调用已显式携带 Origin: http://127.0.0.1:4397）
            if not _is_local_origin(self.headers):
                self._send_json({"ok": False}, code=403)
                return
            qs = parse_qs(parsed.query)
            b64 = (qs.get("path", [""])[0]) or ""
            try:
                pad = (4 - (len(b64) % 4)) % 4
                p = base64.urlsafe_b64decode(b64 + ("=" * pad)).decode('utf-8')
            except Exception:
                self._send_json({"ok": False}, code=400)
                return
            p = os.path.normpath(os.path.abspath(p.replace("/", os.sep)))
            # 只允许打开媒体库（DATA_ROOT）内的文件
            data_root = os.path.normpath(os.path.abspath(_get_data_root()))
            if not (p.startswith(data_root + os.sep) or p == data_root):
                self._send_json({"ok": False}, code=403)
                return
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
                # 注意：不要用 cmd /c start 或 powershell -Command —— 文件名含 & 或 " 时可注入命令
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
    port = 4397
    server = HTTPServer(('127.0.0.1', port), Handler)
    print(f"Open helper listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == '__main__':
    main()
