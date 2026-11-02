"""Read-only lab dashboard, bound to loopback; access through an SSH tunnel."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Remote station monitoring lab</title><style>
body{font:16px system-ui;margin:40px auto;max-width:1080px;padding:0 20px;background:#f4f6f8;color:#142334}
table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:14px;border-bottom:1px solid #d4dce5}
.ok{color:#166534}.stale{color:#b91c1c}small{color:#4b5563}h1{font-size:28px}
</style><h1>Remote station monitoring lab</h1>
<p>Two simulated sensors on one outdoor VM. Readings arrive over authenticated HTTPS.</p>
<p id="summary">Loading...</p><table><thead><tr><th>Sensor</th><th>Reading freshness</th><th>Temperature</th><th>Stored</th><th>Reported queue*</th><th>Latest reading UTC</th></tr></thead><tbody id="rows"></tbody></table>
<p><small>*Queue size was measured before that reading was queued and sent. It is not a live queue measurement during an outage. Stale means no reading timestamp within 30 seconds; it does not diagnose the cause.</small></p>
<p id="error"></p><script>
async function refresh(){try{let r=await fetch('/api/status');if(!r.ok)throw Error('Status unavailable');let d=await r.json();
document.getElementById('summary').textContent=`Total stored readings: ${d.total} | Refreshed: ${new Date().toLocaleTimeString()}`;
let body=document.getElementById('rows');body.replaceChildren();
for(let s of d.sensors){let tr=document.createElement('tr');let values=[s.sensor,s.state,s.temperature===null?'—':s.temperature+' °C',s.count,s.queue===null?'—':s.queue,s.last||'No reading yet'];
values.forEach((v,i)=>{let td=document.createElement('td');td.textContent=v;if(i===1)td.className=s.state==='CURRENT'?'ok':'stale';tr.appendChild(td)});body.appendChild(tr)}
document.getElementById('error').textContent='';}catch(e){document.getElementById('error').textContent='Dashboard refresh failed: '+e.message}}
refresh();setInterval(refresh,5000);
</script></html>'''


def report(path):
    now = datetime.now(timezone.utc)
    result = []
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        total = db.execute('SELECT count(*) FROM readings').fetchone()[0]
        for sensor in ('SENSOR-A', 'SENSOR-B'):
            count = db.execute('SELECT count(*) FROM readings WHERE node=?', (sensor,)).fetchone()[0]
            row = db.execute('SELECT recorded_at, payload FROM readings WHERE node=? ORDER BY recorded_at DESC LIMIT 1', (sensor,)).fetchone()
            if not row:
                result.append(dict(sensor=sensor,state='NO DATA',count=0,temperature=None,queue=None,last=None))
                continue
            age = (now - datetime.fromisoformat(row[0])).total_seconds()
            payload = json.loads(row[1])
            result.append(dict(sensor=sensor,state='CURRENT' if -30 <= age <= 30 else 'STALE',count=count,
                temperature=payload.get('simulated_temperature_c'),queue=payload.get('pending_before_sample'),last=row[0]))
    return {'total': total, 'sensors': result}


def handler_for(path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                data = PAGE.encode(); kind = 'text/html; charset=utf-8'; code = 200
            elif self.path == '/api/status':
                try:
                    data = json.dumps(report(path)).encode(); code = 200
                except sqlite3.Error:
                    data = b'{"error":"Collector database not ready"}'; code = 503
                kind = 'application/json'
            else:
                data = b'Not found'; kind = 'text/plain'; code = 404
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(data)
    return Handler


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='data/collector.db')
    p.add_argument('--port', type=int, default=8080)
    args = p.parse_args()
    print('Dashboard available on loopback only; connect using an SSH tunnel.', flush=True)
    HTTPServer(('127.0.0.1', args.port), handler_for(args.db)).serve_forever()
