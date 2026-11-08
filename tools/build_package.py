#!/usr/bin/env python3
"""Assemble the TWRP-flashable packages for the iNavi X3 -> SM-N916S port.

  build_package.py --firmware <mounted X3 root> --repo <repo root> --out <dir>

<mounted X3 root> holds `system/` and `vendor/` as produced by
tools/extract_firmware.sh.
"""
import argparse, os, shutil, stat, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repack_apk
from axml import describe

# ---------------------------------------------------------------------------
# apps that keep their original THINKWARE signature: none of them declares a
# sharedUserId, so a signature mismatch with the host ROM's platform key does
# not matter, and none is persistent or runs as the system uid -- the worst a
# broken one can do is crash itself.
VENDOR_APPS = [
    # (install dir name, source path under the firmware root, what it is)
    ('InaviMatrixKeyboard', 'vendor/app/inavi_matrix_keyboard/inavi_matrix_keyboard.apk',
     '아이나비 한글(천지인) 키보드'),
    ('InaviQwerty', 'vendor/app/qwerty/qwerty.apk', '아이나비 쿼티 키보드'),
    ('InaviBrightness', 'vendor/app/com.inavi.settings.brightness/com.inavi.settings.brightness.apk',
     '아이나비 밝기 설정'),
    ('ThinkwareSteward', 'vendor/app/com.thinkware.steward/com.thinkware.steward.apk',
     'TPEG 교통정보 수신 서비스'),
    ('DriveX', 'vendor/app/DriveX/DriveX.apk', '하이패스/OBD UART 리더 (전용 하드웨어 필요)'),
    ('InaviInstallManager', 'vendor/app/installmanager/installmanager.apk',
     '아이나비 내비 본체 설치 관리자'),
    ('HudPnd', 'vendor/app/hud_pnd/hud_pnd.apk', 'HUD 연동'),
    ('SdUnmount', 'vendor/app/com.tw.sdunmount/com.tw.sdunmount.apk', 'SD 안전 제거 도우미'),
    ('AudioController', 'vendor/app/com.thinkware.audiocontroller/com.thinkware.audiocontroller.apk',
     '오디오 컨트롤러 (lib-tas 필요)'),
    ('BSDService', 'vendor/app/BSDService/BSDService.apk',
     '사각지대 경보 서비스 (전용 카메라 필요)'),
    ('Dummy3DS', 'vendor/app/Dummy3DS/Dummy3DS.apk', '3D 내비 자리표시 스텁'),
    ('DummyTBT', 'vendor/app/DummyTBT/DummyTBT.apk', 'TBT 자리표시 스텁'),
    ('DummyTCONMW', 'vendor/app/DummyTCONMW/DummyTCONMW.apk', 'TCON 자리표시 스텁'),
    ('DummyHappywayard', 'vendor/app/DummyHappywayard/DummyHappywayard.apk', '해피웨이야드 스텁'),
]

# /vendor/lib members the shipped apps actually need (DT_NEEDED closure of the
# JNI libraries bundled inside those apks). Deliberately excludes every GPU,
# RenderScript, OpenCL, EGL and mediadrm blob: replacing those on the phone
# would take the display down.
VENDOR_LIBS = ['libEMSTPEGDataManager.so', 'libEMSTPEGParser.so']

LIB_TAS_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- Declares the THINKWARE shared library that the ported iNavi apps load with
     <uses-library android:name="lib-tas" />.  On the X3 this entry lives inside
     /system/etc/permissions/platform.xml; shipping it as its own file leaves the
     host ROM's platform.xml untouched. -->
<permissions>
    <library name="lib-tas"
            file="@JAR@" />
