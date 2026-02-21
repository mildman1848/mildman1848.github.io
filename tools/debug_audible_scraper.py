#!/usr/bin/env python3
"""Simple Audible scraper debugging helper.

Runs the same public endpoints used by the Kodi Audible metadata scrapers and
prints compact diagnostics to make endpoint failures easier to triage.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def album_search(domain: str, query: str, limit: int) -> int:
    params = urllib.parse.urlencode(
        {
            "response_groups": "contributors,media,product_desc,product_attrs,product_extended_attrs,series,category_ladders,rating,product_details",
            "image_sizes": "500",
            "num_results": str(limit),
            "products_sort_by": "Relevance",
            "keywords": query,
        }
    )
    url = f"https://api.{domain}/1.0/catalog/products?{params}"
    data = fetch_json(url)
    products = data.get("products", [])
    print(f"[ALBUM] endpoint: {url}")
    print(f"[ALBUM] total_results: {data.get('total_results', 0)} | products_in_payload: {len(products)}")
    if products:
        first = products[0]
        print(f"[ALBUM] sample: asin={first.get('asin')} title={first.get('title')}")
    return 0


def artist_search(domain: str, query: str, limit: int) -> int:
    params = urllib.parse.urlencode(
        {
            "response_groups": "contributors,product_desc,product_attrs,series",
            "image_sizes": "500",
            "num_results": str(limit),
            "products_sort_by": "Relevance",
            "keywords": query,
        }
    )
    url = f"https://api.{domain}/1.0/catalog/products?{params}"
    data = fetch_json(url)
    products = data.get("products", [])

    author_asin = None
    author_name = None
    for item in products:
        authors = item.get("authors") or []
        if authors:
            author_asin = authors[0].get("asin")
            author_name = authors[0].get("name")
            if author_asin:
                break

    print(f"[ARTIST] endpoint: {url}")
    print(f"[ARTIST] total_results: {data.get('total_results', 0)} | products_in_payload: {len(products)}")
    if author_asin:
        profile_url = f"https://api.{domain}/1.0/catalog/contributors/{author_asin}?locale=de-DE"
        profile = fetch_json(profile_url)
        contributor = profile.get("contributor") or {}
        print(f"[ARTIST] contributor endpoint: {profile_url}")
        print(f"[ARTIST] sample contributor: id={contributor.get('contributor_id')} name={contributor.get('name') or author_name}")
    else:
        print("[ARTIST] no author ASIN found in search payload")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["album", "artist", "both"])
    p.add_argument("query", help="Search query")
    p.add_argument("--domain", default="audible.de", help="Audible domain, e.g. audible.de")
    p.add_argument("--limit", type=int, default=25, help="Result limit")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.mode in ("album", "both"):
            album_search(args.domain, args.query, args.limit)
        if args.mode in ("artist", "both"):
            artist_search(args.domain, args.query, args.limit)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
