#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-}"
SECONDS_DOWN="${2:-60}"
[[ "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && "$SECONDS_DOWN" =~ ^[0-9]+$ ]] || { echo 'Usage: bash outage.sh COLLECTOR_PRIVATE_IP SECONDS'; exit 1; }
sudo -v
cleanup(){ sudo iptables -D OUTPUT -p tcp -d "$TARGET" --dport 8443 -m comment --comment field-lab-outage -j DROP || true; }
sudo iptables -I OUTPUT 1 -p tcp -d "$TARGET" --dport 8443 -m comment --comment field-lab-outage -j DROP
trap cleanup EXIT
trap 'exit 130' INT TERM
echo "Blocking collector telemetry for $SECONDS_DOWN seconds. SSH remains available. Keep this terminal open."
sleep "$SECONDS_DOWN"
echo 'Restoring telemetry connection.'
