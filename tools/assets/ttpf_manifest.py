#!/usr/bin/env python3
"""Offline manifest and budget planner for GTA VI ``.ttpf`` texture stores.

The tool is read-only over the user's game copy: it parses the RDS5 header, the
chunk table and the ETPF descriptor index of each store and writes *derived
metadata* only (hashes, dimensions, formats, byte sizes). It never writes
texture payloads and it refuses to put its output inside the repository.

Two subcommands:

    python tools/assets/ttpf_manifest.py scan  <game_root> --out <dir>
    python tools/assets/ttpf_manifest.py plan  <dir> [--vram-gib 5] [--ceiling 1024]

``scan`` writes ``manifest.bin`` (fixed records for a runtime), ``stores.json``,
``summary.json`` and, with ``--csv``, ``textures.csv`` for spreadsheets.

``plan`` reads ``manifest.bin`` and prints the disk/VRAM scenarios that the
asset pipeline design is built on: full chains, mip0 only, a resolution
ceiling, and a BC7->BC1 share, split by resident class and streaming cell.

Format notes (measured on the 1.0.2.1 package, 57 stores, 357,115 descriptors):

* ``RDS5`` header: ``u32 +4`` = chunk count (the last entry is a terminator),
  ``u32 +16`` = ETPF offset / 256, chunk table at ``+0x18`` (8 bytes each).
* Chunk entry ``(a, b)``: file offset ``(a & 0xFFFFFF) << 8``, codec in bits
  24-29 (``0x20`` zlib, ``0x04`` BC1 BCPack, ``0x0C`` BC3, ``0x10`` BC4,
  ``0x14`` BC5, ``0x18`` BC6H, ``0x1C`` BC7).
* ``ETPF``: ``u32 +8`` = texture count, then ``count`` 16-byte descriptors,
  then ``count`` sorted ``u64`` texture hashes.
* Descriptor: width-1 (14 bits), height-1 (14), mips-1 (4); DXGI format in
  bits 3-10 of the second dword with bit 7 set for cube maps, array size-1 in
  bits 10-19, dimension in bits 20-23, tile mode in bits 24-27.
* Tile modes 0 = ``SW_64KB_D``, 1-3 = ``SW_4KB_S``, 9-12 = cube-map variants.
  The payload is AMD Gfx10 tiled; this tool reports linear sizes and keeps the
  tile mode for the baker.

Nothing here decrypts an RPF9 table of contents or touches protected data.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAGIC_RDS5 = b"RDS5"
MAGIC_ETPF = b"ETPF"
MANIFEST_MAGIC = b"GT6AMF01"
MANIFEST_VERSION = 1
RECORD_SIZE = 64

# DXGI format -> (bytes per element, block side in texels, name).  Block side 4
# means BC1-BC7 (8 or 16 bytes per 4x4 block).
FORMATS: dict[int, tuple[int, int, str]] = {
    1: (16, 1, "R32G32B32A32_FLOAT"),
    2: (16, 1, "R32G32B32A32_UINT"),
    3: (16, 1, "R32G32B32A32_SINT"),
    10: (8, 1, "R16G16B16A16_FLOAT"),
    11: (8, 1, "R16G16B16A16_UNORM"),
    12: (8, 1, "R16G16B16A16_UINT"),
    13: (8, 1, "R16G16B16A16_SNORM"),
    14: (8, 1, "R16G16B16A16_SINT"),
    28: (4, 1, "R8G8B8A8_UNORM"),
    29: (4, 1, "R8G8B8A8_UNORM_SRGB"),
    30: (4, 1, "R8G8B8A8_UINT"),
    34: (8, 1, "R16G16_FLOAT"),
    35: (8, 1, "R16G16_UNORM"),
    41: (4, 1, "R32_FLOAT"),
    42: (4, 1, "R32_UINT"),
    43: (4, 1, "R32_SINT"),
    49: (4, 1, "R8G8_UNORM"),
    50: (4, 1, "R8G8_UINT"),
    54: (2, 1, "R16_FLOAT"),
    56: (2, 1, "R16_UNORM"),
    57: (2, 1, "R16_UINT"),
    61: (1, 1, "R8_UNORM"),
    65: (1, 1, "A8_UNORM"),
    70: (8, 4, "BC1_TYPELESS"),
    71: (8, 4, "BC1_UNORM"),
    72: (8, 4, "BC1_UNORM_SRGB"),
    73: (16, 4, "BC2_TYPELESS"),
    74: (16, 4, "BC2_UNORM"),
    75: (16, 4, "BC2_UNORM_SRGB"),
    76: (16, 4, "BC3_TYPELESS"),
    77: (16, 4, "BC3_UNORM"),
    78: (16, 4, "BC3_UNORM_SRGB"),
    79: (8, 4, "BC4_TYPELESS"),
    80: (8, 4, "BC4_UNORM"),
    81: (8, 4, "BC4_SNORM"),
    82: (16, 4, "BC5_TYPELESS"),
    83: (16, 4, "BC5_UNORM"),
    84: (16, 4, "BC5_SNORM"),
    85: (2, 1, "B5G6R5_UNORM"),
    86: (2, 1, "B5G5R5A1_UNORM"),
    87: (4, 1, "B8G8R8A8_UNORM"),
    88: (4, 1, "B8G8R8A8_UNORM_SRGB"),
    91: (4, 1, "B8G8R8X8_UNORM"),
    93: (4, 1, "B8G8R8X8_UNORM_SRGB"),
    94: (16, 4, "BC6H_TYPELESS"),
    95: (16, 4, "BC6H_UF16"),
    96: (16, 4, "BC6H_SF16"),
    97: (16, 4, "BC7_TYPELESS"),
    98: (16, 4, "BC7_UNORM"),
    99: (16, 4, "BC7_UNORM_SRGB"),
    115: (2, 1, "B5G6R5_UNORM"),
    116: (4, 1, "B8G8R8A8_UNORM"),
    117: (4, 1, "B8G8R8A8_UNORM_SRGB"),
}

FAMILY = {
    "BC1_TYPELESS": "BC1", "BC1_UNORM": "BC1", "BC1_UNORM_SRGB": "BC1",
    "BC2_TYPELESS": "BC2", "BC2_UNORM": "BC2", "BC2_UNORM_SRGB": "BC2",
    "BC3_TYPELESS": "BC3", "BC3_UNORM": "BC3", "BC3_UNORM_SRGB": "BC3",
    "BC4_TYPELESS": "BC4", "BC4_UNORM": "BC4", "BC4_SNORM": "BC4",
    "BC5_TYPELESS": "BC5", "BC5_UNORM": "BC5", "BC5_SNORM": "BC5",
    "BC6H_TYPELESS": "BC6H", "BC6H_UF16": "BC6H", "BC6H_SF16": "BC6H",
    "BC7_TYPELESS": "BC7", "BC7_UNORM": "BC7", "BC7_UNORM_SRGB": "BC7",
}

# Resident class -> priority.  The runtime may override; this is the default
# the planner uses.  Higher is more important.
PRIORITY = {
    "global:ui": 3,
    "global:lighting": 3,
    "global:graphics": 3,
    "global:vfx": 2,
    "global:weapons": 2,
    "global:vehicles": 2,
    "global:peds": 2,
    "global:props": 1,
    "cell:interiors": 1,
    "cell:maps": 0,
    "cell:terrain": 0,
    "other": 1,
}


@dataclass
class Texture:
    hash: int
    pool: int
    width: int
    height: int
    mips: int
    dxgi: int
    cube: bool
    array_size: int
    dim: int
    tile: int
    flags: int
    page: int
    cell: str
    priority: int


@dataclass
class Store:
    path: str
    rel: str
    size: int
    chunks: int
    etpf: int
    count: int
    vsize: int
    codec_chunks: dict[int, int] = field(default_factory=dict)
    codec_bytes: dict[int, int] = field(default_factory=dict)
    textures: list[Texture] = field(default_factory=list)


def u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def cell_of(rel: str) -> str:
    """Streaming cell of a store, from its package path.

    Maps and terrain are split into 8 tiles each (``ttdb_maps_3_7``), interiors
    into 4; everything else is global.  The rule is deliberately textual so a
    renamed dump still classifies by its directory.
    """
    p = rel.replace("\\", "/").lower()
    if "/interiors/" in p:
        return "cell:interiors"
    if "/terrain/" in p:
        return "cell:terrain"
    if "/maps/" in p:
        return "cell:maps"
    for name in ("vehicles", "peds", "props", "weapons", "ui", "vfx", "lighting", "graphics"):
        if f"/{name}/" in p:
            return f"global:{name}"
    return "other"


def format_of(dxgi: int) -> tuple[int, int, str] | None:
    return FORMATS.get(dxgi)


def mip_sizes(width: int, height: int, mips: int, dxgi: int, slices: int) -> list[int]:
    """Linear byte size of every mip, largest first (DDS order)."""
    fmt = format_of(dxgi)
    if fmt is None:
        return []
    bpe, block, _ = fmt
    out = []
    for i in range(mips):
        w = max(1, width >> i)
        h = max(1, height >> i)
        bw = max(1, (w + block - 1) // block)
        bh = max(1, (h + block - 1) // block)
        out.append(bw * bh * bpe * slices)
    return out


def full_chain(width: int, height: int, mips: int, dxgi: int, slices: int) -> int:
    return sum(mip_sizes(width, height, mips, dxgi, slices))


def chain_at_ceiling(width: int, height: int, dxgi: int, slices: int,
                     ceiling: int | None) -> list[int]:
    """Mip sizes after resampling so the largest side is at most ``ceiling``."""
    if ceiling:
        width = min(width, ceiling)
        height = min(height, ceiling)
    mips = max(1, max(width, height).bit_length())
    return mip_sizes(width, height, mips, dxgi, slices)


def read_store(path: Path, root: Path, pool: int) -> Store:
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(0x200)
        if head[:4] != MAGIC_RDS5:
            raise ValueError(f"{path}: not RDS5")
        chunks = u32(head, 4)
        vsize = u32(head, 8) | ((u32(head, 0xC) & 0xFF) << 32)
        etpf = u32(head, 0x10) * 256
        f.seek(0x18)
        raw = f.read(8 * chunks)
        entries = [struct.unpack_from("<II", raw, 8 * i) for i in range(chunks)]
        f.seek(etpf)
        hdr = f.read(16)
        if hdr[:4] != MAGIC_ETPF:
            raise ValueError(f"{path}: no ETPF at {etpf:#x}")
        count = u32(hdr, 8)
        if count > 4_000_000:
            raise ValueError(f"{path}: implausible texture count {count}")
        body = f.read(count * 16)
        hashes = f.read(count * 8)

    rel = str(path.relative_to(root)).replace("\\", "/")
    store = Store(path=str(path), rel=rel, size=size, chunks=chunks,
                  etpf=etpf, count=count, vsize=vsize)

    # Chunk table: drop the zero terminator, then measure stored bytes.
    if entries and entries[-1][0] == 0:
        entries = entries[:-1]
    store.chunks = len(entries)
    offsets = [(a & 0xFFFFFF) << 8 for a, _ in entries]
    for i, (a, _b) in enumerate(entries):
        end = offsets[i + 1] if i + 1 < len(offsets) else size
        stored = max(0, end - offsets[i])
        codec = (a >> 24) & 0x3F
        store.codec_chunks[codec] = store.codec_chunks.get(codec, 0) + 1
        store.codec_bytes[codec] = store.codec_bytes.get(codec, 0) + stored

    cell = cell_of(rel)
    hs = struct.unpack(f"<{count}Q", hashes) if count else ()
    for i in range(count):
        d0, d1 = struct.unpack_from("<II", body, i * 16)
        loc = struct.unpack_from("<Q", body, i * 16 + 8)[0]
        width = (d0 & 0x3FFF) + 1
        height = ((d0 >> 14) & 0x3FFF) + 1
        mips = ((d0 >> 28) & 0xF) + 1
        raw_fmt = (d1 >> 3) & 0xFF
        dxgi = raw_fmt & 0x7F
        cube = bool(raw_fmt & 0x80) or ((d1 >> 20) & 0xF) == 4
        array_size = ((d1 >> 10) & 0x3FF) + 1
        dim = (d1 >> 20) & 0xF
        tile = (d1 >> 24) & 0xF
        # The console stores cubes as a 6-slice array; the descriptor's array
        # field is already 6 on the samples, but keep the invariant explicit.
        slices = 6 if cube else array_size
        mips = min(mips, max(1, max(width, height).bit_length()))
        store.textures.append(Texture(
            hash=hs[i], pool=pool, width=width, height=height, mips=mips,
            dxgi=dxgi, cube=cube, array_size=slices, dim=dim, tile=tile,
            flags=d1 & 0x7, page=loc & 0x1FFFFF, cell=cell,
            priority=PRIORITY.get(cell, 1),
        ))
    return store


def find_stores(root: Path) -> list[Path]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".ttpf"):
                out.append(Path(dirpath) / name)
    out.sort()
    return out


def refuse_repo(out: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    try:
        out.resolve().relative_to(repo)
    except ValueError:
        return
    sys.exit(f"refusing to write derived game metadata inside the repository: {out}")


def write_manifest(out: Path, stores: list[Store]) -> dict:
    """Fixed-record manifest, sorted by the 64-bit texture hash.

    Header (64 B):
        magic[8] "GT6AMF01", u32 version, u32 count, u32 record_size,
        u32 mip_entries, u32 pool_count, u32 reserved[3]
    Record (64 B), sorted by hash:
        u64 hash, u32 pool, u32 mip_index,
        u32 baked_bytes, u64 content_hash,
        u16 width, u16 height, u16 slices, u8 mips, u8 dxgi,
        u8 tile, u8 flags, u8 cell, u8 priority, u8 status, u8 reserved,
        u32 reserved2, u32 reserved3, u64 reserved4, 6 bytes of padding
    Mip table (12 B per entry): u64 offset, u32 length (linear, mip0 first).
    """
    records: list[tuple] = []
    mips: list[tuple[int, int]] = []
    cells: list[str] = []
    seen_hashes: set[int] = set()
    duplicates = 0
    for store in stores:
        for t in store.textures:
            if t.hash in seen_hashes:
                duplicates += 1
                continue
            seen_hashes.add(t.hash)
            sizes = mip_sizes(t.width, t.height, t.mips, t.dxgi, t.array_size)
            if not sizes:
                # Unknown format: keep the hash discoverable, but no mip table.
                records.append((
                    t.hash, t.pool, 0, 0, 0, t.width, t.height, t.array_size,
                    0, t.dxgi, t.tile, t.flags, cell_id(t.cell), t.priority, 4, 0,
                    0, 0, 0,
                ))
                continue
            idx = len(mips)
            offset = 0
            for s in sizes:
                mips.append((offset, s))
                offset = align(offset, 4096)
                offset += s
            baked = offset
            cells.append(t.cell)
            records.append((
                t.hash, t.pool, idx, baked, 0, t.width, t.height, t.array_size,
                t.mips, t.dxgi, t.tile, t.flags, cell_id(t.cell), t.priority, 0, 0,
                0, 0, 0,
            ))
    records.sort(key=lambda r: r[0])

    cell_names = sorted({c for c in cells})
    with (out / "manifest.bin").open("wb") as f:
        f.write(struct.pack("<8sIIIIIIII24x", MANIFEST_MAGIC, MANIFEST_VERSION,
                            len(records), RECORD_SIZE, len(mips),
                            len(stores), 0, 0, 0))
        for r in records:
            f.write(struct.pack("<QIIIQHHHBBBBBBBBIIQ6x", *r))
        for off, length in mips:
            f.write(struct.pack("<QI", off, length))
    return {
        "records": len(records),
        "mip_entries": len(mips),
        "duplicate_hashes": duplicates,
        "cells": cell_names,
        "bytes": (out / "manifest.bin").stat().st_size,
    }


def cell_id(name: str) -> int:
    if name == "cell:maps":
        return 1
    if name == "cell:terrain":
        return 9
    if name == "cell:interiors":
        return 17
    if name == "global:ui":
        return 21
    if name == "global:lighting":
        return 22
    if name == "global:graphics":
        return 23
    if name == "global:weapons":
        return 24
    if name == "global:vehicles":
        return 25
    if name == "global:peds":
        return 26
    if name == "global:props":
        return 27
    if name == "global:vfx":
        return 28
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    root: Path = args.game_root
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    out: Path = args.out
    refuse_repo(out)
    out.mkdir(parents=True, exist_ok=True)

    paths = find_stores(root)
    if not paths:
        print(f"no .ttpf under {root}", file=sys.stderr)
        return 2
    stores: list[Store] = []
    for i, path in enumerate(paths):
        try:
            stores.append(read_store(path, root, i))
        except (ValueError, struct.error, OSError) as e:
            print(f"skip: {e}", file=sys.stderr)

    total = 0
    total_mip0 = 0
    unknown: dict[int, int] = {}
    formats: dict[str, int] = {}
    counts: dict[str, int] = {}
    for store in stores:
        for t in store.textures:
            fmt = format_of(t.dxgi)
            if fmt is None:
                unknown[t.dxgi] = unknown.get(t.dxgi, 0) + 1
                continue
            b = full_chain(t.width, t.height, t.mips, t.dxgi, t.array_size)
            total += b
            total_mip0 += mip_sizes(t.width, t.height, 1, t.dxgi, t.array_size)[0]
            name = fmt[2]
            family = FAMILY.get(name, name)
            formats[family] = formats.get(family, 0) + b
            counts[family] = counts.get(family, 0) + 1

    info = write_manifest(out, stores)
    (out / "stores.json").write_text(json.dumps([{
        "id": i,
        "path": s.rel,
        "file_bytes": s.size,
        "virtual_bytes": s.vsize,
        "chunks": s.chunks,
        "textures": len(s.textures),
        "codecs": {f"0x{k:02x}": v for k, v in sorted(s.codec_chunks.items())},
        "codec_bytes": {f"0x{k:02x}": v for k, v in sorted(s.codec_bytes.items())},
    } for i, s in enumerate(stores)], indent=1), encoding="utf-8")

    summary = {
        "stores": len(stores),
        "descriptors": sum(len(s.textures) for s in stores),
        "unique_hashes": info["records"],
        "duplicate_hashes": info["duplicate_hashes"],
        "unknown_formats": {str(k): v for k, v in sorted(unknown.items())},
        "full_chain_gib": total / 2**30,
        "mip0_gib": total_mip0 / 2**30,
        "store_bytes_gib": sum(s.size for s in stores) / 2**30,
        "formats_gib": {k: round(v / 2**30, 3) for k, v in sorted(formats.items())},
        "formats_count": dict(sorted(counts.items())),
        "manifest_bytes": info["bytes"],
        "cells": info["cells"],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    if args.csv:
        import csv
        with (out / "textures.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["hash", "pool", "store", "cell", "priority", "width", "height",
                        "mips", "dxgi", "format", "family", "cube", "slices", "dim",
                        "tile", "flags", "mip0_bytes", "chain_bytes"])
            for store in stores:
                for t in store.textures:
                    fmt = format_of(t.dxgi)
                    if fmt is None:
                        continue
                    w.writerow([f"{t.hash:016x}", t.pool, store.rel, t.cell, t.priority,
                                t.width, t.height, t.mips, t.dxgi, fmt[2],
                                FAMILY.get(fmt[2], fmt[2]), int(t.cube), t.array_size,
                                t.dim, t.tile, t.flags,
                                mip_sizes(t.width, t.height, 1, t.dxgi, t.array_size)[0],
                                full_chain(t.width, t.height, t.mips, t.dxgi, t.array_size)])

    print(f"stores       {summary['stores']}")
    print(f"descriptors  {summary['descriptors']}  unique {summary['unique_hashes']}"
          f"  duplicates {summary['duplicate_hashes']}")
    print(f"full chains  {summary['full_chain_gib']:.2f} GiB"
          f"   mip0 {summary['mip0_gib']:.2f} GiB")
    print(f"store files  {summary['store_bytes_gib']:.2f} GiB")
    print(f"manifest     {info['bytes'] / 2**20:.1f} MiB -> {out / 'manifest.bin'}")
    if unknown:
        print(f"unknown fmt  {unknown}")
    return 0


def read_manifest(path: Path) -> list[dict]:
    b = path.read_bytes()
    magic, version, count, record_size, mip_entries, pools, *_ = struct.unpack_from(
        "<8sIIIIIII", b, 0)
    if magic != MANIFEST_MAGIC or version != MANIFEST_VERSION:
        raise ValueError(f"{path}: not a {MANIFEST_MAGIC.decode()} v{MANIFEST_VERSION} manifest")
    if record_size != RECORD_SIZE:
        raise ValueError(f"{path}: record size {record_size}")
    need = 64 + count * record_size + mip_entries * 12
    if len(b) < need:
        raise ValueError(f"{path}: truncated ({len(b)} < {need})")
    base = 64
    mip_base = base + count * record_size
    out = []
    for i in range(count):
        (h, pool, mip_index, baked, content, width, height, slices, mips, dxgi,
         tile, flags, cell, priority, status, _r, _r2, _r3, _r4) = struct.unpack_from(
            "<QIIIQHHHBBBBBBBBIIQ6x", b, base + i * record_size)
        sizes = []
        off = 0
        for j in range(mips):
            _, length = struct.unpack_from("<QI", b, mip_base + (mip_index + j) * 12)
            sizes.append(length)
        out.append(dict(hash=h, pool=pool, width=width, height=height, slices=slices,
                        mips=mips, dxgi=dxgi, tile=tile, flags=flags, cell=cell,
                        priority=priority, status=status, sizes=sizes))
    return out


CELL_NAMES = {
    0: "other", 1: "cell:maps", 9: "cell:terrain", 17: "cell:interiors",
    21: "global:ui", 22: "global:lighting", 23: "global:graphics",
    24: "global:weapons", 25: "global:vehicles", 26: "global:peds",
    27: "global:props", 28: "global:vfx",
}


def cmd_plan(args: argparse.Namespace) -> int:
    manifest = args.dir / "manifest.bin"
    if not manifest.is_file():
        print(f"run scan first: {manifest}", file=sys.stderr)
        return 2
    rows = read_manifest(manifest)

    ceiling = args.ceiling if args.ceiling and args.ceiling > 0 else None
    scenarios = {"as-is": 0, "mip0": 0, "ceiling": 0}
    bc7 = 0
    rgba = 0
    by_cell: dict[str, list[int]] = {}
    for r in rows:
        fmt = format_of(r["dxgi"])
        if fmt is None:
            continue
        family = FAMILY.get(fmt[2], fmt[2])
        full = sum(r["sizes"])
        mip0 = r["sizes"][0] if r["sizes"] else 0
        chain = chain_at_ceiling(r["width"], r["height"], r["dxgi"],
                                 r["slices"], ceiling)
        cfull = sum(chain)
        scenarios["as-is"] += full
        scenarios["mip0"] += mip0
        scenarios["ceiling"] += cfull
        if family == "BC7":
            bc7 += cfull
        elif family in ("RGBA8", "BGRA8"):
            rgba += cfull
        cell = CELL_NAMES.get(r["cell"], "other")
        acc = by_cell.setdefault(cell, [0, 0, 0, 0, 0])
        acc[0] += cfull
        acc[1] += sum(chain[1:])
        acc[2] += sum(chain[2:])
        acc[3] += sum(chain[3:])

    share = max(0.0, min(1.0, args.bc1_share))
    ceiling_bc1 = scenarios["ceiling"] - bc7 * share / 2 - rgba * 0.75
    print(f"textures           {len(rows)}")
    print(f"as-is full chain   {scenarios['as-is'] / 2**30:8.2f} GiB")
    print(f"mip0 only          {scenarios['mip0'] / 2**30:8.2f} GiB")
    label = f"ceiling {ceiling}px" if ceiling else "ceiling none"
    print(f"{label:<18} {scenarios['ceiling'] / 2**30:8.2f} GiB")
    print(f"  BC7->BC1 {share:.0%}    {ceiling_bc1 / 2**30:8.2f} GiB"
          f"  (saves {(scenarios['ceiling'] - ceiling_bc1) / 2**30:.2f})")
    print()
    print(f"{'class':<18}{'full':>9}{'>=mip1':>9}{'>=mip2':>9}{'>=mip3':>9}  GiB")
    for name, v in sorted(by_cell.items(), key=lambda kv: -kv[1][0]):
        print(f"{name:<18}{v[0]/2**30:9.2f}{v[1]/2**30:9.2f}{v[2]/2**30:9.2f}{v[3]/2**30:9.2f}")
    print()
    vram = args.vram_gib * 2**30
    print(f"VRAM budget {args.vram_gib:.2f} GiB -> "
          f"{vram / scenarios['ceiling']:.1%} of the capped full set, "
          f"{vram / max(1, scenarios['mip0']):.1%} of mip0")
    disk = args.disk_free_gb * 1e9
    headroom = max(0.0, min(0.9, args.headroom))
    ratio = max(0.2, min(1.5, args.disk_ratio))
    on_disk = ceiling_bc1 * ratio
    limit = disk * (1.0 - headroom)
    margin = limit - on_disk
    print(f"on disk     {on_disk / 1e9:8.1f} GB raw x {ratio:.2f} compression")
    print(f"disk free   {args.disk_free_gb:.1f} GB, keep {headroom:.0%} free -> "
          f"{'fits' if margin >= 0 else 'does not fit'}"
          f" ({margin / 1e9:+.1f} GB margin)")
    if args.json:
        (args.dir / "plan.json").write_text(json.dumps({
            "ceiling": ceiling,
            "bc1_share": share,
            "scenarios": {k: v for k, v in scenarios.items()},
            "ceiling_bc1": ceiling_bc1,
            "by_cell": {k: v for k, v in by_cell.items()},
            "vram_gib": args.vram_gib,
            "disk_free_gb": args.disk_free_gb,
            "disk_ratio": ratio,
            "on_disk_bytes": on_disk,
        }, indent=1), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="index every .ttpf store and write the manifest")
    scan.add_argument("game_root", type=Path)
    scan.add_argument("--out", type=Path, required=True,
                      help="output directory (outside the repository)")
    scan.add_argument("--csv", action="store_true", help="also write textures.csv")
    scan.set_defaults(func=cmd_scan)

    plan = sub.add_parser("plan", help="print disk/VRAM scenarios from a manifest")
    plan.add_argument("dir", type=Path, help="directory written by scan")
    plan.add_argument("--ceiling", type=int, default=1024,
                      help="resample the largest side to this many texels (0: off)")
    plan.add_argument("--bc1-share", type=float, default=0.6,
                      help="share of BC7 bytes re-encoded as BC1 (0..1)")
    plan.add_argument("--vram-gib", type=float, default=4.2,
                      help="texture budget for residency percentages (native slice: 4.2)")
    plan.add_argument("--disk-free-gb", type=float, default=119.0)
    plan.add_argument("--disk-ratio", type=float, default=0.85,
                      help="compressed bytes per raw byte in the pool (measure on 3 stores)")
    plan.add_argument("--headroom", type=float, default=0.10,
                      help="share of the free disk the bake must leave untouched (0..0.9)")
    plan.add_argument("--json", action="store_true", help="write plan.json")
    plan.set_defaults(func=cmd_plan)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
