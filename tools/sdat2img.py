#!/usr/bin/env python3
"""transfer.list + .new.dat -> raw ext4 image (sdat2img equivalent, list v1-4)."""
import sys, os

BLK = 4096


def parse_ranges(s):
    v = [int(x) for x in s.split(',')]
    n = v[0]
    pairs = v[1:]
    assert len(pairs) == n and n % 2 == 0, f"bad range set: {s}"
    return [(pairs[i], pairs[i + 1]) for i in range(0, n, 2)]


def main(tlist, newdat, out):
    lines = open(tlist).read().splitlines()
    ver = int(lines[0])
    total_blocks = int(lines[1])
    cmds = lines[2:] if ver < 2 else lines[4:]

    max_blk = total_blocks
    for ln in cmds:
        parts = ln.split(' ', 1)
        if len(parts) == 2 and parts[0] in ('new', 'zero', 'erase'):
            for a, b in parse_ranges(parts[1]):
                max_blk = max(max_blk, b)

    with open(newdat, 'rb') as src, open(out, 'wb') as dst:
        dst.truncate(max_blk * BLK)
        written = 0
        for ln in cmds:
            parts = ln.split(' ', 1)
            if len(parts) != 2:
                continue
            cmd, arg = parts
            if cmd != 'new':
                continue  # zero/erase: sparse holes already read as zero
            for a, b in parse_ranges(arg):
                dst.seek(a * BLK)
                remaining = (b - a) * BLK
                while remaining:
                    chunk = src.read(min(1 << 22, remaining))
                    if not chunk:
                        raise SystemExit(f"{newdat} ran out at block {a}")
                    dst.write(chunk)
                    remaining -= len(chunk)
                written += b - a
    print(f"{out}: version {ver}, {written} data blocks, image {max_blk * BLK} bytes")


if __name__ == '__main__':
    main(*sys.argv[1:4])
