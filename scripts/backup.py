"""Create consistent, versioned SQLite snapshots on a separate mounted disk."""
import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def snapshot(source, destination, keep=3):
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = destination / f'{source.stem}-{stamp}.sqlite'
    temporary = target.with_suffix('.partial')
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Snapshot integrity check failed')
    with open(temporary, 'rb+') as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    # Retain only this sensor's snapshots after the new one is complete.
    for old in sorted(destination.glob(f'{source.stem}-*.sqlite'), reverse=True)[keep:]:
        old.unlink()
    print(f'BACKUP_OK {target.name}', flush=True)
    return target


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source-dir', default='data')
    p.add_argument('--destination', default='/mnt/field-backup/snapshots')
    p.add_argument('--mount', default='/mnt/field-backup')
    args = p.parse_args()
    source = Path(args.source_dir).resolve(); destination = Path(args.destination).resolve()
    mount = Path(args.mount).resolve()
    if not mount.is_mount() or not destination.is_relative_to(mount):
        p.error('Backup disk is not mounted at the expected location')
    if os.stat(source).st_dev == os.stat(mount).st_dev:
        p.error('Backup destination must be a different filesystem from the primary data')
    databases = [source/'sensor-a.db', source/'sensor-b.db']
    if not all(x.is_file() for x in databases):
        p.error('Both sensor databases must exist before backing up')
    for database in databases:
        snapshot(database, destination)