</permissions>
"""


# Where a system app's files go depends on the platform version:
#   Android 5.0+  "cluster" layout: /system/app/Foo/Foo.apk, libs in Foo/lib/arm/
#   Android 4.x   flat layout:      /system/app/Foo.apk,     libs in /system/lib/
# PackageManagerService on 4.4 only looks at *.apk files in /system/app and
# skips subdirectories outright, so a cluster-layout package installs nothing
# there -- it just silently does not appear.
LAYOUTS = {
    'android6': {
        'sdks': ['23'],
        'cluster': True,
        'libtas': 'vendor/framework/lib-tas.jar',
        'vendor_lib': 'vendor/lib',
        'label': '안드로이드 6.0.x (SDK 23)',
        'suffix': 'android6',
    },
    'android4': {
        'sdks': ['19'],
        'cluster': False,
        'libtas': 'framework/lib-tas.jar',
        'vendor_lib': 'lib',
        'label': '안드로이드 4.4.x (SDK 19)',
        'suffix': 'android4.4',
    },
}


def sh(*cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def extract_jni(apk, dest_dir):
    """Unpack an apk's bundled armeabi libraries into dest_dir.

    Android does not unpack native libraries for apps that live in /system, so a
    ported system app only finds its JNI code if the .so files are already in
    the directory the platform looks in: <app dir>/lib/arm on 5.0+, /system/lib
    on 4.x.
    """
    out = []
    with zipfile.ZipFile(apk) as z:
        members = [n for n in z.namelist() if n.endswith('.so') and n.startswith('lib/')]
        sel = []
        # prefer armeabi-v7a, fall back to armeabi
        for abi in ('armeabi-v7a', 'armeabi'):
            sel = [n for n in members if n.startswith(f'lib/{abi}/')]
            if sel:
                break
        for n in sel:
            target = os.path.join(dest_dir, os.path.basename(n))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'wb') as f:
                f.write(z.read(n))
            out.append(target)
    return out


def place_app(sysd, section, name, src_apk, layout, patch=None, ks=None,
              alias=None, pw=None):
    """Install one apk into the staged tree using the layout's conventions.

    Returns (installed apk path, list of extracted .so paths).
    """
    if layout['cluster']:
        app_dir = os.path.join(sysd, section, name)
        os.makedirs(app_dir, exist_ok=True)
        apk = os.path.join(app_dir, f'{name}.apk')
        jni_dir = os.path.join(app_dir, 'lib', 'arm')
    else:
        os.makedirs(os.path.join(sysd, section), exist_ok=True)
        apk = os.path.join(sysd, section, f'{name}.apk')
        jni_dir = os.path.join(sysd, 'lib')

    if patch:
        repack_apk.repack(src_apk, apk, patch)
        repack_apk.sign(apk, ks, alias, pw)
    else:
        copy(src_apk, apk)
    return apk, extract_jni(apk, jni_dir)


def app_fits(src_apk, layout):
    """True when the apk's minSdkVersion allows the layout's platform."""
    mn = describe(src_apk).get('minSdk')
    mn = mn if isinstance(mn, int) else 1
    return mn <= min(int(s) for s in layout['sdks']), mn


def tree_size_kb(root):
    total = 0
    for dp, _, fs in os.walk(root):
        for f in fs:
            total += os.path.getsize(os.path.join(dp, f))
    return total // 1024 + 1


def make_zip(stage, out_zip, installer, info_lines, extra=None):
    """Pack a staged system/ tree plus the installer into a flashable zip."""
    if os.path.exists(out_zip):
        os.remove(os.path.abspath(out_zip))
    os.makedirs(os.path.dirname(os.path.abspath(out_zip)), exist_ok=True)
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo('META-INF/com/google/android/update-binary')
        zi.external_attr = (0o100755 << 16)
        zi.date_time = (2026, 1, 1, 0, 0, 0)
        z.writestr(zi, open(installer, 'rb').read())
        z.writestr('META-INF/com/google/android/updater-script',
                   '# dummy: the real work is done by update-binary\n')
        z.writestr('inavi/info.txt', '\n'.join(info_lines) + '\n')
        for name, text in (extra or {}).items():
            z.writestr(f'inavi/{name}', text)
        if os.path.isdir(os.path.join(stage, 'system')):
            z.writestr('inavi/size_kb', str(tree_size_kb(stage) * 2))
            for dp, _, fs in sorted(os.walk(stage)):
                for f in sorted(fs):
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, stage)
                    z.write(full, rel)
    return out_zip


def add_navi_apks(sysd, report, navi_apks, layout):
    """Stage the real navigation apks (com.thinkware.sundo.inavi3d and friends).

    They are not part of the OS zip -- the firmware only ships 34 KB stubs -- so
    they have to be supplied separately. Each apk is dropped in as an ordinary
    /system/app entry, replacing the matching stub if one is staged.
    """
    STUB_PACKAGES = {
        'com.thinkware.inavi3ds': 'Dummy3DS',
        'com.thinkware.sundo.TBT': 'DummyTBT',
        'com.thinkware.sundo.TCONService': 'DummyTCONMW',
        'com.thinkware.sundo.happyteam.happywayard': 'DummyHappywayard',
    }
    for src in navi_apks:
        d = describe(src)
        pkg = d['package']
        name = ''.join(w.capitalize() for w in pkg.split('.')[-2:]) or 'InaviNavi'
        # a real apk for a package we only had a stub for replaces that stub
        stub = STUB_PACKAGES.get(pkg)
        if stub:
            shutil.rmtree(os.path.join(sysd, 'app', stub), ignore_errors=True)
            flat_stub = os.path.join(sysd, 'app', f'{stub}.apk')
            if os.path.exists(flat_stub):
                os.remove(flat_stub)
            name = stub.replace('Dummy', 'Inavi')
        fits, mn = app_fits(src, layout)
        if not fits:
            report.append((f'app/{name}', pkg, d['versionName'],
                           f'제외: minSdk {mn} > 이 플랫폼'))
            continue
        if d['sharedUserId']:
            report.append((f'app/{name}', pkg, d['versionName'],
                           f'경고: sharedUserId={d["sharedUserId"]} -> 순정 서명과 불일치로 '
                           f'설치 거부될 수 있음'))
        _, libs = place_app(sysd, 'app', name, src, layout)
        report.append((f'app/{name}', pkg, d['versionName'],
                       '아이나비 내비 본체 (사용자 제공)'
                       + (f' [+{len(libs)} JNI lib]' if libs else '')))


def build_core(fw, repo, out, ks, alias, pw, work, layout, navi_apks=()):
    stage = os.path.join(work, 'core-' + layout['suffix'])
    shutil.rmtree(stage, ignore_errors=True)
    sysd = os.path.join(stage, 'system')
    report = []

    # --- IvyLauncher: de-odexed, sharedUserId dropped, re-signed -------------
    src = os.path.join(repo, 'deodexed/app/IvyLauncher/IvyLauncher.apk')
    fits, mn = app_fits(src, layout)
    if fits:
        apk, _ = place_app(sysd, 'priv-app', 'IvyLauncher', src, layout,
                           patch=[('manifest', 'sharedUserId')],
                           ks=ks, alias=alias, pw=pw)
        d = describe(apk)
        assert d['sharedUserId'] is None, 'sharedUserId survived the patch'
        report.append(('priv-app/IvyLauncher', d['package'], d['versionName'],
                       '아이나비 X3 런처 (sharedUserId 제거 + 재서명)'))
    else:
        report.append(('priv-app/IvyLauncher', '-', '-',
                       f'제외: minSdk {mn} > 이 플랫폼'))

    # --- vendor apps, byte-identical to the firmware -------------------------
    for name, rel, what in VENDOR_APPS:
        s = os.path.join(fw, rel)
        if not os.path.exists(s):
            report.append((f'app/{name}', '-', '-', f'건너뜀: {rel} 없음'))
            continue
        fits, mn = app_fits(s, layout)
        d = describe(s)
        if not fits:
            report.append((f'app/{name}', d['package'], d['versionName'],
                           f'제외: minSdk {mn} > 이 플랫폼'))
            continue
        _, libs = place_app(sysd, 'app', name, s, layout)
        report.append((f'app/{name}', d['package'], d['versionName'],
                       what + (f' [+{len(libs)} JNI lib]' if libs else '')))

    # --- lib-tas shared library + its declaration ---------------------------
    jar_rel = layout['libtas']
    copy(os.path.join(fw, 'vendor/framework/lib-tas.jar'),
         os.path.join(sysd, jar_rel))
    os.makedirs(os.path.join(sysd, 'etc/permissions'), exist_ok=True)
    with open(os.path.join(sysd, 'etc/permissions/inavi-lib-tas.xml'), 'w') as f:
        f.write(LIB_TAS_XML.replace('@JAR@', '/system/' + jar_rel))
    report.append((jar_rel, 'lib-tas', '-',
                   'THINKWARE 공유 라이브러리 (+ etc/permissions 선언)'))

    # --- the vendor .so the shipped apps resolve against --------------------
    for lib in VENDOR_LIBS:
        s = os.path.join(fw, 'vendor/lib', lib)
        if os.path.exists(s):
            dest = os.path.join(sysd, layout['vendor_lib'], lib)
            copy(s, dest)
            report.append((f'{layout["vendor_lib"]}/{lib}', '-', '-',
                           'Steward TPEG 의존 라이브러리'))

    if navi_apks:
        add_navi_apks(sysd, report, navi_apks, layout)

    info = [
        '패키지: 아이나비 X3 시스템 앱 레이어 (core)',
        f'대상  : {layout["label"]} / 32비트 ARM',
        f'배치  : {"하위 디렉터리(5.0+)" if layout["cluster"] else "평면 구조(4.x)"}',
        '내용  : X3 런처 + 아이나비 계열 앱 + lib-tas 공유 라이브러리',
        '주의  : 부트로더/커널/HAL 은 건드리지 않습니다.',
    ]
    remove = ['/' + os.path.relpath(os.path.join(dp, f), sysd)
              for dp, _, fs in os.walk(sysd) for f in fs]
    z = make_zip(stage, os.path.join(out, f'INAVI_X3-core-{layout["suffix"]}.zip'),
                 os.path.join(repo, 'installer/update-binary'), info,
                 extra={'sdk.txt': ' '.join(layout['sdks']) + '\n'})
    return z, report, sorted(remove)


def build_systemui(fw, repo, out, ks, alias, pw, work, layout):
    """NaviSystemUI + NaviSettings. Explicitly experimental: these two replace
    com.android.systemui / com.android.settings, and they were built against the
    X3's AOSP framework resources, so on a Samsung ROM the resource ids they
    reference will not line up."""
    stage = os.path.join(work, 'sysui-' + layout['suffix'])
    shutil.rmtree(stage, ignore_errors=True)
    sysd = os.path.join(stage, 'system')
    report = []
    for name, src_rel, drop, what in (
        ('NaviSystemUI', 'deodexed/priv-app/NaviSystemUI/NaviSystemUI.apk',
         'sharedUserId', 'X3 상태바/내비바 (com.android.systemui 교체)'),
        ('NaviSettings', 'deodexed/priv-app/NaviSettings/NaviSettings.apk',
         'sharedUserId', 'X3 설정 (com.android.settings 교체)'),
    ):
        src = os.path.join(repo, src_rel)
        fits, mn = app_fits(src, layout)
        if not fits:
            report.append((f'priv-app/{name}', '-', '-',
                           f'제외: minSdk {mn} > 이 플랫폼'))
            continue
        apk, _ = place_app(sysd, 'priv-app', name, src, layout,
                           patch=[('manifest', drop)], ks=ks, alias=alias, pw=pw)
        d = describe(apk)
        report.append((f'priv-app/{name}', d['package'], d['versionName'], what))
    if not os.path.isdir(sysd):
        return None, report, []

    # the stock apks that own the same package names have to step aside
    predelete = '\n'.join([
        '# 같은 패키지명을 가진 순정 앱 (백업 후 제거)',
        '/priv-app/SystemUI',
        '/app/SystemUI',
        '/priv-app/SecSettings',
        '/priv-app/Settings',
        '/app/SecSettings',
        '/app/Settings',
    ]) + '\n'
    info = [
        '패키지: 아이나비 X3 상태바/설정 (실험용)',
        '',
        '*** 경고 ***',
        '순정 SystemUI/설정을 백업 후 제거하고 X3 것으로 바꿉니다.',
        '삼성 순정 ROM에서는 리소스 ID와 서명이 달라 상태바가 뜨지 않거나',
        '설정이 강제종료될 가능성이 매우 높습니다.',
        '문제가 생기면 제거(uninstall) zip 을 플래시해 되돌리세요.',
    ]
    remove = ['/' + os.path.relpath(os.path.join(dp, f), sysd)
              for dp, _, fs in os.walk(sysd) for f in fs]
    z = make_zip(stage, os.path.join(
                     out, f'INAVI_X3-systemui-{layout["suffix"]}-EXPERIMENTAL.zip'),
                 os.path.join(repo, 'installer/update-binary'), info,
                 extra={'predelete.txt': predelete, 'require_optin': '',
                        'sdk.txt': ' '.join(layout['sdks']) + '\n'})
    return z, report, sorted(remove)


def build_uninstall(repo, out, removals, work):
    """One uninstall package covering every layout, so it works whichever
    core package was flashed."""
    stage = os.path.join(work, 'uninstall')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage, exist_ok=True)
    extras = ['# 앱 디렉터리 / 평면 apk 양쪽 모두 정리',
              '/etc/permissions/inavi-lib-tas.xml',
              '/vendor/framework/lib-tas.jar',
              '/framework/lib-tas.jar']
    for n in ('IvyLauncher', 'NaviSystemUI', 'NaviSettings'):
        extras += [f'/priv-app/{n}', f'/priv-app/{n}.apk']
    for n, _, _ in VENDOR_APPS:
        extras += [f'/app/{n}', f'/app/{n}.apk']
    for lib in VENDOR_LIBS:
        extras += [f'/vendor/lib/{lib}', f'/lib/{lib}']
    body = ['# 이 포트가 설치한 파일 목록'] + removals + extras
    info = [
        '패키지: 아이나비 X3 포트 제거',
        '설치한 파일을 지우고, 이 설치 프로그램이 만든 백업을 복원합니다.',
        '안드로이드 4.4 / 6.0 패키지 모두에 대응합니다.',
    ]
    return make_zip(stage, os.path.join(out, 'INAVI_X3-uninstall.zip'),
                    os.path.join(repo, 'installer/update-binary'), info,
                    extra={'remove.txt': '\n'.join(body) + '\n'})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--firmware', required=True)
    ap.add_argument('--repo', default=os.path.dirname(HERE))
    ap.add_argument('--out', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--keystore', required=True)
    ap.add_argument('--alias', default='inavi-port')
    ap.add_argument('--storepass', default='inavix3')
    ap.add_argument('--navi-apk', action='append', default=[],
                    help='아이나비 내비 본체 apk (여러 번 지정 가능). '
                         '지도 데이터는 zip에 넣지 않고 내장메모리/SD에 둡니다.')
    ap.add_argument('--layout', action='append', default=[],
                    choices=sorted(LAYOUTS), help='빌드할 플랫폼 (기본: 전부)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    wanted = a.layout or sorted(LAYOUTS)

    def show(title, rows, path):
        size = f'{os.path.getsize(path) / 1048576:.1f} MB' if path else '-'
        print(f'\n=== {title}  ({size})')
        print(f'    {os.path.basename(path) if path else "(생성 안 함)"}')
        for where, pkg, ver, what in rows:
            print(f'    {where:34s} {str(pkg):42s} {str(ver):10s} {what}')

    removals = []
    for key in wanted:
        layout = LAYOUTS[key]
        core, rc, rem1 = build_core(a.firmware, a.repo, a.out, a.keystore, a.alias,
                                    a.storepass, a.work, layout, a.navi_apk)
        sysui, rs, rem2 = build_systemui(a.firmware, a.repo, a.out, a.keystore,
                                         a.alias, a.storepass, a.work, layout)
        removals += rem1 + rem2
        show(f'core / {layout["label"]}', rc, core)
        show(f'systemui / {layout["label"]} (실험용)', rs, sysui)

    unin = build_uninstall(a.repo, a.out, sorted(set(removals)), a.work)
    print(f'\n=== 제거 패키지  ({os.path.getsize(unin) / 1024:.0f} KB)')
    print(f'    {os.path.basename(unin)}')


if __name__ == '__main__':
    main()
