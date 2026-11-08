# 아이나비 X3 → SM-N916S 이식 분석 및 결과

원본: `INAVI_X3_OS_DAV_UIJ07.zip` (247 MB, sha256 `52420793e87cba33d579c5bda80b6178eeeb26f1e3233898f845c2aa4cb612d0`)

---

## 1. 원본 zip 구조

표준 안드로이드 블록 OTA 패키지입니다.

| 항목 | 내용 |
|---|---|
| `system.new.dat` + `system.transfer.list` | /system 이미지 (전개 시 450 MB ext4) |
| `vendor.new.dat` + `vendor.transfer.list` | /vendor 이미지 (200 MB ext4) |
| `boot.img` | 커널 5.1 MB + 램디스크 1.0 MB |
| `bootloader.bin`, `bl2.bin` | 부트로더 — `mmcblk0boot0` 에 `dd` |
| `micom_update.hex` | 보조 마이크로컨트롤러 펌웨어 |

`updater-script` 가 밝히는 대상 기기:

```
getprop("ro.product.device") == "serpiero" || abort(...)
Target: INAVI/full_serpiero/serpiero:6.0.1/MXB48T/DAV.UIJ07:user/release-keys
```

`build.prop` 핵심:

```
ro.build.version.sdk=23            ro.build.version.release=6.0.1
ro.product.device=serpiero         ro.product.model=daVinci
ro.product.manufacturer=THINKWARE SYSTEM CORPORATION
ro.product.cpu.abi=armeabi-v7a     ro.product.cpu.abilist64=   (64비트 없음)
ro.board.platform=exynos5          dalvik.vm.isa.arm.variant=cortex-a15
ro.sf.lcd_density=160
```

**좋은 소식**: 안드로이드 버전(6.0.1 / SDK 23)과 ABI(armeabi-v7a 32비트)가
N916S 최종 순정과 일치합니다. 앱·프레임워크 레벨의 호환성은 확보됩니다.

---

## 2. 펌웨어 전체를 N916S에 플래시할 수 없는 이유

결론부터: **이 zip 을 그대로 N916S에 올리면 부팅하지 못하고, 일부 항목은
영구 벽돌을 만듭니다.** 추측이 아니라 이미지 안에서 확인한 사실입니다.

### 2-1. 부트로더·마이콤 — 벽돌 위험

원본 `updater-script` 가 하는 일:

```
run_program("/system/bin/sh","-c","echo 0 > /sys/block/mmcblk0boot0/force_ro");
dd if=/tmp/bl2.bin        of=/dev/block/mmcblk0boot0 bs=512 seek=30
dd if=/tmp/bootloader.bin of=/dev/block/mmcblk0boot0 bs=512 seek=62
run_program("/system/bin/micom_updater","/tmp/micom_update.hex","027")
```

- `mmcblk0boot0` 의 특정 섹터에 X3 전용 부트로더를 직접 씁니다. N916S는 eMMC
  파티션 구성과 부트 체인이 전혀 다르고, 삼성 부트로더는 서명 검증을 하므로
  이 바이너리는 애초에 실행되지 않습니다. 강제로 쓰면 복구 불가입니다.
- `micom_update.hex` 는 X3 기판의 보조 MCU 펌웨어입니다. N916S에는 그 MCU가
  없습니다.
- 파티션 번호도 다릅니다 (X3: system=`mmcblk0p1`, vendor=`mmcblk0p10`,
  boot=`mmcblk0p5`).

→ **이 네 항목(`bootloader.bin`, `bl2.bin`, `micom_update.hex`, `boot.img`)은
어떤 경우에도 N916S에 쓰지 않습니다.**

### 2-2. HAL — X3 /system 은 N916S 하드웨어를 모릅니다

`/system/lib/hw` 실제 내용:

```
camera.serpiero.so        lights.serpiero.so      audio.primary.serpiero.so
gralloc.exynos5.so        hwcomposer.exynos5.so   memtrack.exynos5.so
gps.default.so  gps.mi.so  bluetooth.default.so   power.default.so
```

