# Setup and reproduction reference

The complete [report](../reports/Remote_Device_Recorder_Lab_Report.pdf) includes the procedures, commands, screenshots and measured results. This reference describes the supplied starter setup using the actual lab address plan. Substitute your own stable host-only addresses where different.

## 1 Prepare two Ubuntu Server VMs

Use separate VirtualBox guests with OpenSSH enabled, about 2 GB RAM, 2 vCPUs and a 20 GB primary virtual disk each. Add a new empty 8 GB VDI only to the outdoor VM. Use Adapter 1 NAT for updates and Adapter 2 on the same host-only network for lab communication.

The supplied installers expect username `azureuser` and the guest directory `/home/azureuser/field-lab`. The username is retained for compatibility; this lab runs locally in VirtualBox.

Use `ip -br address` to identify addresses. This run used Windows `192.168.56.1`, outdoor `192.168.56.101`, and monitor `192.168.56.102`. Keep address allocation stable through reservations or a verified static configuration outside the active DHCP pool.

On both Ubuntu guests:

```bash
sudo apt-get update
sudo apt-get install -y python3 openssl curl iptables ufw util-linux e2fsprogs openssh-server
sudo systemctl enable --now ssh
mkdir -p ~/field-lab/data
```

From Windows PowerShell in the cloned repository:

```powershell
$OutdoorIP = '192.168.56.101'
$MonitorIP = '192.168.56.102'
scp .\scripts\*.py .\scripts\*.sh "azureuser@${OutdoorIP}:/home/azureuser/field-lab/"
scp .\scripts\*.py .\scripts\*.sh "azureuser@${MonitorIP}:/home/azureuser/field-lab/"
```

On both guests:

```bash
cd ~/field-lab
sed -i 's/\r$//' *.sh
python3 tests.py
```

## 2 Configure Linux firewall rules

On a fresh monitor VM, keeping the VirtualBox console available:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.56.1 to any port 22 proto tcp
sudo ufw allow from 192.168.56.101 to any port 8443 proto tcp
sudo ufw enable
sudo ufw status verbose
```

On the outdoor VM:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.56.1 to any port 22 proto tcp
sudo ufw enable
```

Inspect existing rules before enabling and verify new SSH sessions afterward. Use only these dedicated lab guests for configuration changes.

## 3 Configure authenticated HTTPS

On the monitor VM:

```bash
cd ~/field-lab
MONITOR_PRIVATE='192.168.56.102'
openssl req -x509 -newkey rsa:2048 -sha256 -days 30 -nodes \
  -keyout collector.key -out collector.crt \
  -subj '/CN=field-lab-monitor' \
  -addext "subjectAltName=IP:${MONITOR_PRIVATE}"
chmod 600 collector.key
openssl rand -hex 32 > token.txt
chmod 600 token.txt
bash install-services.sh collector
```

Transfer the public certificate and shared token through Windows; retain the private key on the monitor:

```powershell
scp "azureuser@${MonitorIP}:/home/azureuser/field-lab/collector.crt" .\collector.crt
scp "azureuser@${MonitorIP}:/home/azureuser/field-lab/token.txt" .\token.txt
scp .\collector.crt .\token.txt "azureuser@${OutdoorIP}:/home/azureuser/field-lab/"
```

After a successful transfer, delete only the temporary Windows token copy. Keep tokens, keys and environment files out of GitHub.

On the outdoor VM:

```bash
cd ~/field-lab
chmod 600 token.txt
bash install-services.sh outdoor
```

Enter `192.168.56.102` when prompted for collector private IPv4. Check services and logs:

```bash
systemctl is-active field-sensor-a field-sensor-b
sudo journalctl -u field-sensor-a -n 20 --no-pager
```

## 4 Open the dashboard

From Windows:

```powershell
ssh -N -L 8080:127.0.0.1:8080 azureuser@192.168.56.102
```

Keep the tunnel open and visit `http://localhost:8080`. Capture both sensors CURRENT before injecting faults.

## 5 Prepare and schedule backups

On the outdoor VM, inspect disks:

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
```

Match the new empty VDI against VirtualBox Storage settings. Formatting destroys the selected disk's contents. The following example is appropriate ONLY if `/dev/sdb` is the verified new empty backup VDI:

```bash
bash prepare-backup-disk.sh /dev/sdb
findmnt /mnt/field-backup
python3 backup.py
sudo systemctl enable --now field-backup.timer
ls -lh /mnt/field-backup/snapshots
```

The helper requires explicit confirmation and refuses existing filesystems. Snapshots retain three versions per sensor.

## 6 Exercise delivery and process recovery

Use one outdoor SSH terminal for the outage helper and a second for counters:

```bash
bash outage.sh 192.168.56.102 120
```

```bash
date -u
python3 agent.py --status --db data/sensor-a.db
python3 agent.py --status --db data/sensor-b.db
```

Capture pending counts during the outage, a STALE dashboard after about 30 seconds, and CURRENT status with drained queues after recovery. The helper restores its rule when its timer ends or when interrupted with Ctrl+C in that terminal.

For the sensor interruption exercise:

```bash
sudo systemctl stop field-sensor-a
# Observe A STALE while B continues
sudo systemctl start field-sensor-a
```

The report also records automatic restart following a forced process termination.

## 7 Restore a selected snapshot

While telemetry is blocked, stop both sensors and the backup timer, then create a stable snapshot:

```bash
sudo systemctl stop field-sensor-a field-sensor-b
sudo systemctl stop field-backup.timer field-backup.service
python3 backup.py
SNAPSHOT="$(find /mnt/field-backup/snapshots -maxdepth 1 -name 'sensor-a-*.sqlite' -printf '%f\n' | sort | tail -n 1)"
test -n "$SNAPSHOT"
cp "/mnt/field-backup/snapshots/$SNAPSHOT" recovery-evidence.sqlite
python3 agent.py --status --db recovery-evidence.sqlite
```

Confirm the selected snapshot has pending records. Preserve the primary file under an unused name, then restore:

```bash
test ! -e data/sensor-a.before-restore.db && mv data/sensor-a.db data/sensor-a.before-restore.db
python3 recover.py --snapshot recovery-evidence.sqlite --output data/sensor-a.db
sudo systemctl start field-sensor-a field-sensor-b
sudo systemctl start field-backup.timer
```

If the preservation name exists, choose a new name first. The restore utility refuses to overwrite an existing output file. Restore connectivity, allow the queue to drain, and transfer the selected snapshot to the monitor. There, run:

```bash
python3 verify_recovery.py --snapshot recovery-evidence.sqlite
```

This project's selected snapshot had four pending IDs, all found at the collector.

## 8 Save results

```bash
# Outdoor VM
sudo -v
python3 export_evidence.py outdoor
# Monitor VM
sudo -v
python3 export_evidence.py monitor
```

Download both export archives and open their contents on Windows before shutting down the guests. Exported logs, credentials and databases are excluded from the public repository; the report presents the reviewed results and selected screenshots.
