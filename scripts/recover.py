"""Restore a SQLite snapshot to a NEW file; does not overwrite existing data."""
import argparse
import sqlite3
from pathlib import Path
from contextlib import closing


def recover(snapshot, output):
    if not snapshot.is_file():
        raise ValueError('Snapshot does not exist')
    if output.exists():
        raise ValueError('Output already exists: preserve it before restoring')
    with closing(sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)) as src:
        if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Snapshot integrity check failed')
        with closing(sqlite3.connect(output)) as dst:
            src.backup(dst)
    print(f'Restored {snapshot.name} into {output}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    recover(a.snapshot, a.output)
