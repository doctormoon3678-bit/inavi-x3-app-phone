#!/usr/bin/env python3
"""Append classes*.dex to an APK without touching existing entries.

Existing entries keep their bytes and offsets (alignment and the original
v1 signature stay intact); the dex files are added deflated at the end, so
no re-zipalign is needed. Then verifies 4-byte alignment of stored entries.
usage: merge_dex.py <in.apk> <dex-dir> <out.apk>
"""
import os, shutil, sys, zipfile, struct

src, dexdir, out = sys.argv[1:4]
shutil.copyfile(src, out)
dexes = sorted(f for f in os.listdir(dexdir) if f.startswith('classes') and f.endswith('.dex'))
with zipfile.ZipFile(out, 'a') as z:
    if any(n.endswith('.dex') for n in z.namelist()):
        raise SystemExit(f'{src}: already contains dex')
    for d in dexes:
        zi = zipfile.ZipInfo(d, date_time=(2008, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        z.writestr(zi, open(os.path.join(dexdir, d), 'rb').read(), compresslevel=9)
raw = open(out, 'rb').read()
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    for zi in z.infolist():
        if zi.compress_type == zipfile.ZIP_STORED and zi.file_size:
            n, e = struct.unpack_from('<HH', raw, zi.header_offset + 26)
            data_off = zi.header_offset + 30 + n + e
            if data_off % 4:
                print(f'warning: {zi.filename} not 4-byte aligned')
print(f'{os.path.basename(out)}: +{" ".join(dexes)}')