그리고 `/system/lib/libreference-ril.so` — **AOSP 레퍼런스 RIL**, 즉 실제
모뎀 드라이버가 없습니다.

N916S가 부팅하려면 Exynos 5433 + 그 커널에 맞는 `gralloc`/`hwcomposer`,
섀넌 모뎀용 `libsec-ril.so`, 센서허브 HAL, `camera.vendor.universal5433.so`,
`lights.trelte.so` 가 필요합니다. X3 이미지에는 하나도 없습니다.

`hwcomposer`/`gralloc` 은 커널의 디스플레이 드라이버와 ioctl 단위로 짝이
맞아야 합니다. 커널(X3 boot.img)을 가져올 수도 없으니(2-1) **화면 자체가
켜지지 않습니다.**

### 2-3. 반대 방향도 막힙니다

"삼성 커널 + X3 /system" 조합도 성립하지 않습니다. 삼성 순정 6.0.1의 HAL과
RIL 블롭은 삼성이 수정한 프레임워크 심볼에 링크되어 있고, boot.img 램디스크의
init.rc·SELinux 정책은 삼성 /system 레이아웃을 전제합니다. X3의 /system은
순수 AOSP 프레임워크(아래 2-4)라서 서비스 이름·경로·컨텍스트가 어긋납니다.

### 2-4. 서명 — 플랫폼 키가 다릅니다

APK들의 실제 X.509 인증서를 PKCS#7에서 추출해 묶어보면:

| 인증서 | 주체 | 개수 |
|---|---|---|
| `3588a067f5e3f575` | `O=THINKWARE, OU=DEVICE, CN=nobody` | **52개 (framework-res.apk 포함)** |
| `9d62afe7d82f0429` | 같은 주체(별 키) | 13개 |
| 기타 | media/contacts 계열, HWS, AOSP testkey | 6개 |

즉 `framework-res.apk`(= `android` 패키지 = 플랫폼 키)와 IvyLauncher,
NaviSystemUI, NaviSettings, NIPservice, tascommonservice 등이 **같은 THINKWARE
플랫폼 키**로 서명돼 있습니다.

N916S의 플랫폼 키는 삼성 것입니다. 따라서 `sharedUserId="android.uid.system"`
을 선언한 X3 앱은 순정 ROM에서 **서명 불일치로 PackageManager가 거부**합니다.
삼성 플랫폼 개인키는 공개되지 않으므로 우회할 수 없습니다.

### 2-5. 내비게이션 본체가 zip에 없습니다

가장 중요한 부분입니다. 이 zip은 이름대로 `OS` 이미지이고, 실제 아이나비
내비게이션은 들어있지 않습니다.

`/vendor/app` 의 `Dummy*` 들은 자리표시용 빈 껍데기입니다:

```
Dummy3DS.apk          36 KB   classes.dex 1,728 바이트, 메서드 6개
DummyTBT.apk          34 KB   동일
DummyTCONMW.apk       34 KB   DummyHappywayard.apk 14 KB
```

IvyLauncher의 dex 문자열에서 실제 대상 패키지가 드러납니다:

```
com.thinkware.sundo.inavi3d                 <- 진짜 3D 내비게이션
com.thinkware.sundo.inavi3d.action.start_initialization
com.thinkware.ivy.launcher.inavi.install
com.thinkware.dixon.installmanager          <- 본체를 설치하는 관리자
```

본체와 지도 데이터는 `/sx` 파티션(`mmcblk0p20`)이나 별도 업데이트 패키지에서
`installmanager` 가 설치합니다. 따라서 **이 zip만으로는 내비가 뜨지 않습니다.**

### 2-6. 그 외

- 해상도/DPI: X3 `ro.sf.lcd_density=160`, N916S는 QHD 2560×1440 / 640dpi.
  X3 UI는 N916S에서 매우 작게 그려집니다.
- X3 `/system/framework` 에 커스텀 jar은 없습니다 — 순수 AOSP 6.0.1입니다.
  (`framework.jar`, `services.jar` 모두 AOSP) 이식에는 오히려 유리한 점입니다.
