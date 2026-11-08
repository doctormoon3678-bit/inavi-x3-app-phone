#!/usr/bin/env python3
"""Minimal binary AndroidManifest.xml reader: package, sdk, permissions, libs, components."""
import struct, sys, zipfile

RES_STRING_POOL = 0x0001
RES_XML_START_ELEMENT = 0x0102
RES_XML_RESOURCE_MAP = 0x0180

TYPE_NULL, TYPE_REFERENCE, TYPE_STRING, TYPE_INT_DEC, TYPE_INT_HEX, TYPE_INT_BOOL = 0, 1, 3, 0x10, 0x11, 0x12


def read_string_pool(buf, off):
    hdr_type, hdr_size, size = struct.unpack_from('<HHI', buf, off)
    cnt, _sc, flags, str_start, _ss = struct.unpack_from('<IIIII', buf, off + 8)
    utf8 = bool(flags & (1 << 8))
    offs = struct.unpack_from('<%dI' % cnt, buf, off + 28)
    base = off + str_start
    out = []
    for o in offs:
        p = base + o
        if utf8:
            n = buf[p]
            p += 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | buf[p]; p += 1
            n2 = buf[p]; p += 1
            if n2 & 0x80:
                n2 = ((n2 & 0x7F) << 8) | buf[p]; p += 1
            out.append(buf[p:p + n2].decode('utf-8', 'replace'))
        else:
            n = struct.unpack_from('<H', buf, p)[0]; p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from('<H', buf, p)[0]; p += 2
            out.append(buf[p:p + n * 2].decode('utf-16-le', 'replace'))
    return out, off + size


def parse(buf):
    pos = 8  # skip file header
    strings = None
    elements = []
    while pos < len(buf) - 8:
        t, hs, sz = struct.unpack_from('<HHI', buf, pos)
        if sz == 0:
            break
        if t == RES_STRING_POOL:
            strings, _ = read_string_pool(buf, pos)
        elif t == RES_XML_START_ELEMENT:
            p = pos + hs
            ns_i, name_i = struct.unpack_from('<ii', buf, p)
            a_start, a_size, a_cnt = struct.unpack_from('<HHH', buf, p + 8)
            attrs = {}
            ap = p + a_start
            for _ in range(a_cnt):
                a_ns, a_nm, a_raw, a_tv, a_data = struct.unpack_from('<iiiIi', buf, ap)
                typ = (a_tv >> 24) & 0xFF
                key = strings[a_nm] if 0 <= a_nm < len(strings) else f'?{a_nm}'
                if typ == TYPE_STRING and 0 <= a_data < len(strings):
                    val = strings[a_data]
                elif typ == TYPE_INT_BOOL:
                    val = bool(a_data)
                elif typ == TYPE_REFERENCE:
                    val = f'@0x{a_data & 0xFFFFFFFF:08x}'
                else:
                    val = a_data
                attrs[key] = val
                ap += a_size
            elements.append((strings[name_i], attrs))
        pos += sz
    return elements


def describe(apk):
    with zipfile.ZipFile(apk) as z:
        els = parse(z.read('AndroidManifest.xml'))
        names = z.namelist()
    info = {'apk': apk, 'libs': sorted({n for n in names if n.startswith('lib/')}),
            'assets': sum(1 for n in names if n.startswith('assets/')),
            'has_classes_dex': any(n.startswith('classes') and n.endswith('.dex') for n in names),
            'uses_permission': [], 'uses_library': [], 'launcher': [], 'perm_defined': []}
    for name, a in els:
        if name == 'manifest':
            info['package'] = a.get('package')
            info['sharedUserId'] = a.get('sharedUserId')
            info['versionName'] = a.get('versionName')
            info['versionCode'] = a.get('versionCode')
        elif name == 'uses-sdk':
            info['minSdk'] = a.get('minSdkVersion')
            info['targetSdk'] = a.get('targetSdkVersion')
        elif name == 'uses-permission':
            info['uses_permission'].append(a.get('name'))
        elif name == 'permission':
            info['perm_defined'].append(a.get('name'))
        elif name == 'uses-library':
            info['uses_library'].append((a.get('name'), a.get('required', True)))
        elif name == 'application':
            info['app_name'] = a.get('name')
            info['persistent'] = a.get('persistent')
            info['label'] = a.get('label')
        elif name == 'category' and a.get('name') in (
                'android.intent.category.HOME', 'android.intent.category.LAUNCHER'):
            info['launcher'].append(a.get('name'))
    return info


if __name__ == '__main__':
    import json
    for p in sys.argv[1:]:
        try:
            print(json.dumps(describe(p), ensure_ascii=False))
        except Exception as e:
            print(json.dumps({'apk': p, 'error': f'{type(e).__name__}: {e}'}))
