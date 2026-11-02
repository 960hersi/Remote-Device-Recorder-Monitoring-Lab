#!/usr/bin/env bash
# Only for a newly created, EMPTY lab data disk. Never use on an existing disk.
set -euo pipefail
[[ "$(id -un)" == azureuser ]] || { echo 'Run as azureuser, not root.'; exit 1; }
DEVICE="${1:-}"
[[ -n "$DEVICE" && -b "$DEVICE" ]] || { echo 'Usage: bash prepare-backup-disk.sh /dev/PATH-TO-NEW-EMPTY-DATA-DISK'; exit 1; }
DEVICE="$(readlink -f "$DEVICE")"
[[ "$(lsblk -dn -o TYPE "$DEVICE")" == disk ]] || { echo 'Expected a whole disk'; exit 1; }
[[ "$(lsblk -nr -o TYPE "$DEVICE" | wc -l)" -eq 1 ]] || { echo 'Disk has child partitions; refusing.'; exit 1; }
[[ -z "$(lsblk -dn -o FSTYPE,MOUNTPOINTS "$DEVICE" | tr -d '[:space:]')" ]] || { echo 'Disk has a filesystem or mount; refusing.'; exit 1; }
[[ -z "$(sudo wipefs -n --noheadings -o TYPE "$DEVICE")" ]] || { echo 'Disk has signatures; refusing.'; exit 1; }
if mountpoint -q /mnt/field-backup || grep -q '/mnt/field-backup' /etc/fstab; then
  echo 'Backup mount is already configured; refusing to reformat.'; exit 1
fi
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS "$DEVICE"
echo 'Match this disk to the NEW empty virtual disk attached to outdoor-vm in VirtualBox.'
echo 'Formatting erases this disk. Never choose the OS disk, temporary disk, or an existing data disk.'
read -r -p 'Type ERASE-THIS-NEW-LAB-DISK to continue: ' CONFIRM
[[ "$CONFIRM" == ERASE-THIS-NEW-LAB-DISK ]] || { echo 'Cancelled'; exit 1; }
sudo mkfs.ext4 -L FIELD_BACKUP "$DEVICE"
sudo mkdir -p /mnt/field-backup
UUID="$(sudo blkid -s UUID -o value "$DEVICE")"
[[ -n "$UUID" ]] || { echo 'Could not identify filesystem UUID'; exit 1; }
sudo cp /etc/fstab /etc/fstab.before-field-lab
printf 'UUID=%s /mnt/field-backup ext4 defaults,nofail 0 2\n' "$UUID" | sudo tee -a /etc/fstab >/dev/null
sudo systemctl daemon-reload
sudo mount /mnt/field-backup
sudo chown azureuser:azureuser /mnt/field-backup
mkdir -p /mnt/field-backup/snapshots
chmod 700 /mnt/field-backup/snapshots
findmnt /mnt/field-backup
echo 'Backup disk is ready. This helper refuses to format it again.'
