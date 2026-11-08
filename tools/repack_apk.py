#!/usr/bin/env python3
"""Repack an APK: optionally drop manifest attributes, strip the old signature,
keep resources.arsc / *.so STORED and 4-byte aligned, then re-sign with jarsigner.

  repack_apk.py in.apk out.apk [--drop manifest:sharedUserId] [--keystore k --alias a --storepass p]

Without keystore options the output is left unsigned (so it can be signed later).
"""
import argparse, binascii, os, struct, subprocess, sys, zipfile, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axmlpatch import patch as axml_patch

ALIGN = 4
STORE_SUFFIXES = ('.so',)
STORE_NAMES = ('resources.arsc',)


def should_store(name):
    return name in STORE_NAMES or name.endswith(STORE_SUFFIXES)


def repack(src, dst, drops):
    applied = []
    zin = zipfile.ZipFile(src)
    names = [i for i in zin.infolist() if not i.filename.upper().startswith('META-INF/')]

    # build the member list first so alignment padding can be computed as we write
    out = open(dst, 'wb')
    central = []
    for info in names:
        data = zin.read(info.filename)
        if info.filename == 'AndroidManifest.xml' and drops:
            for el, attr in drops:
                data, rem = axml_patch(data, el, attr)
                if rem:
                    applied += rem
        store = should_store(info.filename)
        if store:
            comp_data = data
            method = zipfile.ZIP_STORED
        else:
            co = zlib.compressobj(9, zlib.DEFLATED, -15)
            comp_data = co.compress(data) + co.flush()
            method = zipfile.ZIP_DEFLATED

        crc = binascii.crc32(data) & 0xFFFFFFFF
        name_b = info.filename.encode('utf-8')
        extra = b''
        if store:
            # zero-pad the local extra field so the payload starts on an ALIGN
            # boundary, which is what zipalign does for uncompressed members
            header_end = out.tell() + 30 + len(name_b)
            extra = b'\x00' * ((ALIGN - (header_end % ALIGN)) % ALIGN)
        offset = out.tell()
        out.write(struct.pack('<IHHHHHIIIHH', 0x04034b50, 20, 0, method,
                              0, 0, crc, len(comp_data), len(data),
                              len(name_b), len(extra)))
        out.write(name_b)
        out.write(extra)
        out.write(comp_data)
        central.append((info.filename, method, crc, len(comp_data), len(data), offset,
                        info.external_attr))

    cd_start = out.tell()
    for name, method, crc, csize, size, offset, attrs in central:
        name_b = name.encode('utf-8')
        out.write(struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 20, 20, 0, method,
                              0, 0, crc, csize, size, len(name_b), 0, 0, 0, 0,
                              attrs, offset))
        out.write(name_b)
    cd_end = out.tell()
    out.write(struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(central), len(central),
                          cd_end - cd_start, cd_start, 0))
    out.close()
    zin.close()

    # sanity: readable zip, manifest intact, every STORED member 4-byte aligned
    with zipfile.ZipFile(dst) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f'repack produced a corrupt entry: {bad}')
        if 'AndroidManifest.xml' not in z.namelist():
            raise SystemExit('repack lost AndroidManifest.xml')
        if len(z.namelist()) != len(names):
            raise SystemExit(f'repack lost entries: {len(names)} -> {len(z.namelist())}')
        for i in z.infolist():
            if i.compress_type == zipfile.ZIP_STORED and i.header_offset is not None:
                with open(dst, 'rb') as f:
                    f.seek(i.header_offset + 26)
                    nl, el = struct.unpack('<HH', f.read(4))
                payload = i.header_offset + 30 + nl + el
                if payload % ALIGN:
                    raise SystemExit(f'{i.filename} not {ALIGN}-byte aligned ({payload})')
    return applied


def sign(apk, keystore, alias, storepass):
    # SHA-256 JAR (v1) signatures: understood by Android 4.3+, and unlike SHA-1
    # they are not rejected as "weak" by current JDKs when verifying.
    subprocess.run(['jarsigner', '-keystore', keystore, '-storepass', storepass,
                    '-sigalg', 'SHA256withRSA', '-digestalg', 'SHA-256',
                    '-sigfile', 'CERT', apk, alias],
                   check=True, stdout=subprocess.DEVNULL)
    r = subprocess.run(['jarsigner', '-verify', apk], capture_output=True, text=True)
    if 'jar verified' not in r.stdout:
        raise SystemExit(f'signature verification failed for {apk}:\n{r.stdout}{r.stderr}')
    verify_v1(apk)


def verify_v1(apk):
    """Independent check that every zip member is covered by the v1 signature.

    Android refuses an APK that contains an entry with no digest in MANIFEST.MF,
    which is exactly what happens when a dex is dropped into a signed apk
    without re-signing.
    """
    import base64, hashlib, re
    with zipfile.ZipFile(apk) as z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        man = z.read('META-INF/MANIFEST.MF').decode('utf-8', 'replace')
        sections = {}
        for sec in re.split(r'\r?\n\r?\n', man):
            sec = sec.replace('\r\n', '\n').replace('\n ', '')  # unfold continuations
            m = re.search(r'^Name:\s*(.+)$', sec, re.M)
            if not m:
                continue
            d = re.search(r'^(SHA-256|SHA1|SHA-1)-Digest:\s*(\S+)$', sec, re.M)
            if d:
                sections[m.group(1).strip()] = (d.group(1), d.group(2))
        missing, wrong = [], []
        for n in names:
            if n.upper().startswith('META-INF/'):
                continue
            if n not in sections:
                missing.append(n); continue
            algo, want = sections[n]
            h = hashlib.sha256 if algo == 'SHA-256' else hashlib.sha1
            got = base64.b64encode(h(z.read(n)).digest()).decode()
            if got != want:
                wrong.append(n)
    if missing or wrong:
        raise SystemExit(f'{apk}: v1 signature incomplete — '
                         f'{len(missing)} unsigned entries {missing[:5]}, '
                         f'{len(wrong)} digest mismatches {wrong[:5]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--drop', action='append', default=[],
                    help='element:attribute to remove from AndroidManifest.xml')
    ap.add_argument('--keystore'); ap.add_argument('--alias'); ap.add_argument('--storepass')
    a = ap.parse_args()
    drops = []
    for d in a.drop:
        el, _, attr = d.partition(':')
        drops.append((el, attr))
    applied = repack(a.src, a.dst, drops)
    for el, attr in drops:
        if (el, attr) not in applied:
            raise SystemExit(f'error: <{el} {attr}> not present in {a.src}')
    if a.keystore:
        sign(a.dst, a.keystore, a.alias, a.storepass)
    print(f'{os.path.basename(a.dst)}: {os.path.getsize(a.dst)} bytes'
          + (f', dropped {applied}' if applied else '')
          + (', signed' if a.keystore else ', UNSIGNED'))


if __name__ == '__main__':
    main()