- `/vendor/framework/lib-tas.jar` (108 KB, `tas.camera.*`, `tas.internal.avm.*`)
  가 공유 라이브러리로 선언되어 있고, 여러 아이나비 앱이 이를 필수로 요구합니다.

---

## 3. 그래서 만든 것

전체 ROM 플래시는 물리적으로 불가능하므로, **실제로 플래시해서 동작시킬 수 있는
최대치**를 TWRP 패키지로 만들었습니다. 커널·부트로더·HAL·모뎀은 손대지
않으므로 기기가 못 켜지는 일은 없습니다.

### `out/INAVI_X3_N916S-core.zip` (22 MB)

| 설치 위치 | 패키지 | 설명 |
|---|---|---|
| `priv-app/IvyLauncher` | `com.thinkware.ivy.launcher` 1.3 | **X3 런처** (deodex + `sharedUserId` 제거 + 재서명) |
| `app/InaviMatrixKeyboard` | `com.thinkware.dixon.keyboard` | 아이나비 천지인 키보드 |
| `app/InaviQwerty` | `com.thinkware.dixon.qwertykeyboard` | 아이나비 쿼티 키보드 |
| `app/InaviBrightness` | `com.inavi.settings.brightness` | 밝기 설정 |
| `app/ThinkwareSteward` | `com.thinkware.steward` 2.0.3 | TPEG 교통정보 (+JNI) |
| `app/DriveX` | `com.ubivelox.drivex` | 하이패스/OBD UART 리더 (+JNI) |
| `app/InaviInstallManager` | `com.thinkware.dixon.installmanager` | **내비 본체 설치 관리자** |
| `app/HudPnd` | `com.thinkware.hud_pnd` | HUD 연동 |
| `app/SdUnmount` | `com.tw.sdunmount` | SD 안전 제거 |
| `app/AudioController` | `com.thinkware.audiocontroller` | 오디오 컨트롤러 |
| `app/BSDService` | `com.thinkware.bsd` 1.5 | 사각지대 경보 |
| `app/Dummy3DS` 등 4개 | `com.thinkware.inavi3ds` 등 | 런처 타일이 참조하는 스텁 |
| `vendor/framework/lib-tas.jar` | `lib-tas` | THINKWARE 공유 라이브러리 |
| `etc/permissions/inavi-lib-tas.xml` | — | 위 라이브러리 선언 (순정 `platform.xml` 은 건드리지 않음) |
| `vendor/lib/libEMSTPEG{Parser,DataManager}.so` | — | Steward 의존 라이브러리 |

설계상의 안전장치:

- **순정 파일을 0개 덮어씁니다.** 추가만 합니다 (시뮬레이션으로 확인).
- 포함된 앱 중 `persistent=true` 이거나 `android.uid.system` 을 쓰는 것은
  **하나도 없습니다.** 최악의 경우에도 해당 앱만 강제종료되고 부팅은 됩니다.
- GPU/EGL/RenderScript/OpenCL/mediadrm 블롭은 **일부러 제외**했습니다.
  `libGLES_mali.so` 등을 덮으면 화면이 죽습니다.
- `/vendor/lib` 에서 가져온 것은 실제 DT_NEEDED 의존성 폐쇄만 계산해 2개뿐입니다.
- 시스템 앱의 JNI 라이브러리는 안드로이드가 자동 추출하지 않으므로
  apk 안의 `lib/armeabi*/*.so` 를 `app/<이름>/lib/arm/` 에 함께 배치했습니다.
- 모든 apk는 dex 바이트코드를 전수 검사해 ART 전용 명령어(`*-quick`,
  `return-void-no-barrier`)가 남아있지 않음을 확인했습니다.

### `out/INAVI_X3_N916S-systemui-EXPERIMENTAL.zip` (4 MB)

요청하신 NaviSystemUI·NaviSettings 교체본입니다. **위험합니다.**

- 패키지명이 `com.android.systemui` / `com.android.settings` 라서 순정과
  충돌합니다. 설치 시 순정 `SystemUI`/`SecSettings` 를 백업 후 제거합니다.
