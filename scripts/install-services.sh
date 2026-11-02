#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
APP="$(pwd)"
if [[ "$(id -un)" != azureuser || "$APP" != /home/azureuser/field-lab ]]; then
  echo 'Run as azureuser from /home/azureuser/field-lab'; exit 1
fi
ROLE="${1:-}"
[[ "$ROLE" == collector || "$ROLE" == outdoor ]] || { echo 'Usage: bash install-services.sh collector|outdoor'; exit 1; }
[[ -f token.txt ]] || { echo 'Missing token.txt'; exit 1; }
TOKEN="$(cat token.txt)"
[[ "$TOKEN" =~ ^[a-f0-9]{64}$ ]] || { echo 'Expected a 64-character hex token'; exit 1; }
mkdir -p data
printf 'LAB_TOKEN=%s\n' "$TOKEN" > lab.env
chmod 600 lab.env token.txt
if [[ "$ROLE" == collector ]]; then
  [[ -f collector.crt && -f collector.key ]] || { echo 'Create the TLS certificate first'; exit 1; }
  chmod 600 collector.key
  sudo tee /etc/systemd/system/field-collector.service >/dev/null <<EOF
[Unit]
Description=Field lab HTTPS collector
After=network-online.target
Wants=network-online.target
[Service]
User=azureuser
WorkingDirectory=$APP
EnvironmentFile=$APP/lab.env
ExecStart=/usr/bin/python3 -u $APP/collector.py --db data/collector.db
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
  sudo tee /etc/systemd/system/field-dashboard.service >/dev/null <<EOF
[Unit]
Description=Field lab private monitoring dashboard
After=field-collector.service
Wants=field-collector.service
[Service]
User=azureuser
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 -u $APP/dashboard.py --db data/collector.db
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable field-collector field-dashboard
  sudo systemctl restart field-collector field-dashboard
else
  [[ -f collector.crt ]] || { echo 'Transfer collector.crt first'; exit 1; }
  read -r -p 'Collector PRIVATE IPv4 address: ' COLLECTOR_IP
  [[ "$COLLECTOR_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Enter an IPv4 address'; exit 1; }
  printf 'COLLECTOR_URL=https://%s:8443\n' "$COLLECTOR_IP" >> lab.env
  for SENSOR in a b; do
    sudo tee "/etc/systemd/system/field-sensor-$SENSOR.service" >/dev/null <<EOF
[Unit]
Description=Field lab simulated sensor ${SENSOR^^}
After=network-online.target
Wants=network-online.target
[Service]
User=azureuser
WorkingDirectory=$APP
EnvironmentFile=$APP/lab.env
ExecStart=/usr/bin/python3 -u $APP/agent.py --sensor SENSOR-${SENSOR^^} --db data/sensor-$SENSOR.db --url \${COLLECTOR_URL} --ca collector.crt
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
  done
  sudo tee /etc/systemd/system/field-backup.service >/dev/null <<EOF
[Unit]
Description=Field lab consistent sensor queue snapshots
After=local-fs.target
[Service]
Type=oneshot
User=azureuser
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 -u $APP/backup.py
UMask=0077
EOF
  sudo tee /etc/systemd/system/field-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Back up field sensor queues approximately every 30 seconds
[Timer]
OnBootSec=30
OnUnitActiveSec=30
AccuracySec=1
Unit=field-backup.service
[Install]
WantedBy=timers.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable field-sensor-a field-sensor-b
  sudo systemctl restart field-sensor-a field-sensor-b
  echo 'Sensors started. After mounting the backup disk, enable field-backup.timer as explained in the guide.'
fi
echo 'Services installed. Inspect them with systemctl and journalctl.'
