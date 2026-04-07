import json
import os
import sys
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

# 允许作为脚本运行时找到 data.database
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from data.database import Database

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
db = Database()

def to_url(p: str) -> str:
    p = p.replace('\\', '/') 
    if p.startswith('/'):
        p = p[1:]
    return '/api/static/' + p

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,OPTIONS')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,OPTIONS')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == '/api/models':
                models = db.get_active_models()
                res = [{"id": m["id"], "name": m["name"], "preview_image_path": m.get("preview_image_path") or None} for m in models]
                return self._send_json(res)
            if path == '/api/tags':
                tags = db.get_tags_with_category_name(only_active=True)
                res = [{"id": t["id"], "name": t["name"], "category_name": t.get("category_name") or None} for t in tags]
                return self._send_json(res)
            if path == '/api/media':
                mset = set((qs.get('model_ids', [''])[0]).split(',')) - {''}
                tset = set((qs.get('tag_ids', [''])[0]).split(',')) - {''}
                page = int(qs.get('page', ['1'])[0])
                page_size = int(qs.get('page_size', ['30'])[0])
                name_q = (qs.get('name', [''])[0]).strip().lower()
                min_heat_str = qs.get('min_heat', [''])[0]
                max_heat_str = qs.get('max_heat', [''])[0]
                min_heat = int(min_heat_str) if min_heat_str else None
                max_heat = int(max_heat_str) if max_heat_str else None
                all_items = db.get_all_files_with_relations()
                filtered = []
                for info in all_items:
                    models = info.get('models', [])
                    tags = info.get('tags', [])
                    f_info = info.get('file', {})
                    heat_val = f_info.get('heat_value') or 0
                    if min_heat is not None and heat_val < min_heat:
                        continue
                    if max_heat is not None and heat_val > max_heat:
                        continue
                    if name_q:
                        title = (info.get('file', {}).get('original_file_name') or info.get('file', {}).get('file_name') or '').lower()
                        path_s = (info.get('file', {}).get('file_path') or '').lower()
                        if (name_q not in title) and (name_q not in path_s):
                            continue
                    if mset and not any(m['id'] in mset for m in models):
                        continue
                    if tset and not any(t['id'] in tset for t in tags):
                        continue
                    filtered.append(info)
                start = max((page - 1) * page_size, 0)
                end = start + page_size
                slice_items = filtered[start:end]
                result = []
                for info in slice_items:
                    f = info['file']
                    result.append({
                        'id': f['id'],
                        'title': f.get('original_file_name') or f.get('file_name') or f.get('id'),
                        'file_path': to_url(f.get('file_path', '')),
                        'file_type': f.get('file_type') or 'unknown',
                        'thumbnail_path': to_url(f.get('thumbnail_path', '')) if f.get('thumbnail_path') else None,
                        'image_width': f.get('image_width'),
                        'image_height': f.get('image_height'),
                        'video_width': f.get('video_width'),
                        'video_height': f.get('video_height'),
                        'duration_ms': f.get('duration_ms'),
                        'models': [{'id': m['id'], 'name': m['name'], 'preview_image_path': m.get('preview_image_path') or None} for m in info.get('models', [])],
                        'tags': [{'id': t['id'], 'name': t['name']} for t in info.get('tags', [])],
                        'created_at': f.get('created_at'),
                    })
                has_more = end < len(filtered)
                return self._send_json({'items': result, 'hasMore': has_more})
            if path.startswith('/api/static/'):
                rel = path[len('/api/static/'):]
                fs_path = os.path.join(ROOT, rel)
                if not os.path.exists(fs_path) or not os.path.isfile(fs_path):
                    self.send_error(404)
                    return
                # 简单文件传输
                ctype = 'application/octet-stream'
                if fs_path.lower().endswith(('.jpg','.jpeg')):
                    ctype = 'image/jpeg'
                elif fs_path.lower().endswith('.png'):
                    ctype = 'image/png'
                elif fs_path.lower().endswith('.gif'):
                    ctype = 'image/gif'
                elif fs_path.lower().endswith(('.mp4','.webm','.mkv','.mov','.avi','.mpeg','.mpg','.m4v')):
                    ctype = 'video/mp4'
                with open(fs_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)
        except Exception as e:
            self._send_json({'error': str(e)}, code=500)

def main():
    port = 3000
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Simple API server listening on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()

if __name__ == '__main__':
    main()
