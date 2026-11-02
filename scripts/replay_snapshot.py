"""Resend snapshot outbox records without altering the snapshot, for dedupe tests."""
import argparse
import json
import os
import sqlite3
import ssl
import urllib.request
from pathlib import Path
from contextlib import closing

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--ca', default='collector.crt')
    args = p.parse_args()
    if not args.url.startswith('https://') or not args.snapshot.is_file():
        p.error('Use HTTPS and an existing snapshot')
    token = os.environ['LAB_TOKEN']
    context = ssl.create_default_context(cafile=args.ca)
    with closing(sqlite3.connect(args.snapshot.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM outbox')]
    headers = {'Content-Type':'application/json','Authorization':'Bearer '+token}
    def count():
        req = urllib.request.Request(args.url+'/status', headers=headers)
        with urllib.request.urlopen(req,context=context,timeout=5) as r:
            return json.load(r)['total']
    before = count()
    for i in range(0, len(records), 100):
        batch=records[i:i+100]
        req=urllib.request.Request(args.url+'/readings',data=json.dumps(batch).encode(),headers=headers)
        with urllib.request.urlopen(req,context=context,timeout=5) as r:
            response=json.load(r)
        if set(response['acked']) != {item['id'] for item in batch}:
            raise RuntimeError('Incomplete acknowledgement')
    after = count()
    print(f'Snapshot records sent: {len(records)}; total before: {before}; total after: {after}; increase: {after-before}')
