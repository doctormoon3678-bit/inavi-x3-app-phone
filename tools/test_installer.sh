#!/usr/bin/env bash
# Exercise installer/update-binary the way TWRP does, against a throwaway ext4
# image mounted at /system. Needs root and loop devices; run it in a container
# or VM, never on a machine that has a real /system.
#
#   sudo tools/test_installer.sh out /tmp/inavi-test
#
# Covers: the SDK gate in both directions, an unwritable /data for both package
# kinds, a zip path containing spaces, the Android 4.4 flat layout, and the full
# core -> systemui -> uninstall cycle on Android 6.
set -u

OUT=${1:?usage: test_installer.sh <out dir with the zips> <scratch dir>}
WORK=${2:?usage: test_installer.sh <out dir with the zips> <scratch dir>}
CORE6=$OUT/INAVI_X3-core-android6.zip
CORE4=$OUT/INAVI_X3-core-android4.4.zip
SYSUI=$OUT/INAVI_X3-systemui-android6-EXPERIMENTAL.zip
UNINST=$OUT/INAVI_X3-uninstall.zip
IMG=$WORK/system.img
fail=0

for z in "$CORE6" "$CORE4" "$SYSUI" "$UNINST"; do
  [ -f "$z" ] || { echo "missing $z"; exit 1; }
done

# reset_system <sdk> <release> <model> <device>
reset_system() {
  mountpoint -q /system && umount /system
  rm -f "$IMG"; mkdir -p "$WORK" /system
  dd if=/dev/zero of="$IMG" bs=1M count=420 status=none
  mkfs.ext4 -q -F "$IMG"
  mount -o loop "$IMG" /system
  cat >/system/build.prop <<EOF
ro.build.version.sdk=$1
ro.build.version.release=$2
ro.product.model=$3
ro.product.device=$4
ro.product.cpu.abi=armeabi-v7a
ro.product.cpu.abilist=armeabi-v7a,armeabi
EOF
  mkdir -p /system/priv-app/SystemUI /system/priv-app/SecSettings /system/app \
           /system/lib /system/framework /system/vendor/lib \
           /system/etc/permissions /system/vendor/framework
  echo "STOCK-SAMSUNG-SYSTEMUI" >/system/priv-app/SystemUI/SystemUI.apk
  echo "STOCK-SAMSUNG-SETTINGS" >/system/priv-app/SecSettings/SecSettings.apk
  echo "<permissions/>" >/system/etc/permissions/platform.xml
}
marshmallow() { reset_system 23 6.0.1 SM-N916S trelteskt; }
kitkat()      { reset_system 19 4.4.4 SM-N910K treltektt; }

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

echo "== 1) SDK gate: the Android 6 package must refuse a 4.4.4 device"
kitkat; mkdir -p /data/media/0
out=$(run "$CORE6"); remount
check "중단함" 1 "$(printf '%s' "$out" | grep -c '### 중단')"
check "아무것도 설치 안 함" 0 "$(ls /system/app 2>/dev/null | wc -l)"

echo "== 2) SDK gate: the Android 4.4 package must refuse a 6.0.1 device"
marshmallow; mkdir -p /data/media/0
out=$(run "$CORE4"); remount
check "중단함" 1 "$(printf '%s' "$out" | grep -c '### 중단')"
check "아무것도 설치 안 함" 0 "$(ls /system/app 2>/dev/null | wc -l)"

echo "== 3) Android 4.4: flat layout, JNI in /system/lib"
kitkat; mkdir -p /data/media/0
run "$CORE4" >/dev/null; remount
check "평면 apk 13개" 13 "$(ls /system/app/*.apk 2>/dev/null | wc -l)"
check "하위 디렉터리 없음" 0 "$(find /system/app -mindepth 1 -type d | wc -l)"
check "런처 평면 배치" 1 "$([ -f /system/priv-app/IvyLauncher.apk ] && echo 1 || echo 0)"
check "JNI in /system/lib" 1 "$([ -f /system/lib/libUartReaderJni.so ] && echo 1 || echo 0)"
check "lib-tas in /system/framework" 1 "$([ -f /system/framework/lib-tas.jar ] && echo 1 || echo 0)"
check "lib-tas 선언 경로" 1 "$(grep -c '/system/framework/lib-tas.jar' /system/etc/permissions/inavi-lib-tas.xml)"
check "minSdk23 앱 제외" 0 "$([ -f /system/app/DummyHappywayard.apk ] && echo 1 || echo 0)"