- X3의 AOSP `framework-res` 리소스 ID를 참조하는데 삼성 프레임워크의 ID는
  전혀 다릅니다. **상태바가 안 뜨거나 설정이 계속 죽을 확률이 매우 높습니다.**
- 그래서 설치하려면 내장메모리 최상위에 빈 파일
  `INAVI_X3_I_UNDERSTAND` 를 직접 만들어야 합니다 (실수 방지).
- 문제가 생기면 제거 zip으로 되돌립니다.

### `out/INAVI_X3_N916S-uninstall.zip`

설치한 파일 전부를 지우고, 이 설치 프로그램이 만든 백업을 **오래된 것부터
순서대로** 복원합니다.

---

## 4. 설치 방법

1. TWRP 진입 → **Backup** 으로 현재 상태 전체 백업 (필수).
2. `INAVI_X3_N916S-core.zip` 플래시.
   - `Mount` 에서 *system partition read-only* 가 꺼져 있어야 합니다.
3. 재부팅. **첫 부팅은 dex2oat 때문에 5~15분** 걸립니다.
4. 홈 버튼 → 런처 선택창에서 **아이나비 런처** 선택.
5. 설정 → 언어 및 입력 → 아이나비 키보드 활성화 (원하면).

설치 프로그램이 하는 사전 점검:

- `/system` 쓰기 가능 여부 (안 되면 안내 후 중단)
- `ro.build.version.sdk == 23`
- ABI에 `armeabi-v7a` 포함
- `/system` 여유 공간

되돌리기: `INAVI_X3_N916S-uninstall.zip` 플래시, 또는 TWRP 터미널에서
`sh /data/media/0/INAVI_X3_backup_*/restore.sh`.

---

## 5. 작동 예상

| | 상태 |
|---|---|
| 아이나비 런처 (홈) | 뜰 가능성 높음. 단 `DEVICE_POWER` 등 서명 전용 권한은 못 받으므로 재부팅·전원 관련 타일은 실패 |
| 아이나비 키보드 2종 | 정상 동작 예상 |
| 밝기 설정 / HUD / SD 제거 | 설치는 됨, 기기 전용 노드가 없어 기능은 제한적 |
| TPEG(Steward) | 내비 본체가 있어야 의미 있음 |
| DriveX, BSDService | 전용 UART·카메라 하드웨어가 없어 동작 불가 (설치만) |
| 내비게이션 본체 | **zip에 없음** — 아래 6번 |
| NaviSystemUI / NaviSettings | 삼성 순정에서는 거의 확실히 실패 (실험용) |
| DPI | X3는 160dpi 기준 → N916S에서 UI가 작게 보입니다. `/system/build.prop` 수정 없이 개발자 옵션의 최소 폭(dp) 조정으로 맞추는 편이 안전합니다 |

---

## 6. 내비게이션 본체 넣기

본체 패키지를 갖고 계시다고 하셨으니, apk를 주시면 같은 zip에 넣어
드립니다. 빌더에 옵션이 준비돼 있습니다:

```bash
python3 tools/build_package.py --firmware <X3 mnt> --out out --work /tmp/w \
    --keystore <키스토어> \
    --navi-apk /path/to/inavi3d.apk --navi-apk /path/to/<추가>.apk
```

- 본체 apk의 패키지명이 스텁과 같으면(`com.thinkware.inavi3ds` 등) 스텁을
  자동으로 대체합니다.
- 본체가 `sharedUserId="android.uid.system"` 을 선언하면 순정 ROM에서는
  설치가 거부됩니다. 빌더가 그 경우 경고를 출력합니다.
- **지도 데이터는 zip에 넣지 않습니다** (수 GB). 내장메모리/SD에 두고
  `InaviInstallManager` 로 설치하는 쪽이 맞습니다.

X3 실기에서 직접 뽑으려면: 기기의 `/sx` 파티션(`mmcblk0p20`) 또는 아이나비
업데이트용 SD카드의 설치 패키지를 확보하면 됩니다.

---

## 7. 진짜 "X3 ROM" 에 가장 가까이 가는 길

삼성 순정 위에서는 서명과 리소스 ID 때문에 런처 레벨이 한계입니다. 한 단계
위를 원하시면 **베이스를 바꾸는 쪽**이 정공법입니다.

