#!/usr/bin/env bash
# Exercise installer/update-binary the way TWRP does, against a throwaway ext4
# image mounted at /system. Needs root and loop devices; run it in a container
# or VM, never on a machine that has a real /system.
#
#   sudo tools/test_installer.sh out /tmp/inavi-test
#
# Cases: no writable /data, a stock-replacing package without /data, a zip path
# containing spaces, and the full core -> systemui -> uninstall cycle.
set -u

OUT=${1:?usage: test_installer.sh <out dir with the zips> <scratch dir>}
WORK=${2:?usage: test_installer.sh <out dir with the zips> <scratch dir>}
CORE=$OUT/INAVI_X3_N916S-core.zip
SYSUI=$OUT/INAVI_X3_N916S-systemui-EXPERIMENTAL.zip
UNINST=$OUT/INAVI_X3_N916S-uninstall.zip
IMG=$WORK/system.img
fail=0

for z in "$CORE" "$SYSUI" "$UNINST"; do
  [ -f "$z" ] || { echo "missing $z"; exit 1; }
done

reset_system() {
  mountpoint -q /system && umount /system
  rm -f "$IMG"; mkdir -p "$WORK" /system
  dd if=/dev/zero of="$IMG" bs=1M count=420 status=none
  mkfs.ext4 -q -F "$IMG"
  mount -o loop "$IMG" /system
  # a plausible stock SM-N916S 6.0.1 build.prop
  cat >/system/build.prop <<'EOF'
ro.build.version.sdk=23
ro.build.version.release=6.0.1
ro.product.model=SM-N916S
ro.product.device=trelteskt
ro.product.cpu.abi=armeabi-v7a
ro.product.cpu.abilist=armeabi-v7a,armeabi
EOF
  mkdir -p /system/priv-app/SystemUI /system/priv-app/SecSettings /system/app \
           /system/vendor/lib /system/etc/permissions /system/vendor/framework
  echo "STOCK-SAMSUNG-SYSTEMUI" >/system/priv-app/SystemUI/SystemUI.apk
  echo "STOCK-SAMSUNG-SETTINGS" >/system/priv-app/SecSettings/SecSettings.apk
  echo "<permissions/>" >/system/etc/permissions/platform.xml
}

# exactly what TWRP does: pull update-binary out of the zip and exec it
run() {
  rm -rf /tmp/inavix3 /tmp/ub
  unzip -p "$1" META-INF/com/google/android/update-binary >/tmp/ub
  chmod +x /tmp/ub
  sh /tmp/ub 3 1 "$1" 2>&1 | sed 's/^ui_print //;/^$/d'
}
remount() { mountpoint -q /system || mount -o loop "$IMG" /system; }
check() { # check <label> <expected> <actual>
  if [ "$2" = "$3" ]; then echo "  PASS  $1"; else
    echo "  FAIL  $1: expected [$2], got [$3]"; fail=$((fail + 1)); fi
}

echo "== A) core with no writable /data: installs, leaves no ramdisk backup"
reset_system; rm -rf /data /sdcard /external_sd /usb-otg
out=$(run "$CORE"); remount
check "앱 설치됨" 14 "$(ls /system/app 2>/dev/null | wc -l)"
check "런처 설치됨" 1 "$(ls /system/priv-app/IvyLauncher 2>/dev/null | wc -l)"
check "백업 없음 경고" 1 "$(printf '%s' "$out" | grep -c '백업을 남기지 못')"
check "/data 생성 안 함" 0 "$([ -d /data ] && echo 1 || echo 0)"

echo "== B) stock-replacing package with no writable /data: must abort untouched"
reset_system; rm -rf /data /sdcard /external_sd /usb-otg
out=$(run "$SYSUI"); remount
check "중단함" 1 "$(printf '%s' "$out" | grep -c '### 중단')"
check "순정 SystemUI 보존" "STOCK-SAMSUNG-SYSTEMUI" "$(cat /system/priv-app/SystemUI/SystemUI.apk)"
check "X3 SystemUI 설치 안 됨" 0 "$([ -e /system/priv-app/NaviSystemUI ] && echo 1 || echo 0)"

echo "== C) zip path containing spaces"
reset_system; mkdir -p /data/media/0
cp "$CORE" "/data/media/0/inavi x3 core.zip"
run "/data/media/0/inavi x3 core.zip" >/dev/null; remount
check "앱 설치됨" 14 "$(ls /system/app 2>/dev/null | wc -l)"

echo "== D) full cycle: core -> systemui -> uninstall -> stock restored"
reset_system; mkdir -p /data/media/0; touch /data/media/0/INAVI_X3_I_UNDERSTAND
run "$CORE" >/dev/null; remount; sleep 1
out=$(run "$SYSUI"); remount
check "순정 SystemUI 치움" 1 "$(printf '%s' "$out" | grep -c '순정 제거: /priv-app/SystemUI')"
check "순정 설정 치움" 1 "$(printf '%s' "$out" | grep -c '순정 제거: /priv-app/SecSettings')"
run "$UNINST" >/dev/null; remount
check "순정 SystemUI 복원" "STOCK-SAMSUNG-SYSTEMUI" "$(cat /system/priv-app/SystemUI/SystemUI.apk 2>/dev/null)"
check "순정 설정 복원" "STOCK-SAMSUNG-SETTINGS" "$(cat /system/priv-app/SecSettings/SecSettings.apk 2>/dev/null)"
check "아이나비 잔류 0" 0 "$(find /system \( -iname '*inavi*' -o -iname '*lib-tas*' -o -iname 'Ivy*' \) | wc -l)"
check "/system/app 비움" 0 "$(ls /system/app 2>/dev/null | wc -l)"
check "순정 platform.xml 무변경" "<permissions/>" "$(cat /system/etc/permissions/platform.xml)"

umount /system 2>/dev/null
echo
if [ "$fail" = "0" ]; then echo "모든 검사 통과"; else echo "실패 $fail 건"; fi
exit $fail
