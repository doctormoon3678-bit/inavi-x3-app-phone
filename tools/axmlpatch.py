#!/usr/bin/env python3
"""Remove an attribute from an element in a binary AndroidManifest.xml.

Usage: axmlpatch.py <in.xml> <out.xml> <element> <attribute>
e.g.   axmlpatch.py AndroidManifest.xml out.xml manifest sharedUserId
"""
import struct, sys

RES_STRING_POOL = 0x0001
RES_XML_START_ELEMENT = 0x0102


def read_string_pool(buf, off):
    cnt = struct.unpack_from('<I', buf, off + 8)[0]
    flags, str_start = struct.unpack_from('<II', buf, off + 16)
    utf8 = bool(flags & (1 << 8))
    offs = struct.unpack_from('<%dI' % cnt, buf, off + 28)
    base = off + str_start
    out = []
    for o in offs:
        p = base + o
        if utf8:
            n = buf[p]; p += 1
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
    return out


def patch(data, el_name, attr_name):
    buf = bytearray(data)
    strings = None
    pos = 8
    removed = []
    while pos < len(buf) - 8:
        t, hs, sz = struct.unpack_from('<HHI', buf, pos)
        if sz == 0:
            break
        if t == RES_STRING_POOL and strings is None:
            strings = read_string_pool(buf, pos)
        elif t == RES_XML_START_ELEMENT:
            p = pos + hs
            name_i = struct.unpack_from('<i', buf, p + 4)[0]
            if strings and 0 <= name_i < len(strings) and strings[name_i] == el_name:
                a_start, a_size, a_cnt = struct.unpack_from('<HHH', buf, p + 8)
                id_i, cls_i, sty_i = struct.unpack_from('<HHH', buf, p + 14)
                for k in range(a_cnt):
                    ap = p + a_start + k * a_size
                    a_nm = struct.unpack_from('<i', buf, ap + 4)[0]
                    if 0 <= a_nm < len(strings) and strings[a_nm] == attr_name:
                        # drop this attribute
                        del buf[ap:ap + a_size]
                        struct.pack_into('<H', buf, p + 12, a_cnt - 1)
                        struct.pack_into('<I', buf, pos + 4, sz - a_size)
                        total = struct.unpack_from('<I', buf, 4)[0]
                        struct.pack_into('<I', buf, 4, total - a_size)
                        # 1-based indices into the attribute list; 0 == none
                        for field_off, val in ((14, id_i), (16, cls_i), (18, sty_i)):
                            if val and val - 1 > k:
                                struct.pack_into('<H', buf, p + field_off, val - 1)
                        removed.append((el_name, attr_name))
                        sz -= a_size
                        break
        pos += sz
    return bytes(buf), removed


def main():
    src, dst, el, attr = sys.argv[1:5]
    out, removed = patch(open(src, 'rb').read(), el, attr)
    if not removed:
        raise SystemExit(f'error: <{el} {attr}=...> not found')
    open(dst, 'wb').write(out)
    print(f'removed {attr} from <{el}>: {len(open(src, "rb").read())} -> {len(out)} bytes')


if __name__ == '__main__':
    main()
