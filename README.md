# 아이나비 X3 → SM-N916S 이식

아이나비 X3(THINKWARE `serpiero`, 안드로이드 6.0.1) 펌웨어를 분석해, 갤럭시
노트4 S-LTE(SM-N916S)에 TWRP로 플래시할 수 있는 패키지를 만듭니다.

## 먼저 알아야 할 것

**X3 펌웨어를 통째로 N916S에 올리는 것은 불가능합니다.** zip 안의
`bootloader.bin`/`bl2.bin`/`micom_update.hex` 는 X3 기판 전용이라 쓰면 영구
벽돌이고, X3의 `/system/lib/hw` 에는 `camera.serpiero.so`,
`hwcomposer.exynos5.so` 같은 **serpiero 전용 HAL만** 있어 N916S에서는 화면조차
켜지지 않습니다. 또 `framework-res.apk` 와 주요 앱이 THINKWARE 플랫폼 키로
서명돼 있어, 삼성 키로 서명된 순정 ROM에서는 `android.uid.system` 앱이 거부
됩니다. 근거는 [`docs/PORTING.md`](docs/PORTING.md) 2장에 전부 정리했습니다.

그래서 **실제로 플래시해서 쓸 수 있는 최대치**를 만들었습니다. 커널·부트로더·
HAL·모뎀은 건드리지 않으므로 기기가 못 켜지는 일은 없습니다.

## 결과물 (`out/`)

| 파일 | 내용 |
|---|---|
| `INAVI_X3_N916S-core.zip` (22 MB) | X3 런처 + 아이나비 키보드·TPEG·설치관리자 등 12종 + `lib-tas` 공유 라이브러리. **순정 파일을 덮어쓰지 않고 추가만 합니다.** |
| `INAVI_X3_N916S-systemui-EXPERIMENTAL.zip` (4 MB) | X3 상태바·설정 교체. 삼성 순정에서는 실패 확률이 매우 높아 동의 파일을 요구합니다. |
| `INAVI_X3_N916S-uninstall.zip` | 설치 파일 제거 + 백업에서 순정 복원 |

설치 전 TWRP **Backup** 을 반드시 먼저 하세요. 첫 부팅은 dex2oat 때문에
5~15분 걸립니다.

## 내비게이션 본체

받은 zip은 OS 이미지라서 **아이나비 내비게이션 본체와 지도가 없습니다.**
`/vendor/app` 의 `Dummy3DS`·`DummyTBT` 는 dex가 1.7 KB인 빈 껍데기이고, 실제
본체는 `com.thinkware.sundo.inavi3d` 로 `/sx` 파티션이나 별도 패키지에서
설치됩니다. 본체 apk를 주시면 `--navi-apk` 옵션으로 패키지에 넣어 드립니다.

## 저장소 구성

```
out/                최종 TWRP 플래시 zip 3종
installer/          TWRP 셸 설치 스크립트 (설치/제거 공용)
tools/              전개·분석·리패킹·검증 도구
deodexed/           odex를 합친 X3 시스템 앱 (별도 압축본: inavi-x3-deodexed.zip)
docs/PORTING.md     전체 분석 결과, 불가능한 이유, 설치/복구, 재현 절차
```

재현 절차와 도구 설명은 [`docs/PORTING.md`](docs/PORTING.md) 8장을 보세요.

## deodex 정보

- 원본 odex: 안드로이드 6.0 ART (OAT 064). 내장 dex의 quick 명령어
  (`invoke-virtual-quick`, `iget/iput-*-quick`, `return-void-no-barrier`)를
  `boot.oat` 기준으로 원래 명령어로 복원했습니다.
- `tools/dexcheck.py` 로 14개 apk 전부 ART 전용 명령어 잔류 0을 확인했습니다.
- 수정이 필요한 apk는 `tools/repack_apk.py` 가 매니페스트 패치 → 4바이트 정렬
  → v1 재서명 → 서명이 모든 엔트리를 덮는지 전수 검증까지 수행합니다.
