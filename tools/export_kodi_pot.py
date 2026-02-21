#!/usr/bin/env python3
"""Export a Kodi strings.po file to a generic strings.pot template."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.source).read_text(encoding="utf-8")
    lines = src.splitlines()
    out = []
    header_done = False

    for line in lines:
        if line.startswith('"Language:'):
            out.append('"Language: \\n"')
            continue
        out.append(line)
        if not header_done and line.strip() == "":
            header_done = True

    Path(args.output).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
