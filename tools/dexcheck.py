#!/usr/bin/env python3
"""Walk every code_item in a dex and report ART-only / undefined opcodes.

A properly de-odexed dex for API 23 must contain none of:
  0x73            return-void-no-barrier
  0x3e-0x43       unused
  0x79, 0x7a      unused
  0xe3-0xff       quickened (iget/iput-*-quick, invoke-virtual-quick, ...)
Any hit means the odex -> dex conversion left ART-internal code behind and the
app will abort as soon as that method runs.
"""
import struct, sys, zipfile

# instruction width in 16-bit code units, indexed by opcode
W = [0] * 256


def _fill(lo, hi, w):
    for o in range(lo, hi + 1):
        W[o] = w


_fill(0x00, 0x01, 1)
W[0x02] = 2; W[0x03] = 3; W[0x04] = 1; W[0x05] = 2; W[0x06] = 3
W[0x07] = 1; W[0x08] = 2; W[0x09] = 3
_fill(0x0A, 0x12, 1)
W[0x13] = 2; W[0x14] = 3; W[0x15] = 2; W[0x16] = 2; W[0x17] = 3
W[0x18] = 5; W[0x19] = 2; W[0x1A] = 2; W[0x1B] = 3; W[0x1C] = 2
W[0x1D] = 1; W[0x1E] = 1; W[0x1F] = 2; W[0x20] = 2; W[0x21] = 1
W[0x22] = 2; W[0x23] = 2; W[0x24] = 3; W[0x25] = 3; W[0x26] = 3
W[0x27] = 1; W[0x28] = 1; W[0x29] = 2; W[0x2A] = 3; W[0x2B] = 3; W[0x2C] = 3
_fill(0x2D, 0x31, 2)
_fill(0x32, 0x37, 2)
_fill(0x38, 0x3D, 2)
_fill(0x3E, 0x43, 1)          # unused
_fill(0x44, 0x51, 2)
_fill(0x52, 0x5F, 2)
_fill(0x60, 0x6D, 2)
_fill(0x6E, 0x72, 3)
W[0x73] = 1                   # unused / return-void-no-barrier
_fill(0x74, 0x78, 3)
_fill(0x79, 0x7A, 1)          # unused
_fill(0x7B, 0x8F, 1)
_fill(0x90, 0xAF, 2)
_fill(0xB0, 0xCF, 1)
_fill(0xD0, 0xD7, 2)
_fill(0xD8, 0xE2, 2)
# quickened / undefined: widths so the walk can continue past them
_fill(0xE3, 0xE8, 2)          # iget/iput-*-quick            (22c)
W[0xE9] = 3; W[0xEA] = 3      # invoke-virtual-quick[/range]  (35c / 3rc)
_fill(0xEB, 0xF2, 2)          # more *-quick                  (22c)
_fill(0xF3, 0xF9, 1)
W[0xFA] = 4; W[0xFB] = 4; W[0xFC] = 3; W[0xFD] = 3; W[0xFE] = 2; W[0xFF] = 2

BAD = set([0x73]) | set(range(0x3E, 0x44)) | {0x79, 0x7A} | set(range(0xE3, 0x100))

NAMES = {0x73: 'return-void-no-barrier', 0xE3: 'iget-quick', 0xE4: 'iget-wide-quick',
         0xE5: 'iget-object-quick', 0xE6: 'iput-quick', 0xE7: 'iput-wide-quick',
         0xE8: 'iput-object-quick', 0xE9: 'invoke-virtual-quick',
         0xEA: 'invoke-virtual-quick/range', 0xEB: 'iput-boolean-quick',
         0xEC: 'iput-byte-quick', 0xED: 'iput-char-quick', 0xEE: 'iput-short-quick',
         0xEF: 'iget-boolean-quick', 0xF0: 'iget-byte-quick', 0xF1: 'iget-char-quick',
         0xF2: 'iget-short-quick'}


def uleb(b, p):
    r = 0; s = 0
    while True:
        x = b[p]; p += 1
        r |= (x & 0x7F) << s
        if not x & 0x80:
            return r, p
        s += 7


def walk_code(b, off, insns_size, found):
    pc = off
    end = off + insns_size * 2
    while pc < end:
        unit = struct.unpack_from('<H', b, pc)[0]
        op = unit & 0xFF
        if op == 0x00:
            ident = unit >> 8
            if ident == 0:
                w = 1
            elif ident == 1:
                w = struct.unpack_from('<H', b, pc + 2)[0] * 2 + 4
            elif ident == 2:
                w = struct.unpack_from('<H', b, pc + 2)[0] * 4 + 2
            elif ident == 3:
                ew = struct.unpack_from('<H', b, pc + 2)[0]
                sz = struct.unpack_from('<I', b, pc + 4)[0]
                w = (sz * ew + 1) // 2 + 4
            else:
                w = 1
        else:
            if op in BAD:
                found[op] = found.get(op, 0) + 1
            w = W[op] or 1
        pc += w * 2


def check(data):
    if data[:8] not in (b'dex\n035\x00', b'dex\n036\x00', b'dex\n037\x00', b'dex\n038\x00',
                        b'dex\n039\x00'):
        return None, f'not a dex (magic {data[:8]!r})'
    class_defs_size, class_defs_off = struct.unpack_from('<II', data, 96)
    found = {}
    methods = 0
    for i in range(class_defs_size):
        cd = class_defs_off + i * 32
        class_data_off = struct.unpack_from('<I', data, cd + 24)[0]
        if not class_data_off:
            continue
        p = class_data_off
        sf, p = uleb(data, p)
        inf, p = uleb(data, p)
        dm, p = uleb(data, p)
        vm, p = uleb(data, p)
        for _ in range(sf + inf):
            _, p = uleb(data, p)
            _, p = uleb(data, p)
        for _ in range(dm + vm):
            _, p = uleb(data, p)   # method_idx_diff
            _, p = uleb(data, p)   # access_flags
            code_off, p = uleb(data, p)
            if code_off:
                methods += 1
                insns_size = struct.unpack_from('<I', data, code_off + 12)[0]
                walk_code(data, code_off + 16, insns_size, found)
    return (methods, found), None


def main(paths):
    rc = 0
    for path in paths:
        if path.endswith(('.apk', '.jar', '.zip')):
            with zipfile.ZipFile(path) as z:
                dexes = [(n, z.read(n)) for n in z.namelist()
                         if n.startswith('classes') and n.endswith('.dex')]
            if not dexes:
                print(f'{path}: NO classes.dex'); rc = 1; continue
        else:
            dexes = [(path, open(path, 'rb').read())]
        for name, data in dexes:
            res, err = check(data)
            if err:
                print(f'{path}!{name}: {err}'); rc = 1; continue
            methods, found = res
            if found:
                rc = 1
                detail = ', '.join(f'0x{o:02x} {NAMES.get(o, "undefined")} x{c}'
                                   for o, c in sorted(found.items()))
                print(f'FAIL {path}!{name}: {methods} methods, LEFTOVER: {detail}')
            else:
                print(f'OK   {path}!{name}: {methods} methods with code, no ART-only opcodes')
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
