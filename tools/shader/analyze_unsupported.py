#!/usr/bin/env python3
"""Categorise the shaders VItoriaBr/fxceless cannot translate.

The runtime reports one line per failure, either from `victory warm --list`
(``does not translate: <file>: <reason>``) or from
`victory translate --list` (``<file> <stage> ... #<hash>  <reason>``).  This
tool groups those lines by stage and by the translator's own reason string,
then marks each group with a first-pass impact class.

It can also inspect a folder of failure dumps made with
``VICTORY_FAIL_DUMP=<dir>``.  Those are DXBC containers; the tool reads only
their metadata (FSSM slot table, PAL stage descriptors, code sizes and wave
width).  It never prints or copies shader code and never needs the game's
files to be in the repository.

Examples
--------
    python tools/shader/analyze_unsupported.py warm-list.txt --markdown
    python tools/shader/analyze_unsupported.py --dumps D:\\out\\fail --json out.json
    python tools/shader/analyze_unsupported.py --game-log game-stderr.log --json out.json
    python tools/shader/analyze_unsupported.py --self-test

The impact class is a triage hint, not a measurement.  A compute failure that
produces data consumed by a draw is more important than a voxelisation GS whose
output is only used for indirect lighting; only a run's ``first bind`` /
``DROPPED`` lines can settle that.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ABSENT = 0xDEADBEEFDEADBEEF
FSSM_HEADER = 0x10
RECORD_SIZE = 0x54
PAL_TABLE = 0x100
PAL_RECORD = 0x88
PAL_TAG = 0x000000C000020000
PAL_MASK = 0xFFFFFFFFFFFF0000

# FSSM payload: stage -> offset of its record pointer.
STAGE_SLOTS = (
    (0x08, "Ls"),
    (0x10, "Hs"),
    (0x18, "Es"),
    (0x20, "Gs"),
    (0x28, "Vs"),
    (0x30, "Ps"),
    (0x48, "Ms"),
    (0x60, "Cs"),
)

PAL_HW = {0: "ls", 1: "hs", 2: "es", 3: "gs", 4: "vs", 5: "ps", 6: "cs", 7: "ngg"}
PAL_API = {0: "vs", 1: "ps", 2: "gs", 3: "cs", 6: "ms"}


# --------------------------------------------------------------------------
# binary metadata readers
# --------------------------------------------------------------------------


def _u16(data: bytes, at: int) -> int:
    return struct.unpack_from("<H", data, at)[0]


def _u32(data: bytes, at: int) -> int:
    return struct.unpack_from("<I", data, at)[0]


def _u64(data: bytes, at: int) -> int:
    return struct.unpack_from("<Q", data, at)[0]


def parse_dxbc(data: bytes) -> dict[str, bytes]:
    """FourCC -> body of a DXBC container (the parts this tool needs)."""
    if len(data) < 0x20 or data[:4] != b"DXBC":
        raise ValueError("not a DXBC container")
    total = _u32(data, 0x18)
    if total > len(data) or total < 0x20:
        raise ValueError("DXBC size disagrees")
    count = _u32(data, 0x1C)
    if count > 256:
        raise ValueError("implausible DXBC part count")
    out: dict[str, bytes] = {}
    for i in range(count):
        at = 0x20 + 4 * i
        off = _u32(data, at)
        if off + 8 > total:
            raise ValueError("DXBC part outside the container")
        fourcc = data[off : off + 4].decode("latin-1")
        size = _u32(data, off + 4)
        body = data[off + 8 : off + 8 + size]
        if len(body) != size:
            raise ValueError("DXBC part body truncated")
        out[fourcc] = body
    return out


def parse_xdat(dxil: bytes) -> list[tuple[int, int, int]]:
    """(tag, offset, size) of each XDAT entry; offsets are DXIL-relative."""
    if dxil[0x18:0x1C] != b"XDAT":
        return []
    count = _u32(dxil, 0x1C)
    if count > 64:
        raise ValueError("implausible XDAT entry count")
    out = []
    for i in range(count):
        at = 0x18 + 0x0C + 0x0C * i
        tag = _u32(dxil, at)
        off = _u32(dxil, at + 4)
        size = _u32(dxil, at + 8)
        if off + size > len(dxil):
            raise ValueError("XDAT entry outside the DXIL part")
        out.append((tag, off, size))
    return out


def unpack_xbch(blob: bytes) -> bytes:
    """XBCH v3 zlib payload -> FSSM bytes."""
    if blob[:4] != b"XBCH":
        raise ValueError("not an XBCH payload")
    if _u32(blob, 4) != 3:
        raise ValueError("unknown XBCH version")
    packed = _u64(blob, 8)
    unpacked = _u64(blob, 16)
    if packed > len(blob) - 0x18:
        raise ValueError("XBCH packed size outside the blob")
    if unpacked > (64 << 20):
        raise ValueError("implausible XBCH unpacked size")
    stream = blob[0x18 : 0x18 + packed]
    out = zlib.decompress(stream)
    if len(out) != unpacked:
        raise ValueError("XBCH decompressed size disagrees")
    return out


def parse_fssm(blob: bytes) -> dict:
    """Stage records, PAL descriptors and wave width of one FSSM blob."""
    if blob[:4] != b"FSSM":
        raise ValueError("not an FSSM blob")
    version = _u16(blob, 4)
    if version != 0x101:
        raise ValueError(f"unknown FSSM version {version:#x}")
    payload = blob[FSSM_HEADER:]
    if _u64(blob, 8) != len(payload):
        raise ValueError("FSSM payload size disagrees")
    if _u64(payload, 0) != 6:
        raise ValueError("unexpected FSSM graphics-slot count")

    records = []
    for slot, stage in STAGE_SLOTS:
        start = _u64(payload, slot)
        if start == ABSENT:
            continue
        if start + RECORD_SIZE > len(payload):
            raise ValueError(f"FSSM {stage} record outside the payload")
        record = payload[start : start + RECORD_SIZE]
        code_off = _u64(record, 0)
        code_size = _u64(record, 8)
        if code_off + code_size > len(payload):
            raise ValueError(f"FSSM {stage} code outside the payload")
        flags = _u32(record, 0x14)
        records.append(
            {
                "stage": stage,
                "record_offset": start,
                "code_offset": code_off,
                "code_size": code_size,
                "wave64": (flags & 0x20) == 0,
            }
        )

    pal = []
    for k in range(16):
        at = PAL_TABLE + k * PAL_RECORD
        if at + 8 > len(blob):
            break
        tag = _u64(blob, at)
        if tag == 0 or (tag & PAL_MASK) != PAL_TAG:
            break
        api_id = (tag >> 8) & 0xFF
        hw_id = tag & 0xFF
        pal.append(
            {
                "api_id": api_id,
                "api": PAL_API.get(api_id),
                "hardware_id": hw_id,
                "hardware": PAL_HW.get(hw_id),
            }
        )

    stages = [r["stage"] for r in records]
    pal_stages = [p["api"] or p["hardware"] for p in pal]
    return {
        "version": version,
        "records": records,
        "pal": pal,
        "stages": stages,
        "pal_stages": pal_stages,
        "has_gs": "Gs" in stages or "gs" in pal_stages,
        "has_es": "Es" in stages or "es" in pal_stages,
        "has_vs": "Vs" in stages or "vs" in pal_stages,
        "has_ps": "Ps" in stages or "ps" in pal_stages,
        "has_ms": "Ms" in stages or "ms" in pal_stages,
        "has_cs": "Cs" in stages or "cs" in pal_stages,
        "wave64": any(r["wave64"] for r in records),
        "code_size": sum(r["code_size"] for r in records),
    }


def inspect_container(data: bytes) -> dict:
    """Metadata of a DXBC/.cdxil failure dump."""
    parts = parse_dxbc(data)
    dxil = parts.get("DXIL")
    if dxil is None:
        return {"error": "no DXIL part", "stages": [], "has_gs": False}
    programs = []
    for tag, off, size in parse_xdat(dxil):
        if tag != 0x0D:
            continue
        fssm = unpack_xbch(dxil[off : off + size])
        programs.append(parse_fssm(fssm))
    if not programs:
        return {"error": "no XBCH/FSSM payload", "stages": [], "has_gs": False}
    stages = sorted({s for p in programs for s in p["stages"]})
    pal_stages = sorted({s for p in programs for s in p["pal_stages"] if s})
    return {
        "programs": len(programs),
        "stages": stages,
        "pal_stages": pal_stages,
        "has_gs": any(p["has_gs"] for p in programs),
        "has_es": any(p["has_es"] for p in programs),
        "has_vs": any(p["has_vs"] for p in programs),
        "has_ps": any(p["has_ps"] for p in programs),
        "has_ms": any(p["has_ms"] for p in programs),
        "has_cs": any(p["has_cs"] for p in programs),
        "wave64": any(p["wave64"] for p in programs),
        "code_size": sum(p["code_size"] for p in programs),
        "details": programs,
    }


# --------------------------------------------------------------------------
# log parsing
# --------------------------------------------------------------------------

STAGE_RE = re.compile(r"\b(Vs|Ps|Cs|Gs|Ms|Es|Ls|Hs)\b")
NAME_STAGE_RE = re.compile(r"\b(PS|CS|GS|VS|MS|ES|LS|HS)_")
HASH_RE = re.compile(r"#([0-9a-fA-F]{16})")
CODE_RE = re.compile(r"~([0-9a-fA-F]{8})")
WARM_RE = re.compile(r"^does not translate: (.*?): (.*)$")
LOG_FAIL_RE = re.compile(
    r'stage="?(?P<stage>[a-z]+)"?.*hash=(?P<hash>[0-9a-fA-F]{16}).*'
    r'error=(?P<error>.*)'
)
FIRST_BIND_RE = re.compile(
    r'stage="?(?P<stage>[a-z]+)"?.*hash=(?P<hash>[0-9a-fA-F]{16}).*first bind'
)


def guess_stage(label: str) -> str | None:
    """Stage from ` Ps ` (translate labels) or from a PS_/CS_/GS_ name."""
    m = STAGE_RE.search(label)
    if m:
        return m.group(1)
    m = NAME_STAGE_RE.search(label)
    if m:
        return m.group(1).capitalize()
    return None


def normalise_reason(reason: str) -> str:
    reason = reason.strip()
    reason = re.sub(r"^converter shader\.dxil v1:\s*", "", reason)
    reason = re.sub(r"^GFX10 code at 0x[0-9a-f]+:\s*", "", reason)
    reason = re.sub(r"\s+is not supported$", "", reason)
    reason = re.sub(r"^(resources|I/O|structure|emit|pipeline|validator):\s*", "", reason)
    return reason.strip()


def category(stage: str | None, reason: str, has_gs: bool = False) -> str:
    low = reason.lower()
    if "geometry stage" in low and has_gs:
        return "geometry_stage"
    if "without a vertex, pixel, compute or mesh program" in low:
        return "geometry_stage" if has_gs or stage in ("Gs", "Es") else "other"
    if "i/o of this stage" in low:
        return "geometry_stage" if stage in ("Gs", "Es") else "other"
    if "hardware sgpr" in low:
        if stage == "Ps":
            return "ps_hw_sgpr"
        if stage == "Cs":
            return "cs_hw_sgpr"
        return "hw_sgpr"
    if "lane mask" in low:
        return "cs_lane_mask" if stage == "Cs" else "lane_mask"
    if "gather4_l" in low:
        return "image_gather4_l"
    if "structured buffer of unknown stride" in low:
        return "unknown_stride"
    if "address in an sgpr" in low or "address not from a root parameter" in low:
        return "root_address"
    if "descriptor" in low:
        return "descriptor"
    if "64-bit image atomic" in low:
        return "image_atomic64"
    return "other"


def parse_warm_log(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        line = line.lstrip("\ufeff").rstrip("\r\n")
        m = WARM_RE.match(line)
        if not m:
            continue
        label, reason = m.group(1), m.group(2)
        rows.append(
            {
                "label": label,
                "stage": guess_stage(label),
                "reason": normalise_reason(reason),
                "raw_reason": reason.strip(),
                "hash": None,
                "container": None,
            }
        )
    return rows


def parse_translate_log(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        line = line.lstrip("\ufeff").rstrip("\r\n")
        if "  " not in line:
            continue
        label, _, reason = line.rpartition("  ")
        if not label or not reason:
            continue
        hash_m = HASH_RE.search(label)
        rows.append(
            {
                "label": label,
                "stage": guess_stage(label),
                "reason": normalise_reason(reason),
                "raw_reason": reason.strip(),
                "hash": hash_m.group(1).lower() if hash_m else None,
                "container": label.strip(),
            }
        )
    return rows


def parse_game_log(lines: list[str]) -> dict[str, dict]:
    """hash -> {stage, binds, error}; only lines that carry a 16-digit hash."""
    out: dict[str, dict] = defaultdict(dict)
    for line in lines:
        m = FIRST_BIND_RE.search(line)
        if m:
            h = m.group("hash").lower()
            out[h].setdefault("stage", m.group("stage"))
            out[h]["binds"] = out[h].get("binds", 0) + 1
            continue
        m = LOG_FAIL_RE.search(line)
        if m:
            h = m.group("hash").lower()
            out[h].setdefault("stage", m.group("stage"))
            out[h]["error"] = normalise_reason(m.group("error"))
    return dict(out)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

IMPACT = {
    "geometry_stage": "P1 — voxelizacja/GI; brak pipeline = brak draw/dispatch, ale nie główna geometria",
    "ps_hw_sgpr": "P1 — zależy od użycia; sprawdź first bind i czy PS nie czyta prim_mask/lds_offset",
    "cs_hw_sgpr": "P1 — jeśli producer danych dla drawów, podnieś do P0",
    "cs_lane_mask": "P0/P1 — maska może zmieniać dane (liczniki, sloty); sprawdź first bind",
    "lane_mask": "P1 — zależy od etapu i użycia maski",
    "hw_sgpr": "P1 — niezidentyfikowany hardware SGPR",
    "image_gather4_l": "P1 — tekstury; zwykle wizualne, ale może karmić kolejne passy",
    "unknown_stride": "P1 — deskryptor/structured buffer; może dawać złe dane",
    "root_address": "P1 — adres/deskryptor; może dawać złe dane",
    "descriptor": "P1 — deskryptor; może dawać złe dane",
    "image_atomic64": "P1 — atomics 64-bit; jeśli producer, P0",
    "other": "P2 — triage: brak kategorii, zobacz reason",
}


def summarise(rows: list[dict], game: dict[str, dict] | None = None) -> dict:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[category(r.get("stage"), r.get("reason", ""), r.get("has_gs", False))].append(r)
    summary = []
    for cat, items in sorted(by_cat.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        stages = Counter((i.get("stage") or "?") for i in items)
        reasons = Counter(i["reason"] for i in items)
        hashes = sorted({i["hash"] for i in items if i.get("hash")})
        binds = 0
        if game:
            binds = sum(game.get(h, {}).get("binds", 0) for h in hashes)
        summary.append(
            {
                "category": cat,
                "count": len(items),
                "stages": dict(stages),
                "top_reasons": reasons.most_common(5),
                "impact": IMPACT.get(cat, IMPACT["other"]),
                "hashes_sample": hashes[:12],
                "first_bind_lines": binds,
                "examples": [i.get("label") or i.get("container") for i in items[:3]],
            }
        )
    return {"total": len(rows), "categories": summary}


def print_markdown(report: dict) -> None:
    print("| Kategoria | Liczba | Etapy | Główny reason | Wpływ | Przykład |")
    print("|---|---:|---|---|---|---|")
    for c in report["categories"]:
        stages = ", ".join(f"{k}:{v}" for k, v in sorted(c["stages"].items()))
        reason = c["top_reasons"][0][0].replace("|", "\\|") if c["top_reasons"] else ""
        example = (c["examples"][0] or "").replace("|", "\\|")
        impact = c["impact"]
        if c["first_bind_lines"]:
            impact += f" (first bind: {c['first_bind_lines']})"
        print(
            f"| `{c['category']}` | {c['count']} | {stages} | {reason} | {impact} | `{example}` |"
        )
    print(f"\n**Razem:** {report['total']} rekordów.")


def print_text(report: dict) -> None:
    print(f"Razem: {report['total']} rekordów\n")
    for c in report["categories"]:
        stages = ", ".join(f"{k}={v}" for k, v in sorted(c["stages"].items()))
        print(f"[{c['category']}] {c['count']}  ({stages})")
        print(f"  wpływ: {c['impact']}")
        for reason, n in c["top_reasons"]:
            print(f"  {n:>5}  {reason}")
        if c["hashes_sample"]:
            print(f"  hashe: {', '.join(c['hashes_sample'])}")
        if c["first_bind_lines"]:
            print(f"  first bind: {c['first_bind_lines']} linii")
        print()


# --------------------------------------------------------------------------
# dumps and self-test
# --------------------------------------------------------------------------


def inspect_dumps(root: Path) -> list[dict]:
    rows = []
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".cdxil", ".dxbc"))
    for path in files:
        try:
            info = inspect_container(path.read_bytes())
            info["file"] = str(path)
            info["category"] = "geometry_stage" if info.get("has_gs") else "other"
            rows.append(info)
        except Exception as exc:  # noqa: BLE001 - one bad dump must not stop the scan
            rows.append({"file": str(path), "error": str(exc), "category": "other"})
    return rows


def _build_dxbc(parts: list[tuple[bytes, bytes]]) -> bytes:
    table = 0x20 + 4 * len(parts)
    total = table + sum(8 + len(body) for _, body in parts)
    out = bytearray()
    out += b"DXBC"
    out += b"\0" * 16
    out += struct.pack("<HH", 1, 0)
    out += struct.pack("<II", total, len(parts))
    off = table
    for _, body in parts:
        out += struct.pack("<I", off)
        off += 8 + len(body)
    for fourcc, body in parts:
        out += fourcc
        out += struct.pack("<I", len(body))
        out += body
    return bytes(out)


def _build_fssm_gs() -> bytes:
    payload = bytearray(0x300)
    struct.pack_into("<Q", payload, 0, 6)
    for slot, _ in STAGE_SLOTS:
        struct.pack_into("<Q", payload, slot, ABSENT)
    record = 0x80
    struct.pack_into("<Q", payload, 0x20, record)  # GS slot
    struct.pack_into("<Q", payload, record + 0, 0x200)  # code offset
    struct.pack_into("<Q", payload, record + 8, 4)  # code size
    struct.pack_into("<I", payload, record + 0x14, 0)  # wave64
    blob = bytearray(b"FSSM")
    blob += struct.pack("<H", 0x101)
    blob += b"\0\0"
    blob += struct.pack("<Q", len(payload))
    blob += payload
    # PAL descriptor at 0x100: API gs (2), hardware gs (3).
    struct.pack_into("<Q", blob, 0x100, PAL_TAG | (2 << 8) | 3)
    return bytes(blob)


def _build_container() -> bytes:
    fssm = _build_fssm_gs()
    comp = zlib.compress(fssm)
    xbch = b"XBCH" + struct.pack("<III", 3, len(comp), 0)
    xbch += struct.pack("<I", len(fssm)) + b"\0\0\0\0"
    xbch += comp
    dxil = bytearray(0x18)
    dxil += b"XDAT"
    dxil += struct.pack("<II", 1, 0)
    blob_at = 0x18 + 12 + 12
    dxil += struct.pack("<III", 0x0D, blob_at, len(xbch))
    dxil += xbch
    return _build_dxbc([(b"DXIL", bytes(dxil))])


def self_test() -> int:
    data = _build_container()
    info = inspect_container(data)
    assert info["has_gs"], info
    assert "Gs" in info["stages"], info
    assert info["wave64"], info
    assert info["programs"] == 1, info

    rows = parse_warm_log(
        [
            "does not translate: C:\\g\\shaders.rpf@0x10 GS_VoxelizeGeneric: "
            "converter shader.dxil v1: a container without a vertex, pixel, compute or mesh program is not supported",
            "does not translate: C:\\g\\shaders.rpf@0x20 PS_Foo: "
            "converter shader.dxil v1: GFX10 code at 0x3e0: a hardware SGPR input is not supported",
        ]
    )
    assert len(rows) == 2, rows
    assert category("Gs", rows[0]["reason"], True) == "geometry_stage", rows[0]
    assert category("Ps", rows[1]["reason"]) == "ps_hw_sgpr", rows[1]

    game = parse_game_log(
        [
            'stage="pixel" hash=0123456789abcdef "first bind"',
            'stage="compute" hash=0123456789abcdef error=GFX10 code at 0x10: a lane mask is not supported',
        ]
    )
    assert game["0123456789abcdef"]["binds"] == 1, game
    assert category("Cs", game["0123456789abcdef"]["error"]) == "cs_lane_mask", game

    report = summarise(rows, game)
    assert report["total"] == 2, report
    print("self-test OK")
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def main() -> int:
    try:  # Windows consoles default to a legacy code page; the report has Polish text.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="*", type=Path, help="victory warm --list or translate --list output")
    ap.add_argument("--dumps", type=Path, help="folder of .cdxil/.dxbc failure dumps")
    ap.add_argument("--game-log", type=Path, help="game-stderr.log with first bind / error lines")
    ap.add_argument("--json", type=Path, help="write the summary and rows here")
    ap.add_argument("--markdown", action="store_true", help="print a Markdown table")
    ap.add_argument("--self-test", action="store_true", help="run the built-in parser test")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    rows: list[dict] = []
    for path in args.logs:
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            return 2
        lines = read_lines(path)
        parsed = parse_warm_log(lines)
        if not parsed:
            parsed = parse_translate_log(lines)
        rows.extend(parsed)

    dump_rows = []
    if args.dumps:
        if not args.dumps.is_dir():
            print(f"not a folder: {args.dumps}", file=sys.stderr)
            return 2
        dump_rows = inspect_dumps(args.dumps)
        for d in dump_rows:
            rows.append(
                {
                    "label": d.get("file"),
                    "stage": (d.get("stages") or [None])[0],
                    "reason": d.get("error") or "geometry stage" if d.get("has_gs") else d.get("error") or "dump",
                    "hash": None,
                    "has_gs": d.get("has_gs", False),
                }
            )

    game = None
    if args.game_log:
        if not args.game_log.is_file():
            print(f"missing: {args.game_log}", file=sys.stderr)
            return 2
        game = parse_game_log(read_lines(args.game_log))

    if not rows:
        print("no failure rows; give a warm/translate --list log or --dumps", file=sys.stderr)
        return 2

    report = summarise(rows, game)
    report["rows"] = rows
    report["dumps"] = dump_rows
    if game is not None:
        report["game_log"] = {"hashes": len(game), "with_binds": sum(1 for v in game.values() if v.get("binds"))}

    if args.markdown:
        print_markdown(report)
    else:
        print_text(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
