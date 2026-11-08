#!/usr/bin/env bash
# Unpack an iNavi X3 block-OTA zip (system.new.dat / vendor.new.dat) and mount
# the resulting ext4 images read-only.
#
#   sudo tools/extract_firmware.sh INAVI_X3_OS_DAV_UIJ07.zip /tmp/x3
#
# Afterwards /tmp/x3/mnt holds system/ and vendor/, which is what
# tools/build_package.py --firmware expects.
set -euo pipefail

ZIP=${1:?usage: extract_firmware.sh <firmware.zip> <workdir>}
WORK=${2:?usage: extract_firmware.sh <firmware.zip> <workdir>}
HERE=$(cd "$(dirname "$0")" && pwd)

mkdir -p "$WORK"/{raw,img,mnt/system,mnt/vendor}

echo ">> zip 전개"
unzip -o -q "$ZIP" \
  system.transfer.list system.new.dat \
  vendor.transfer.list vendor.new.dat \
  boot.img file_contexts \
  'META-INF/com/google/android/updater-script' \
  -d "$WORK/raw"

echo ">> sparse dat -> ext4"
python3 "$HERE/sdat2img.py" "$WORK/raw/system.transfer.list" \
  "$WORK/raw/system.new.dat" "$WORK/img/system.img"
python3 "$HERE/sdat2img.py" "$WORK/raw/vendor.transfer.list" \
  "$WORK/raw/vendor.new.dat" "$WORK/img/vendor.img"

echo ">> 마운트 (읽기 전용)"
mountpoint -q "$WORK/mnt/system" || mount -o ro,loop "$WORK/img/system.img" "$WORK/mnt/system"
mountpoint -q "$WORK/mnt/vendor" || mount -o ro,loop "$WORK/img/vendor.img" "$WORK/mnt/vendor"

echo
echo "준비 완료:"
echo "  $WORK/mnt/system"
echo "  $WORK/mnt/vendor"
sed -n '1,3p' "$WORK/raw/META-INF/com/google/android/updater-script" 2>/dev/null || true
