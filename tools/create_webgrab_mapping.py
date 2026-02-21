#!/usr/bin/env python3
"""
Create channel mapping CSV + mapped WebGrab config from an M3U file.

Outputs:
- mapping CSV with channel_name,suggested_site_id,final_site_id
- WebGrab++.config.mapped.xml using final_site_id
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path


EXTINF_RE = re.compile(r"^#EXTINF:-?\d+\s*(.*?),(.*)$")
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="(.*?)"')


ALIAS_EXACT = {
    "ARD DAS ERSTE": "Das Erste",
    "DAS ERSTE": "Das Erste",
    "DAS ERSTE HD": "Das Erste",
    "3 SAT": "3sat",
    "3SAT": "3sat",
    "ZDF HD": "ZDF",
    "ARTE HD": "arte",
    "RTL HD": "RTL",
    "RTL 2": "RTLZWEI",
    "RTL II": "RTLZWEI",
    "PRO7": "ProSieben",
    "PRO SIEBEN": "ProSieben",
    "SAT.1": "Sat.1",
    "SAT 1": "Sat.1",
    "KABEL 1": "kabel eins",
    "VOX HD": "VOX",
    "N TV": "ntv",
    "N-TV": "ntv",
    "SUPER RTL": "SUPER RTL",
    "TOGGO PLUS": "TOGGO plus",
    "NITRO HD": "NITRO",
    "TELE 5": "TELE 5",
    "DMAX HD": "DMAX",
    "SPORT1 HD": "SPORT1",
    "SIXX HD": "sixx",
    "WELT HD": "WELT",
    "BILD TV": "BILD",
}


DROP_PATTERNS = [
    r"\[[^\]]*\]",
    r"\((?:BACKUP|ALT|TEST)\)",
    r"\b(?:FHD|UHD|4K|8K|HEVC|H\.?265|H\.?264)\b",
    r"\b(?:GERMANY|DE|SAT)\b",
    r"\b(?:HD\+|HD)\b",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--m3u", required=True)
    p.add_argument("--site", default="tvspielfilm.de")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--mapping-csv", required=True)
    p.add_argument("--mapped-config", required=True)
    return p.parse_args()


def parse_channels(m3u: Path) -> list[str]:
    lines = m3u.read_text(encoding="utf-8", errors="ignore").splitlines()
    names: list[str] = []
    seen: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line.startswith("#EXTINF:"):
            continue
        m = EXTINF_RE.match(line)
        if not m:
            continue
        _attrs = dict(ATTR_RE.findall(m.group(1)))
        name = (m.group(2) or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return sorted(names, key=str.lower)


def normalize_for_site_id(name: str) -> str:
    s = name
    for pat in DROP_PATTERNS:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)

    s = s.replace("ʜᴅ", " ")
    s = s.replace("+", " plus ")
    s = s.replace("&", " and ")
    s = s.replace("SÜD", "SUED")
    s = s.replace("Ö", "OE").replace("Ä", "AE").replace("Ü", "UE")
    s = s.replace("ö", "oe").replace("ä", "ae").replace("ü", "ue")
    s = re.sub(r"\s+", " ", s).strip(" -_")

    upper = s.upper()
    if upper in ALIAS_EXACT:
        return ALIAS_EXACT[upper]

    # Heuristic cleanup for duplicated qualifiers.
    s = re.sub(r"\bTV TV\b", "TV", s, flags=re.IGNORECASE)
    s = re.sub(r"\bFERNSEHEN\b", "Fernsehen", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSUD\b", "Sued", s, flags=re.IGNORECASE)

    return s


def write_mapping_csv(names: list[str], out_csv: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for name in names:
        suggested = normalize_for_site_id(name)
        final = suggested
        rows.append((name, suggested, final))

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["channel_name", "suggested_site_id", "final_site_id"])
        w.writerows(rows)

    return rows


def write_mapped_config(rows: list[tuple[str, str, str]], site: str, days: int, out_cfg: Path) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<settings>",
        "  <filename>guide.xml</filename>",
        f"  <update>{days}</update>",
        '  <retry time-out="10">2</retry>',
        "  <timespan>3</timespan>",
        "  <skip>noskip</skip>",
        "  <language>de</language>",
        "  <logging>on</logging>",
        "",
    ]

    for channel_name, _suggested, final in rows:
        site_id = html.escape(final, quote=True)
        name = html.escape(channel_name, quote=True)
        lines.append(f'  <channel update="i" site="{site}" site_id="{site_id}">{name}</channel>')

    lines.append("</settings>")
    lines.append("")
    out_cfg.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    names = parse_channels(Path(args.m3u))
    rows = write_mapping_csv(names, Path(args.mapping_csv))
    write_mapped_config(rows, args.site, args.days, Path(args.mapped_config))
    print(f"Mapped channels: {len(rows)}")
    print(f"CSV: {args.mapping_csv}")
    print(f"Config: {args.mapped_config}")


if __name__ == "__main__":
    main()
