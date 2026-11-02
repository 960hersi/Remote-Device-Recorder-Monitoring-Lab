"""Offline logic tests. No Azure deployment or physical durability is tested."""
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import agent
import collector
import dashboard
import backup
import recover
import export_evidence
import tarfile


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root=Path(self.tmp.name)
        self.ap=str(self.root/'sensor-a.db'); self.cp=str(self.root/'collector.db')
        agent.initialize(self.ap); collector.initialize(self.cp)
        self.token='a'*64

    def tearDown(self):
        self.tmp.cleanup()

    def reading(self, id='one', node='SENSOR-A', when=None):
        return {'id':id,'node':node,'recorded_at':(when or datetime.now(timezone.utc)).isoformat(),
                'simulated_temperature_c':20,'pending_before_sample':0}

    def transport(self, request, **kwargs):
        self.assertEqual(request.get_header('Authorization'),'Bearer '+self.token)
        ids=collector.store(self.cp,json.loads(request.data))
        return io.BytesIO(json.dumps({'acked':ids}).encode())

    def test_failed_delivery_keeps_queue_then_ack_removes(self):
        agent.enqueue(self.ap,self.reading())
        with patch.object(agent.urllib.request,'urlopen',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                agent.flush(self.ap,'https://example',self.token,None)
        self.assertEqual(agent.pending(self.ap),1)
        with patch.object(agent.urllib.request,'urlopen',side_effect=self.transport):
            self.assertEqual(agent.flush(self.ap,'https://example',self.token,None),1)
        self.assertEqual(agent.status(self.ap),dict(generated=1,acknowledged=1,rejected=0,pending=0))

    def test_lost_ack_retry_deduplicates(self):
        r=self.reading(); agent.enqueue(self.ap,r)
        collector.store(self.cp,[r]) # server saved, but its acknowledgement was lost
        with patch.object(agent.urllib.request,'urlopen',side_effect=self.transport):
            self.assertEqual(agent.flush(self.ap,'https://example',self.token,None),1)
        with closing(sqlite3.connect(self.cp)) as db:
            self.assertEqual(db.execute('select count(*) from readings').fetchone()[0],1)

    def test_capacity_and_restart_persistence(self):
        self.assertTrue(agent.enqueue(self.ap,self.reading(),limit=1))
        self.assertFalse(agent.enqueue(self.ap,self.reading('two'),limit=1))
        agent.initialize(self.ap)
        self.assertEqual(agent.status(self.ap)['pending'],1)
        self.assertEqual(agent.status(self.ap)['rejected'],1)

    def test_snapshot_restore_and_retention(self):
        agent.enqueue(self.ap,self.reading())
        dest=self.root/'backups'
        for _ in range(5): latest=backup.snapshot(Path(self.ap),dest,keep=3)
        self.assertEqual(len(list(dest.glob('*.sqlite'))),3)
        output=self.root/'restored.db'
        recover.recover(latest,output)
        self.assertEqual(agent.pending(str(output)),1)
        with self.assertRaises(ValueError): recover.recover(latest,output)

    def test_dashboard_two_sensors_and_stale(self):
        collector.store(self.cp,[self.reading(),self.reading('two','SENSOR-B',datetime.now(timezone.utc)-timedelta(seconds=60))])
        r=dashboard.report(self.cp)
        self.assertEqual([s['state'] for s in r['sensors']],['CURRENT','STALE'])
        self.assertEqual(r['total'],2)

    def test_token_check(self):
        h=object.__new__(collector.handler_for(self.cp,self.token))
        replies=[]; h.reply=lambda code,value:replies.append(code)
        h.headers={'Authorization':'Bearer incorrect'}
        self.assertFalse(h.authorized()); self.assertEqual(replies,[401])
        h.headers={'Authorization':'Bearer '+self.token}
        self.assertTrue(h.authorized())

    def test_evidence_export_includes_readings_excludes_secrets(self):
        data=self.root/'data'; data.mkdir()
        cp=data/'collector.db'; collector.initialize(str(cp))
        collector.store(str(cp),[self.reading()])
        (self.root/'token.txt').write_text('private-test-token')
        with patch.object(export_evidence,'command',return_value='Exit code: 0\nMock service evidence'):
            archive=export_evidence.export('monitor',self.root)
        with tarfile.open(archive) as tar:
            names=tar.getnames()
            self.assertFalse(any(name.endswith('token.txt') for name in names))
            member=next(name for name in names if name.endswith('readings.csv'))
            contents=tar.extractfile(member).read().decode()
            self.assertIn('SENSOR-A',contents)
            self.assertNotIn('private-test-token',contents)


if __name__ == '__main__':
    unittest.main(verbosity=2)
