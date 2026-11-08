# 아이나비 X3 디오덱스(deodex) 앱

`deodexed/` 에 odex를 합친 apk가 있습니다 (`inavi-x3-deodexed.zip`은 같은 내용의 압축본).

- 대상: `app/` DocumentsUI, Email, Exchange2, Gallery2, IvyLauncher /
  `priv-app/` CalendarProvider, ContactsProvider, DownloadProvider, MediaProvider,
  NaviSettings, NaviSettingsProvider, NaviSystemUI, PackageInstaller, Telecom
- 원본 odex: Android 6.0 ART (OAT 064). 내장 dex의 quick 명령어(invoke-virtual-quick,
  iget/iput-*-quick, return-void-no-barrier)를 `boot.oat` 기준으로 원래 명령어로 복원.
- 기존 apk 항목과 서명(META-INF)은 그대로 두고 `classes.dex`만 추가 (재서명 없음).

## 설치
기기의 `/system/app/<앱>/`, `/system/priv-app/<앱>/` 에서 apk를 교체하고
`oat/` 폴더를 삭제한 뒤 재부팅. 첫 부팅 때 dex2oat가 다시 실행되어 오래 걸릴 수 있음.

## 다시 만들기
```
tools/build.sh   # baksmali/dexlib2 2.5.2 소스 빌드 + OatDeodex
java -cp tools/build/out OatDeodex <앱.odex> <출력폴더> <boot.oat>
python3 tools/merge_dex.py <원본.apk> <출력폴더> <결과.apk>
```