X3의 `/system/framework` 가 순수 AOSP 6.0.1이라는 점이 핵심입니다.
N916S(trelte 계열)에는 커뮤니티가 만든 **안드로이드 6.0.1 AOSP 기반 커스텀롬**
(CM13/LineageOS 13 계열)이 존재하고, 이쪽은:

- 커널과 Exynos 5433 HAL·RIL을 **N916S 것으로 유지**하면서
- 프레임워크 리소스가 **AOSP라서 X3 앱과 ID가 맞고**
- 보통 공개된 **AOSP test-keys 로 서명**되어 있어, 그 키로 X3 앱을 재서명하면
  `android.uid.system` 앱(NaviSettings 등)까지 진짜 플랫폼 서명으로 살릴 수
  있습니다.

이 경로를 원하시면, 쓰실 커스텀롬 zip을 주시면 그 롬의 플랫폼 키/리소스에
맞춰 다시 패키징해 드리겠습니다.

---

## 8. 재현 방법

```bash
# 1) 원본 zip 전개 + ext4 마운트 (root 필요)
sudo tools/extract_firmware.sh INAVI_X3_OS_DAV_UIJ07.zip /tmp/x3

# 2) odex 분리 (이미 deodexed/ 에 결과가 있음)
tools/build.sh
java -cp tools/build/out OatDeodex <앱.odex> <출력> /tmp/x3/mnt/system/framework/arm/boot.oat
python3 tools/merge_dex.py <원본.apk> <출력> <결과.apk>

# 3) 서명 키 생성
keytool -genkeypair -keystore inavi-port.jks -storepass inavix3 -keypass inavix3 \
  -alias inavi-port -keyalg RSA -keysize 2048 -validity 10950 \
  -dname "CN=INAVI X3 port for N916S, OU=port, O=community, C=KR"

# 4) 패키지 빌드
python3 tools/build_package.py --firmware /tmp/x3/mnt --out out --work /tmp/w \
  --keystore inavi-port.jks --alias inavi-port --storepass inavix3
```

보조 도구:

| 도구 | 용도 |
|---|---|
| `tools/sdat2img.py` | `*.new.dat` + transfer list → raw ext4 |
| `tools/axml.py` | 바이너리 AndroidManifest 읽기 (패키지/권한/라이브러리) |
| `tools/axmlpatch.py` | 바이너리 매니페스트에서 속성 제거 |
| `tools/repack_apk.py` | 리패킹 + 4바이트 정렬 + v1 재서명 + 서명 커버리지 검증 |
| `tools/dexcheck.py` | dex 전수 검사: ART 전용/미정의 명령어 탐지 |
| `tools/elfneeded.py` | `.so` 의 DT_NEEDED/SONAME 조회 |
| `tools/build_package.py` | TWRP zip 3종 생성 |
| `installer/update-binary` | TWRP 셸 설치 스크립트 (설치/제거 공용) |

### 검증 내역

- `dexcheck.py` 는 정상 dex에서 오탐 0, 합성 주입(`0xe9`) 탐지 성공으로
  유효성을 확인했고, deodex 결과 14개 apk 전부 통과했습니다.
- 수정하지 않은 14개 apk는 펌웨어 원본과 **sha256 바이트 동일**하며 v1 서명이
  모든 엔트리를 덮습니다.
- 재서명한 3개 apk는 `jarsigner -verify` 통과 + 자체 전수 다이제스트 검증 통과.
  (`jarsigner` 가 원본 apk를 `weak algorithm ... disabled` 로 거부하는 것은
  JDK 21 정책이며 안드로이드 6과 무관합니다.)
- `installer/update-binary` 는 420 MB ext4 이미지를 `/system` 에 마운트한
  가짜 SM-N916S 환경에서 **설치 → 순정 제거·백업 → 제거 → 순정 복원** 전체
  사이클을 실행해 확인했습니다. 권한 `644`/`755` `root:root`, JNI 배치,
  순정 `platform.xml` 무변경까지 확인했습니다.
