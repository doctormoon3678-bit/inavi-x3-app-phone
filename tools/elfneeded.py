#!/usr/bin/env python3
"""Print DT_NEEDED / SONAME of 32-bit ARM ELF shared objects."""
import struct, sys, os

DT_NEEDED, DT_STRTAB, DT_SONAME, DT_STRSZ = 1, 5, 14, 10
PT_DYNAMIC = 2


def info(data):
    if data[:4] != b'\x7fELF':
        return None
    is64 = data[4] == 2
    machine = struct.unpack_from('<H', data, 18)[0]
    arch = {40: 'arm', 183: 'aarch64', 3: 'x86', 62: 'x86_64'}.get(machine, str(machine))
    if is64:
        phoff = struct.unpack_from('<Q', data, 32)[0]
        phentsize, phnum = struct.unpack_from('<HH', data, 54)
    else:
        phoff = struct.unpack_from('<I', data, 28)[0]
        phentsize, phnum = struct.unpack_from('<HH', data, 42)
    dyn_off = dyn_sz = None
    for i in range(phnum):
        p = phoff + i * phentsize
        ptype = struct.unpack_from('<I', data, p)[0]
        if ptype == PT_DYNAMIC:
            if is64:
                dyn_off = struct.unpack_from('<Q', data, p + 8)[0]
                dyn_sz = struct.unpack_from('<Q', data, p + 32)[0]
            else:
                dyn_off = struct.unpack_from('<I', data, p + 4)[0]
                dyn_sz = struct.unpack_from('<I', data, p + 16)[0]
            break
    if dyn_off is None:
        return {'arch': arch, 'bits': 64 if is64 else 32, 'needed': [], 'soname': None}
    ent = 16 if is64 else 8
    entries = []
    strtab_va = None
    for off in range(dyn_off, dyn_off + dyn_sz, ent):
        if is64:
            tag, val = struct.unpack_from('<QQ', data, off)
        else:
            tag, val = struct.unpack_from('<II', data, off)
        if tag == 0:
            break
        entries.append((tag, val))
        if tag == DT_STRTAB:
            strtab_va = val

    # map the strtab virtual address back to a file offset through PT_LOAD
    strtab_off = None
    for i in range(phnum):
        p = phoff + i * phentsize
        ptype = struct.unpack_from('<I', data, p)[0]
        if ptype != 1:
            continue
        if is64:
            o, va, _pa, fsz = struct.unpack_from('<QQQQ', data, p + 8)
        else:
            o, va, _pa, fsz = struct.unpack_from('<IIII', data, p + 4)
        if strtab_va is not None and va <= strtab_va < va + fsz:
            strtab_off = o + (strtab_va - va)
            break
    if strtab_off is None:
        strtab_off = strtab_va

    def s(idx):
        p = strtab_off + idx
        e = data.index(b'\x00', p)
        return data[p:e].decode('utf-8', 'replace')

    needed = [s(v) for t, v in entries if t == DT_NEEDED]
    soname = next((s(v) for t, v in entries if t == DT_SONAME), None)
    return {'arch': arch, 'bits': 64 if is64 else 32, 'needed': needed, 'soname': soname}


if __name__ == '__main__':
    for p in sys.argv[1:]:
        d = info(open(p, 'rb').read())
        if not d:
            print(f'{p}: not ELF'); continue
        print(f'{os.path.basename(p)} [{d["arch"]}/{d["bits"]}] soname={d["soname"]}')
        for n in d['needed']:
            print(f'    -> {n}')
