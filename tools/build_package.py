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
            file="/system/vendor/framework/lib-tas.jar" />
</permissions>
"""


def sh(*cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def extract_jni(apk, dest_dir):
    """Place an apk's bundled armeabi libs next to it as lib/arm/*.so.

    Android does not unpack native libraries for apps that live in /system, so a
    ported system app only finds its JNI code if the .so files sit in
    <app dir>/lib/arm/.
    """
    out = []
    with zipfile.ZipFile(apk) as z:
        members = [n for n in z.namelist() if n.endswith('.so') and n.startswith('lib/')]
        # prefer armeabi-v7a, fall back to armeabi
        for abi in ('armeabi-v7a', 'armeabi'):
            sel = [n for n in members if n.startswith(f'lib/{abi}/')]
            if sel:
                break
        for n in sel:
            target = os.path.join(dest_dir, 'lib', 'arm', os.path.basename(n))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'wb') as f:
                f.write(z.read(n))
            out.append(target)
    return out


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


def add_navi_apks(sysd, report, navi_apks):
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
            name = stub.replace('Dummy', 'Inavi')
        if d['sharedUserId']:
            report.append((f'app/{name}', pkg, d['versionName'],
                           f'경고: sharedUserId={d["sharedUserId"]} -> 순정 서명과 불일치로 '
                           f'설치 거부될 수 있음'))
        dd = os.path.join(sysd, 'app', name)
        os.makedirs(dd, exist_ok=True)
        apk = copy(src, os.path.join(dd, f'{name}.apk'))
        libs = extract_jni(apk, dd)
        report.append((f'app/{name}', pkg, d['versionName'],
                       '아이나비 내비 본체 (사용자 제공)'
                       + (f' [+{len(libs)} JNI lib]' if libs else '')))


def build_core(fw, repo, out, ks, alias, pw, work, navi_apks=()):
    stage = os.path.join(work, 'core')
    shutil.rmtree(stage, ignore_errors=True)
    sysd = os.path.join(stage, 'system')
    report = []

    # --- IvyLauncher: de-odexed, sharedUserId dropped, re-signed -------------
    src = os.path.join(repo, 'deodexed/app/IvyLauncher/IvyLauncher.apk')
    dest_dir = os.path.join(sysd, 'priv-app/IvyLauncher')
    os.makedirs(dest_dir, exist_ok=True)
    apk = os.path.join(dest_dir, 'IvyLauncher.apk')
    repack_apk.repack(src, apk, [('manifest', 'sharedUserId')])
    repack_apk.sign(apk, ks, alias, pw)
    extract_jni(apk, dest_dir)
    d = describe(apk)
    assert d['sharedUserId'] is None, 'sharedUserId survived the patch'
    report.append(('priv-app/IvyLauncher', d['package'], d['versionName'],
                   '아이나비 X3 런처 (sharedUserId 제거 + 재서명)'))

    # --- vendor apps, byte-identical to the firmware -------------------------
    for name, rel, what in VENDOR_APPS:
        s = os.path.join(fw, rel)
        if not os.path.exists(s):
            report.append((f'app/{name}', '-', '-', f'건너뜀: {rel} 없음'))
            continue
        dd = os.path.join(sysd, 'app', name)
        os.makedirs(dd, exist_ok=True)
        a = copy(s, os.path.join(dd, f'{name}.apk'))
        libs = extract_jni(a, dd)
        d = describe(a)
        report.append((f'app/{name}', d['package'], d['versionName'],
                       what + (f' [+{len(libs)} JNI lib]' if libs else '')))

    # --- lib-tas shared library + its declaration ---------------------------
    copy(os.path.join(fw, 'vendor/framework/lib-tas.jar'),
         os.path.join(sysd, 'vendor/framework/lib-tas.jar'))
    os.makedirs(os.path.join(sysd, 'etc/permissions'), exist_ok=True)
    with open(os.path.join(sysd, 'etc/permissions/inavi-lib-tas.xml'), 'w') as f:
        f.write(LIB_TAS_XML)
    report.append(('vendor/framework/lib-tas.jar', 'lib-tas', '-',
                   'THINKWARE 공유 라이브러리 (+ etc/permissions 선언)'))

    # --- the two vendor .so the shipped apps resolve against ----------------
    for lib in VENDOR_LIBS:
        s = os.path.join(fw, 'vendor/lib', lib)
        if os.path.exists(s):
            copy(s, os.path.join(sysd, 'vendor/lib', lib))
            report.append((f'vendor/lib/{lib}', '-', '-', 'Steward TPEG 의존 라이브러리'))

    if navi_apks:
        add_navi_apks(sysd, report, navi_apks)

    info = [
        '패키지: 아이나비 X3 시스템 앱 레이어 (core)',
        '대상  : SM-N916S / 안드로이드 6.0.1 32비트',
        '내용  : X3 런처 + 아이나비 계열 앱 + lib-tas 공유 라이브러리',
        '주의  : 부트로더/커널/HAL 은 건드리지 않습니다.',
    ]
    remove = ['/' + os.path.relpath(os.path.join(dp, f), sysd)
              for dp, _, fs in os.walk(sysd) for f in fs]
    z = make_zip(stage, os.path.join(out, 'INAVI_X3_N916S-core.zip'),
                 os.path.join(repo, 'installer/update-binary'), info)
    return z, report, sorted(remove)


def build_systemui(fw, repo, out, ks, alias, pw, work):
    """NaviSystemUI + NaviSettings. Explicitly experimental: these two replace
    com.android.systemui / com.android.settings, and they were built against the
    X3's AOSP framework resources, so on a Samsung ROM the resource ids they
    reference will not line up."""
    stage = os.path.join(work, 'sysui')
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
        dd = os.path.join(sysd, 'priv-app', name)
        os.makedirs(dd, exist_ok=True)
        apk = os.path.join(dd, f'{name}.apk')
        repack_apk.repack(src, apk, [('manifest', drop)])
        repack_apk.sign(apk, ks, alias, pw)
        extract_jni(apk, dd)
        d = describe(apk)
        report.append((f'priv-app/{name}', d['package'], d['versionName'], what))

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
    z = make_zip(stage, os.path.join(out, 'INAVI_X3_N916S-systemui-EXPERIMENTAL.zip'),
                 os.path.join(repo, 'installer/update-binary'), info,
                 extra={'predelete.txt': predelete, 'require_optin': ''})
    return z, report, sorted(remove)


def build_uninstall(repo, out, removals, work):
    stage = os.path.join(work, 'uninstall')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage, exist_ok=True)
    body = ['# 이 포트가 설치한 파일 목록'] + removals + [
        '# 앱 디렉터리 자체도 정리',
        '/priv-app/IvyLauncher', '/priv-app/NaviSystemUI', '/priv-app/NaviSettings',
        '/etc/permissions/inavi-lib-tas.xml',
        '/vendor/framework/lib-tas.jar',
    ] + [f'/app/{n}' for n, _, _ in VENDOR_APPS]
    info = [
        '패키지: 아이나비 X3 포트 제거',
        '설치한 파일을 지우고, 가장 최근 백업에서 순정 파일을 복원합니다.',
    ]
    return make_zip(stage, os.path.join(out, 'INAVI_X3_N916S-uninstall.zip'),
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
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)

    core, rc, rem1 = build_core(a.firmware, a.repo, a.out, a.keystore, a.alias,
                                a.storepass, a.work, a.navi_apk)
    sysui, rs, rem2 = build_systemui(a.firmware, a.repo, a.out, a.keystore, a.alias,
                                     a.storepass, a.work)
    unin = build_uninstall(a.repo, a.out, sorted(set(rem1 + rem2)), a.work)

    def show(title, rows, path):
        print(f'\n=== {title}  ({os.path.getsize(path) / 1048576:.1f} MB)')
        print(f'    {os.path.basename(path)}')
        for where, pkg, ver, what in rows:
            print(f'    {where:34s} {str(pkg):42s} {str(ver):10s} {what}')

    show('core 패키지', rc, core)
    show('systemui 패키지 (실험용)', rs, sysui)
    print(f'\n=== 제거 패키지  ({os.path.getsize(unin) / 1024:.0f} KB)')
    print(f'    {os.path.basename(unin)}')


if __name__ == '__main__':
    main()
