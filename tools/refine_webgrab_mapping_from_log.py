#!/usr/bin/env python3
"""
Refine WebGrab channel mapping CSV using a WebGrab+Plus log file.

The script marks channels with likely failed EPG fetches and clears their
final_site_id for manual correction.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


FAIL_PATTERNS = [
    re.compile(r"(?i)\b0\s+shows?\b"),
    re.compile(r"(?i)\bno\s+shows?\b"),
    re.compile(r"(?i)\bchannel\s+not\s+found\b"),
    re.compile(r"(?i)\bno\s+index\s+page\b"),
    re.compile(r"(?i)\bskipping\s+channel\b"),
    re.compile(r"(?i)\berror\b"),
    re.compile(r"(?i)\bfailed\b"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--mapping-csv", required=True, help="Input mapping CSV")
    p.add_argument("--log-file", required=True, help="WebGrab log file")
    p.add_argument(
        "--output-csv",
        required=True,
        help="Updated mapping CSV with failed channels marked",
    )
    p.add_argument(
        "--report-file",
        required=True,
        help="Text report with failed channels and source lines",
    )
    return p.parse_args()


def load_mapping(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    needed = {"channel_name", "suggested_site_id", "final_site_id"}
    if not rows:
        return []
    if not needed.issubset(rows[0].keys()):
        raise SystemExit(f"CSV must contain columns: {sorted(needed)}")
    return rows


def find_failed_channels(log_text: str, channel_names: list[str]) -> dict[str, list[str]]:
    failed: dict[str, list[str]] = {}
    lines = log_text.splitlines()

    # Build case-insensitive lookup that prefers longest channel names first.
    names_sorted = sorted(channel_names, key=len, reverse=True)
    lowered = [(name, name.lower()) for name in names_sorted]

    for line in lines:
        line_l = line.lower()
        if not any(p.search(line) for p in FAIL_PATTERNS):
            continue
        for original, low in lowered:
            if low and low in line_l:
                failed.setdefault(original, []).append(line.strip())
                break
    return failed


def write_outputs(
    rows: list[dict[str, str]],
    failed: dict[str, list[str]],
    out_csv: Path,
    report_path: Path,
) -> None:
    for row in rows:
        name = row["channel_name"]
        if name in failed:
            row["final_site_id"] = ""

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["channel_name", "suggested_site_id", "final_site_id"]
        )
        w.writeheader()
        w.writerows(rows)

    with report_path.open("w", encoding="utf-8") as f:
        f.write(f"failed_channels={len(failed)}\n")
        for name in sorted(failed.keys(), key=str.lower):
            f.write(f"\n[{name}]\n")
            for line in failed[name][:5]:
                f.write(f"- {line}\n")


def main() -> None:
    args = parse_args()
    rows = load_mapping(Path(args.mapping_csv))
    names = [r["channel_name"] for r in rows]
    log_text = Path(args.log_file).read_text(encoding="utf-8", errors="ignore")
    failed = find_failed_channels(log_text, names)
    write_outputs(rows, failed, Path(args.output_csv), Path(args.report_file))
    print(f"rows={len(rows)}")
    print(f"failed_channels={len(failed)}")
    print(f"output_csv={args.output_csv}")
    print(f"report_file={args.report_file}")


if __name__ == "__main__":
    main()
