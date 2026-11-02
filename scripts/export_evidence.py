"""Export lab results and selected logs without copying credentials or keys."""
import argparse
import csv
import io
import json
import sqlite3
import subprocess
import tarfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return f'Exit code: {result.returncode}\n{result.stdout}\n{result.stderr}'
    except (OSError, subprocess.TimeoutExpired) as error:
        return f'Export unavailable: {error}\n'


def export(role, app):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = app / 'evidence-exports' / f'{role}-{stamp}'
    destination.mkdir(parents=True)
    (destination/'export-info.txt').write_text(
        f'Role: {role}\nExport UTC: {stamp}\nReview before publishing. No credentials are intentionally exported.\n', encoding='utf-8')
    services = ['field-sensor-a', 'field-sensor-b', 'field-backup.service', 'field-backup.timer'] if role == 'outdoor' else ['field-collector', 'field-dashboard']
    for service in services:
        (destination/f'{service}-status.txt').write_text(command([
            'systemctl', 'show', service, '--property=ActiveState,SubState,NRestarts,Result,ExecMainStatus']), encoding='utf-8')
        (destination/f'{service}-journal.txt').write_text(command([
            'sudo', '-n', 'journalctl', '-u', service, '--since', '24 hours ago', '--no-pager', '-o', 'short-iso']), encoding='utf-8')
    if role == 'outdoor':
        import agent
        summary = {}
        for sensor in ('a', 'b'):
            file = app/'data'/f'sensor-{sensor}.db'
            if file.is_file():
                summary[f'SENSOR-{sensor.upper()}'] = agent.status(str(file))
        (destination/'queue-counters.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        disk = command(['df', '-h', str(app/'data'), '/mnt/field-backup'])
        disk += '\n' + command(['findmnt', '/mnt/field-backup'])
        disk += '\nSnapshot files:\n' + '\n'.join(p.name for p in Path('/mnt/field-backup/snapshots').glob('*.sqlite'))
        (destination/'backup-disk.txt').write_text(disk, encoding='utf-8')
    else:
        import dashboard
        file=app/'data'/'collector.db'
        if file.is_file():
            (destination/'dashboard-status.json').write_text(json.dumps(dashboard.report(str(file)), indent=2), encoding='utf-8')
            with closing(sqlite3.connect(file.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                with (destination/'readings.csv').open('w',newline='',encoding='utf-8') as output:
                    writer=csv.writer(output)
                    writer.writerow(['id','sensor','recorded_at_utc','simulated_temperature_c','load_1m','memory_used_percent','disk_used_percent','pending_before_sample'])
                    for identifier,sensor,when,payload in db.execute('SELECT id,node,recorded_at,payload FROM readings ORDER BY recorded_at'):
                        r=json.loads(payload)
                        writer.writerow([identifier,sensor,when]+[r.get(k,'') for k in ('simulated_temperature_c','load_1m','memory_used_percent','disk_used_percent','pending_before_sample')])
    archive=destination.with_suffix('.tar.gz')
    with tarfile.open(archive,'w:gz') as tar:
        tar.add(destination,arcname=destination.name)
    print(f'Created {archive}')
    print('Check journal files for export failures. Copy this archive to your Windows computer BEFORE deletion.')
    return archive


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('role',choices=['outdoor','monitor'])
    a=p.parse_args()
    export(a.role,Path(__file__).resolve().parent)
