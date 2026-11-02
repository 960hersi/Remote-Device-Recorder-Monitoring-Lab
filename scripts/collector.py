"""Small authenticated HTTPS telemetry collector for a personal lab."""
import argparse
from contextlib import closing
import hmac
import json
import os
import sqlite3
import ssl
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


def initialize(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS readings (id TEXT PRIMARY KEY, node TEXT NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL)')


def store(path, readings):
    with closing(sqlite3.connect(path)) as db, db:
        for r in readings:
            if not all(isinstance(r.get(k), str) and r[k] for k in ('id', 'node', 'recorded_at')):
                raise ValueError('Missing reading identifiers')
            db.execute('INSERT OR IGNORE INTO readings VALUES (?, ?, ?, ?)',
                       (r['id'], r['node'], r['recorded_at'], json.dumps(r)))
    return [r['id'] for r in readings]


def handler_for(path, token):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value):
            raw = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            supplied = self.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied, 'Bearer ' + token):
                self.reply(401, {'error': 'Unauthorized'})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if self.path != '/status':
                return self.reply(404, {'error': 'Unknown endpoint'})
            with closing(sqlite3.connect(path)) as db, db:
                total = db.execute('SELECT count(*) FROM readings').fetchone()[0]
                rows = db.execute('SELECT node, max(recorded_at), count(*) FROM readings GROUP BY node').fetchall()
            now = datetime.now(timezone.utc)
            nodes = []
            for name, timestamp, count in rows:
                age = (now - datetime.fromisoformat(timestamp)).total_seconds()
                nodes.append({'node': name, 'last_recorded_at': timestamp, 'age_seconds': round(age, 1), 'stale': age > 30, 'stored': count})
            self.reply(200, {'total': total, 'nodes': nodes})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/readings':
                return self.reply(404, {'error': 'Unknown endpoint'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 262144:
                    return self.reply(413, {'error': 'Invalid body size'})
                batch = json.loads(self.rfile.read(size))
                if not isinstance(batch, list) or not 1 <= len(batch) <= 100:
                    raise ValueError('Batch must contain 1 to 100 readings')
                if not all(isinstance(r, dict) for r in batch):
                    raise ValueError('Readings must be objects')
                for r in batch:
                    timestamp = datetime.fromisoformat(r.get('recorded_at', ''))
                    if timestamp.tzinfo is None:
                        raise ValueError('Timestamp requires timezone')
                ids = store(path, batch)
                self.reply(200, {'acked': ids})
            except (ValueError, TypeError, KeyError):
                self.reply(400, {'error': 'Invalid reading data'})
    return Handler


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='collector.db')
    p.add_argument('--cert', default='collector.crt')
    p.add_argument('--key', default='collector.key')
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8443)
    args = p.parse_args()
    token = os.environ.get('LAB_TOKEN', '')
    if len(token) < 32:
        p.error('Set LAB_TOKEN to a random value of at least 32 characters')
    initialize(args.db)
    server = HTTPServer((args.host, args.port), handler_for(args.db, token))
    server.timeout = 10
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f'Collector listening on HTTPS port {args.port}', flush=True)
    server.serve_forever()
