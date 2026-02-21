#!/usr/bin/env python3
"""
Generate a WebGrab+Plus config skeleton from an M3U playlist.

Usage:
  python3 tools/generate_webgrab_config.py \
    --m3u /path/to/VavooTV-Germany-2026-02-21.m3u \
    --site tvspielfilm.de \
    --output /path/to/WebGrab++.config.xml
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


EXTINF_RE = re.compile(r"^#EXTINF:-?\d+\s*(.*?),(.*)$")
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="(.*?)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create WebGrab+Plus config skeleton from M3U channels."
    )
    parser.add_argument("--m3u", required=True, help="Input M3U file path")
    parser.add_argument(
        "--site",
        default="tvspielfilm.de",
        help="WebGrab+Plus siteini name (default: tvspielfilm.de)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Number of EPG days to grab (default: 3)",
    )
    parser.add_argument(
        "--output",
        default="WebGrab++.config.xml",
        help="Output config file path",
    )
    return parser.parse_args()


def parse_m3u_channels(m3u_text: str) -> list[dict[str, str]]:
    channels: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for raw_line in m3u_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("#EXTINF:"):
            continue

        match = EXTINF_RE.match(line)
        if not match:
            continue

        attr_blob, display_name = match.groups()
        attrs = dict(ATTR_RE.findall(attr_blob))

        name = (display_name or "").strip()
        tvg_id = (attrs.get("tvg-id", "") or "").strip()
        key = (name.lower(), tvg_id.lower())

        if not name or key in seen:
            continue
        seen.add(key)

        channels.append(
            {
                "name": name,
                "tvg_id": tvg_id,
            }
        )

    channels.sort(key=lambda c: c["name"].lower())
    return channels


def to_webgrab_config(channels: list[dict[str, str]], site: str, days: int) -> str:
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<settings>")
    lines.append("  <filename>guide.xml</filename>")
    lines.append(f"  <update>{days}</update>")
    lines.append("  <retry time-out=\"10\">2</retry>")
    lines.append("  <timespan>3</timespan>")
    lines.append("  <skip>noskip</skip>")
    lines.append("  <language>de</language>")
    lines.append("  <logging>on</logging>")
    lines.append("")
    lines.append("  <!--")
    lines.append("    xmltv_id muss zur gewaehlten site.ini passen.")
    lines.append("    Wenn tvg-id in der M3U nicht passt, bitte manuell ersetzen.")
    lines.append("  -->")

    for ch in channels:
        channel_name = html.escape(ch["name"], quote=True)
        xmltv_id = html.escape(ch["tvg_id"] or ch["name"], quote=True)
        lines.append(
            f'  <channel update="i" site="{site}" site_id="{xmltv_id}">{channel_name}</channel>'
        )

    lines.append("</settings>")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    m3u_path = Path(args.m3u)
    if not m3u_path.exists():
        raise SystemExit(f"M3U not found: {m3u_path}")

    channels = parse_m3u_channels(m3u_path.read_text(encoding="utf-8", errors="ignore"))
    if not channels:
        raise SystemExit("No channels parsed from M3U.")

    output = to_webgrab_config(channels, args.site, args.days)
    out_path = Path(args.output)
    out_path.write_text(output, encoding="utf-8")
    print(f"Wrote {out_path} with {len(channels)} channel entries.")


if __name__ == "__main__":
    main()
