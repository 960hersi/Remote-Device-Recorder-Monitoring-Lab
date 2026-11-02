"""Linux telemetry agent with a bounded persistent outbox and HTTPS delivery."""
import argparse
from contextlib import closing
import json
import os
import shutil
import socket
import sqlite3
import ssl
import time
import urllib.request
import uuid
import math
import random
from datetime import datetime, timezone


def initialize(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        db.executemany('INSERT OR IGNORE INTO counters VALUES (?, 0)', [(x,) for x in ('generated', 'acknowledged', 'rejected')])


def pending(path):
    with closing(sqlite3.connect(path)) as db, db:
        return db.execute('SELECT count(*) FROM outbox').fetchone()[0]


def enqueue(path, reading, limit=10000):
    with closing(sqlite3.connect(path)) as db, db:
        if db.execute('SELECT count(*) FROM outbox').fetchone()[0] >= limit:
            db.execute("UPDATE counters SET value=value+1 WHERE name='rejected'")
            return False
        db.execute('INSERT INTO outbox VALUES (?, ?)', (reading['id'], json.dumps(reading)))
        db.execute("UPDATE counters SET value=value+1 WHERE name='generated'")
    return True


def flush(path, url, token, context):
    with closing(sqlite3.connect(path)) as db, db:
        rows = db.execute('SELECT id, payload FROM outbox ORDER BY rowid LIMIT 100').fetchall()
    if not rows:
        return 0
    request = urllib.request.Request(url + '/readings',
        data=json.dumps([json.loads(row[1]) for row in rows]).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, context=context, timeout=3) as response:
        acked = set(json.load(response)['acked'])
    delivered = [row[0] for row in rows if row[0] in acked]
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany('DELETE FROM outbox WHERE id = ?', [(x,) for x in delivered])
        db.execute("UPDATE counters SET value=value+? WHERE name='acknowledged'", (len(delivered),))
    return len(delivered)


def status(path):
    with closing(sqlite3.connect(path)) as db:
        values = dict(db.execute('SELECT name, value FROM counters'))
        values['pending'] = db.execute('SELECT count(*) FROM outbox').fetchone()[0]
        return values


def sample(sensor, queue_count):
    memory = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, value = line.split(':', 1)
            memory[key] = int(value.strip().split()[0])
    disk = shutil.disk_usage('/')
    return {'id': str(uuid.uuid4()), 'node': sensor, 'host': socket.gethostname(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'simulated_temperature_c': round(20 + 2 * math.sin(time.time() / 600) + random.uniform(-0.2, 0.2), 2),
        'pending_before_sample': queue_count,
        'load_1m': os.getloadavg()[0],
        'memory_used_percent': round(100 * (1 - memory['MemAvailable'] / memory['MemTotal']), 2),
        'disk_used_percent': round(100 * disk.used / disk.total, 2)}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--url')
    p.add_argument('--sensor', choices=['SENSOR-A', 'SENSOR-B'])
    p.add_argument('--status', action='store_true')
    p.add_argument('--ca', default='collector.crt')
    p.add_argument('--db', default='agent.db')
    p.add_argument('--interval', type=float, default=10)
    args = p.parse_args()
    initialize(args.db)
    if args.status:
        print(json.dumps(status(args.db), indent=2))
        raise SystemExit(0)
    if not args.url or not args.url.startswith('https://') or args.interval < 1 or not args.sensor:
        p.error('Use an HTTPS URL and an interval of at least one second')
    token = os.environ.get('LAB_TOKEN', '')
    if len(token) < 32:
        p.error('Set LAB_TOKEN to the same value used by the collector')
    context = ssl.create_default_context(cafile=args.ca)
    print('Agent started; Ctrl+C stops it. Pending readings persist on disk.', flush=True)
    try:
        while True:
            started = time.monotonic()
            r = sample(args.sensor, pending(args.db))
            accepted = enqueue(args.db, r)
            print(f"sample={r['id']} queued={accepted}", flush=True)
            if not accepted:
                print('BUFFER FULL: new sample rejected; earlier samples retained', flush=True)
            try:
                delivered = flush(args.db, args.url.rstrip('/'), token, context)
                print(f'acknowledged={delivered} pending={pending(args.db)}', flush=True)
            except Exception as e:
                print(f'delivery_failed={type(e).__name__} pending={pending(args.db)}', flush=True)
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print('\nStopped. Outbox preserved.', flush=True)