echo "== 4) Android 6: cluster layout"
marshmallow; mkdir -p /data/media/0
run "$CORE6" >/dev/null; remount
check "앱 디렉터리 14개" 14 "$(find /system/app -mindepth 1 -maxdepth 1 -type d | wc -l)"
check "평면 apk 없음" 0 "$(ls /system/app/*.apk 2>/dev/null | wc -l)"
check "JNI in app lib/arm" 1 "$([ -f /system/app/DriveX/lib/arm/libUartReaderJni.so ] && echo 1 || echo 0)"
check "lib-tas in vendor" 1 "$([ -f /system/vendor/framework/lib-tas.jar ] && echo 1 || echo 0)"

echo "== 5) core with no writable /data: installs, leaves no ramdisk backup"
marshmallow; rm -rf /data /sdcard /external_sd /usb-otg
out=$(run "$CORE6"); remount
check "앱 설치됨" 14 "$(find /system/app -mindepth 1 -maxdepth 1 -type d | wc -l)"
check "백업 없음 경고" 1 "$(printf '%s' "$out" | grep -c '백업을 남기지 못')"
check "/data 생성 안 함" 0 "$([ -d /data ] && echo 1 || echo 0)"

echo "== 6) stock-replacing package with no writable /data: abort untouched"
marshmallow; rm -rf /data /sdcard /external_sd /usb-otg
out=$(run "$SYSUI"); remount
check "중단함" 1 "$(printf '%s' "$out" | grep -c '### 중단')"
check "순정 SystemUI 보존" "STOCK-SAMSUNG-SYSTEMUI" "$(cat /system/priv-app/SystemUI/SystemUI.apk)"

echo "== 7) zip path containing spaces"
marshmallow; mkdir -p /data/media/0
cp "$CORE6" "/data/media/0/inavi x3 core.zip"
run "/data/media/0/inavi x3 core.zip" >/dev/null; remount
check "앱 설치됨" 14 "$(find /system/app -mindepth 1 -maxdepth 1 -type d | wc -l)"

echo "== 8) full cycle: core -> systemui -> uninstall -> stock restored"
marshmallow; mkdir -p /data/media/0; touch /data/media/0/INAVI_X3_I_UNDERSTAND
run "$CORE6" >/dev/null; remount; sleep 1
out=$(run "$SYSUI"); remount
check "순정 SystemUI 치움" 1 "$(printf '%s' "$out" | grep -c '순정 제거: /priv-app/SystemUI')"
check "순정 설정 치움" 1 "$(printf '%s' "$out" | grep -c '순정 제거: /priv-app/SecSettings')"
run "$UNINST" >/dev/null; remount
check "순정 SystemUI 복원" "STOCK-SAMSUNG-SYSTEMUI" "$(cat /system/priv-app/SystemUI/SystemUI.apk 2>/dev/null)"
check "순정 설정 복원" "STOCK-SAMSUNG-SETTINGS" "$(cat /system/priv-app/SecSettings/SecSettings.apk 2>/dev/null)"
check "아이나비 잔류 0" 0 "$(find /system \( -iname '*inavi*' -o -iname '*lib-tas*' -o -iname 'Ivy*' \) | wc -l)"
check "순정 platform.xml 무변경" "<permissions/>" "$(cat /system/etc/permissions/platform.xml)"

echo "== 9) uninstall also cleans up the Android 4.4 flat layout"
kitkat; mkdir -p /data/media/0
run "$CORE4" >/dev/null; remount
run "$UNINST" >/dev/null; remount
check "평면 apk 잔류 0" 0 "$(ls /system/app/*.apk 2>/dev/null | wc -l)"
check "JNI 잔류 0" 0 "$(ls /system/lib/libUartReaderJni.so /system/lib/libEMSTPEG*.so 2>/dev/null | wc -l)"
check "lib-tas 잔류 0" 0 "$([ -f /system/framework/lib-tas.jar ] && echo 1 || echo 0)"
check "런처 잔류 0" 0 "$([ -f /system/priv-app/IvyLauncher.apk ] && echo 1 || echo 0)"

umount /system 2>/dev/null
echo
if [ "$fail" = "0" ]; then echo "모든 검사 통과"; else echo "실패 $fail 건"; fi
exit $fail
