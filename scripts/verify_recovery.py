"""On collector, verify all pending IDs in an agent snapshot were received."""
import argparse
import sqlite3
from pathlib import Path
from contextlib import closing

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', required=True, type=Path)
    p.add_argument('--collector-db', default='data/collector.db', type=Path)
    a = p.parse_args()
    for file in (a.snapshot, a.collector_db):
        if not file.is_file():
            p.error(f'File not found: {file}')
    with closing(sqlite3.connect(a.snapshot.resolve().as_uri()+'?mode=ro',uri=True)) as src:
        ids = [row[0] for row in src.execute('SELECT id FROM outbox')]
    with closing(sqlite3.connect(a.collector_db.resolve().as_uri()+'?mode=ro',uri=True)) as dst:
        missing = [value for value in ids if dst.execute('SELECT 1 FROM readings WHERE id=?',(value,)).fetchone() is None]
    print(f'Snapshot pending IDs: {len(ids)}; found: {len(ids)-len(missing)}; missing: {len(missing)}')
    if not ids:
        raise SystemExit('No pending records in snapshot: repeat recovery test while offline')
    raise SystemExit(1 if missing else 0)
