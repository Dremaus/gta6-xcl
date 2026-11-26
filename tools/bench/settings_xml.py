#!/usr/bin/env python3
r"""Read the pacing fields of the title's settings.xml.

The title keeps its settings in ``<data_root>/data/<title_id>/storage/
settings/settings.xml`` (``rage__fwSystemSettingsCollection``). The fields
that control frame pacing are:

    graphics/desiredFPS
    video/frameRateLimit
    video/vSync
    video/refreshRate/numerator, /denominator
    video/resolutionFullscreen/width, /height

The module parses exactly those fields, derives the refresh rate in Hz and a
cap state (``active`` when ``frameRateLimit != 0``, ``removed`` when it is 0),
and can also parse the ``.cap-bak`` backup so an A/B arm can be verified
against the known patched/capped states. It never starts the game.

    python tools/bench/settings_xml.py PATH --with-backup
    python tools/bench/settings_xml.py --data-root D:\Gry\VItoriaBr-data --expect-cap removed
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

TITLE_ID = "7952987A"  # GTA VI (Xbox) profile id on this host


def find_settings(data_root: Path | None) -> Path | None:
    """Locate the title's settings.xml under a runtime data root."""
    if data_root is None:
        return None
    direct = data_root / "data" / TITLE_ID / "storage" / "settings" / "settings.xml"
    if direct.is_file():
        return direct
    hits = sorted(data_root.glob("data/*/storage/settings/settings.xml"))
    return hits[0] if hits else None


def _value(element: ET.Element | None):
    if element is None:
        return None
    text = (element.get("value") or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def parse(path: Path) -> dict:
    """Parse the pacing fields of one settings.xml into a plain dict."""
    record: dict = {"source": str(path)}
    if not path.is_file():
        record["found"] = False
        return record
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        record.update({"found": True, "parse_error": str(exc)})
        return record

    def attr(element_path: str):
        return _value(root.find(element_path))

    desired = attr("graphics/desiredFPS")
    limit = attr("video/frameRateLimit")
    vsync = attr("video/vSync")
    numerator = attr("video/refreshRate/numerator")
    denominator = attr("video/refreshRate/denominator")
    width = attr("video/resolutionFullscreen/width")
    height = attr("video/resolutionFullscreen/height")

    refresh_hz = None
    if isinstance(numerator, int) and isinstance(denominator, int) and denominator != 0:
        refresh_hz = round(numerator / denominator, 2)

    cap = "unknown"
    if limit is not None:
        cap = "active" if limit != 0 else "removed"

    record.update(
        {
            "found": True,
            "graphics": {"desiredFPS": desired},
            "video": {
                "frameRateLimit": limit,
                "vSync": vsync,
                "refreshRate": {"numerator": numerator, "denominator": denominator},
                "resolutionFullscreen": {"width": width, "height": height},
            },
            "refresh_hz": refresh_hz,
            "cap": cap,
            "file_mtime_utc": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(timespec="seconds"),
        }
    )
    return record


def read_settings(path: Path | None = None, data_root: Path | None = None) -> dict:
    """Parse the active settings.xml and, when present, its ``.cap-bak`` backup."""
    resolved = path or find_settings(data_root)
    if resolved is None:
        return {"source": str(path or data_root), "found": False}
    record = parse(resolved)
    backup = Path(str(resolved) + ".cap-bak")
    if backup.is_file():
        record["backup"] = parse(backup)
    return record


def describe(record: dict) -> str:
    """One-line summary for plan prints and reports."""
    if not record.get("found"):
        return f"settings.xml: not found ({record.get('source')})"
    if record.get("parse_error"):
        return f"settings.xml: unparsed ({record.get('parse_error')})"
    g = record.get("graphics", {})
    v = record.get("video", {})
    r = v.get("refreshRate", {})
    res = v.get("resolutionFullscreen", {})
    return (
        f"settings.xml: desiredFPS={g.get('desiredFPS')} "
        f"frameRateLimit={v.get('frameRateLimit')} vSync={v.get('vSync')} "
        f"refresh={r.get('numerator')}/{r.get('denominator')} "
        f"({record.get('refresh_hz')} Hz) fullscreen="
        f"{res.get('width')}x{res.get('height')} cap={record.get('cap')}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="settings.xml to parse (default: VItoriaBr data root)",
    )
    ap.add_argument("--data-root", type=Path)
    ap.add_argument(
        "--with-backup",
        action="store_true",
        help="also parse and include the .cap-bak backup",
    )
    ap.add_argument(
        "--expect-cap",
        choices=["active", "removed"],
        help="exit 1 when the parsed cap state differs",
    )
    args = ap.parse_args()

    if args.path:
        source = args.path
        record = parse(source)
    else:
        data_root = args.data_root or Path(r"D:\Gry\VItoriaBr-data")
        resolved = find_settings(data_root)
        if resolved is None:
            record = {"source": str(data_root), "found": False}
        else:
            source = resolved
            record = parse(resolved)

    if record.get("found") and not record.get("parse_error"):
        backup = Path(str(source) + ".cap-bak")
        if (args.with_backup or not args.path) and backup.is_file():
            record["backup"] = parse(backup)

    print(json.dumps(record, indent=2))
    print(describe(record))
    if args.expect_cap and record.get("cap") != args.expect_cap:
        print(
            f"cap mismatch: expected {args.expect_cap}, got {record.get('cap')}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
