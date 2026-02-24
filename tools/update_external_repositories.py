#!/usr/bin/env python3
"""Sync external Kodi repository addons into this repository.

For each configured external repository addon, this script:
- fetches the addon metadata from a remote addons.xml,
- downloads the latest repository zip,
- removes stale local zip versions for that addon,
- updates repo/addons.xml with the remote addon block,
- refreshes repo/addons.xml.md5.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO_DIR = ROOT / "repo"
CONFIG_PATH = ROOT / "tools" / "external_repositories.json"
ADDONS_XML_PATH = REPO_DIR / "addons.xml"
ADDONS_MD5_PATH = REPO_DIR / "addons.xml.md5"


def _fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "mildman1848-repo-sync/1.0"})
    with urlopen(req, timeout=30) as resp:  # nosec B310 - controlled URLs from repo config
        return resp.read().decode("utf-8")


def _fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "mildman1848-repo-sync/1.0"})
    with urlopen(req, timeout=60) as resp:  # nosec B310 - controlled URLs from repo config
        return resp.read()


def _load_config() -> list[dict[str, Any]]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{CONFIG_PATH} must contain a non-empty JSON list")

    required = {"addon_id"}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each config entry must be an object")
        missing = required - set(item)
        if missing:
            raise ValueError(f"Missing required keys in config entry: {sorted(missing)}")
        has_source_xml = "source_addons_xml" in item or "zip_url_template" in item
        has_direct_zip = "zip_url" in item
        has_index_scan = "zip_index_url" in item or "zip_filename_regex" in item

        mode_count = int(has_source_xml) + int(has_direct_zip) + int(has_index_scan)
        if mode_count != 1:
            raise ValueError(
                f"Config entry '{item.get('addon_id')}' must define exactly one source mode: "
                "'zip_url', 'source_addons_xml/zip_url_template', or "
                "'zip_index_url/zip_filename_regex'"
            )

        if has_index_scan and not (
            "zip_index_url" in item and "zip_filename_regex" in item
        ):
            raise ValueError(
                f"Config entry '{item.get('addon_id')}' must define both "
                "'zip_index_url' and 'zip_filename_regex'"
            )

        if has_index_scan and "zip_url_template" in item and "{filename}" not in item["zip_url_template"]:
            raise ValueError(
                f"Config entry '{item.get('addon_id')}' with index scan must use "
                "'zip_url_template' containing '{{filename}}'"
            )

        if has_source_xml and not (
            "source_addons_xml" in item and "zip_url_template" in item
        ):
            raise ValueError(
                f"Config entry '{item.get('addon_id')}' must define either "
                "'zip_url' or both 'source_addons_xml' and 'zip_url_template'"
            )
    return raw


def _find_addon(root: ET.Element, addon_id: str) -> ET.Element:
    for addon in root.findall("addon"):
        if addon.attrib.get("id") == addon_id:
            return addon
    raise ValueError(f"Addon id '{addon_id}' not found in source addons.xml")


def _strip_whitespace_nodes(element: ET.Element) -> None:
    if element.text is not None and not element.text.strip():
        element.text = None
    if element.tail is not None and not element.tail.strip():
        element.tail = None
    for child in list(element):
        _strip_whitespace_nodes(child)


def _canonical_xml(element: ET.Element) -> str:
    clone = ET.fromstring(ET.tostring(element, encoding="unicode"))
    _strip_whitespace_nodes(clone)
    return ET.tostring(clone, encoding="unicode")


def _version_key(version: str) -> list[Any]:
    parts = re.split(r"([0-9]+)", version)
    key: list[Any] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))
    return key


def _discover_zip_from_index(
    index_url: str, filename_regex: str, zip_url_template: str | None
) -> tuple[str, str]:
    html = _fetch_text(index_url)
    rx = re.compile(filename_regex)

    candidates: list[tuple[str, str]] = []
    for match in rx.finditer(html):
        filename = match.group(0)
        version = match.groupdict().get("version")
        if not version:
            raise ValueError(
                "zip_filename_regex must contain a named capture group 'version'"
            )
        candidates.append((filename, version))

    if not candidates:
        raise ValueError(f"No matching zip filenames found at {index_url}")

    filename, _ = max(candidates, key=lambda item: _version_key(item[1]))

    if zip_url_template:
        zip_url = zip_url_template.format(filename=filename)
    else:
        base = index_url if index_url.endswith("/") else index_url + "/"
        zip_url = base + filename

    return zip_url, filename


def _find_addon_in_zip(data: bytes, expected_addon_id: str) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        addon_candidates = [name for name in zf.namelist() if name.endswith("addon.xml")]
        if not addon_candidates:
            raise ValueError(f"No addon.xml found in downloaded zip for '{expected_addon_id}'")

        for name in addon_candidates:
            addon_root = ET.fromstring(zf.read(name).decode("utf-8"))
            if addon_root.tag != "addon":
                continue
            if addon_root.attrib.get("id") == expected_addon_id:
                return addon_root

    raise ValueError(
        f"Could not find addon id '{expected_addon_id}' in downloaded zip addon.xml files"
    )


def _replace_or_append_addon(root: ET.Element, incoming: ET.Element) -> bool:
    incoming_id = incoming.attrib.get("id")
    incoming_xml = _canonical_xml(incoming)

    for index, existing in enumerate(list(root)):
        if existing.tag != "addon":
            continue
        if existing.attrib.get("id") != incoming_id:
            continue

        existing_xml = _canonical_xml(existing)
        if existing_xml == incoming_xml:
            return False

        root.remove(existing)
        root.insert(index, incoming)
        return True

    root.append(incoming)
    return True


def _write_addons_files(root: ET.Element) -> None:
    ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode")
    xml_text = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml_body + "\n"

    ADDONS_XML_PATH.write_text(xml_text, encoding="utf-8")
    md5 = hashlib.md5(xml_text.encode("utf-8")).hexdigest()
    ADDONS_MD5_PATH.write_text(md5 + "\n", encoding="ascii")


def _clear_extracted_artifacts(target_dir: Path) -> None:
    for child in target_dir.iterdir():
        if child.name.endswith(".zip"):
            continue
        if child.is_dir():
            shutil.rmtree(child)
            continue
        child.unlink()


def _extract_zip_contents(target_zip: Path, addon_id: str, target_dir: Path) -> None:
    with zipfile.ZipFile(target_zip) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue

            name = member.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p]
            if not parts:
                continue

            # Most Kodi zips have a top-level addon folder, strip it if present.
            if parts[0] == addon_id:
                parts = parts[1:]
            if not parts:
                continue

            if any(part in {".", ".."} for part in parts):
                continue

            dest = target_dir.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, dest.open("wb") as dst:
                dst.write(src.read())


def _write_repository_dir_index(addon_id: str, target_dir: Path) -> None:
    entries = sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    rows: list[str] = [
        "      <tr><td><a href=\"../\">Parent Directory</a></td><td align=\"right\">-</td><td align=\"right\">-</td></tr>"
    ]

    for entry in entries:
        if entry.name == "index.html":
            continue
        modified = datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc).strftime("%d-%b-%Y")
        if entry.is_dir():
            href = f"{entry.name}/"
            size = "-"
        else:
            href = entry.name
            size = f"{max(1, round(entry.stat().st_size / 1024))} KB"
        rows.append(
            f"      <tr><td><a href=\"{href}\">{href}</a></td><td align=\"right\">{modified}</td><td align=\"right\">{size}</td></tr>"
        )

    index_text = f"""<html>
<head>
<title>/repo/{addon_id}/</title>
<link rel=\"stylesheet\" href=\"/assets/css/style.css\" media=\"screen\" type=\"text/css\"/>
<link rel=\"stylesheet\" href=\"/assets/css/print.css\" media=\"print\" type=\"text/css\"/>
<meta name=\"description\" content=\"/repo/{addon_id}/\"/>
</head>
<body>
  <h2>Index of /repo/{addon_id}/</h2>
  <table>
    <tbody>
      <tr><th>Name</th><th>Last modified</th><th>Size</th></tr>
      <tr><th colspan=\"3\"><hr></th></tr>
{chr(10).join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    (target_dir / "index.html").write_text(index_text, encoding="utf-8")


def main() -> int:
    config = _load_config()

    local_tree = ET.parse(ADDONS_XML_PATH)
    local_root = local_tree.getroot()
    if local_root.tag != "addons":
        raise ValueError(f"Unexpected root in {ADDONS_XML_PATH}: {local_root.tag}")

    changed = False

    for entry in config:
        addon_id = entry["addon_id"]
        if "zip_url" in entry:
            zip_url = entry["zip_url"]
            data = _fetch_bytes(zip_url)
            source_addon = _find_addon_in_zip(data, addon_id)
        elif "zip_index_url" in entry:
            zip_url, _ = _discover_zip_from_index(
                entry["zip_index_url"],
                entry["zip_filename_regex"],
                entry.get("zip_url_template"),
            )
            data = _fetch_bytes(zip_url)
            source_addon = _find_addon_in_zip(data, addon_id)
        else:
            source_addons_xml = entry["source_addons_xml"]
            zip_url_template = entry["zip_url_template"]
            source_xml = _fetch_text(source_addons_xml)
            source_root = ET.fromstring(source_xml)
            source_addon = _find_addon(source_root, addon_id)
            version = source_addon.attrib.get("version")
            if not version:
                raise ValueError(f"Addon '{addon_id}' has no version in source metadata")
            zip_url = zip_url_template.format(addon_id=addon_id, version=version)
            data = None

        version = source_addon.attrib.get("version")
        if not version:
            raise ValueError(f"Addon '{addon_id}' has no version in source metadata")
        target_dir = REPO_DIR / addon_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_zip = target_dir / f"{addon_id}-{version}.zip"

        if not target_zip.exists():
            if data is None:
                data = _fetch_bytes(zip_url)
            target_zip.write_bytes(data)
            print(f"Downloaded {target_zip.name} from {zip_url}")
            changed = True

        # Keep only the newest synced zip for this external repository addon.
        for old_zip in sorted(target_dir.glob(f"{addon_id}-*.zip")):
            if old_zip.name == target_zip.name:
                continue
            old_zip.unlink()
            print(f"Removed stale zip {old_zip.name}")
            changed = True

        # Cleanup from legacy layout where external zips were stored at repo root.
        for root_zip in sorted(REPO_DIR.glob(f"{addon_id}-*.zip")):
            root_zip.unlink()
            print(f"Removed legacy root zip {root_zip.name}")
            changed = True

        _clear_extracted_artifacts(target_dir)
        _extract_zip_contents(target_zip, addon_id, target_dir)
        _write_repository_dir_index(addon_id, target_dir)

        incoming_addon = ET.fromstring(ET.tostring(source_addon, encoding="unicode"))
        if _replace_or_append_addon(local_root, incoming_addon):
            print(f"Updated addon metadata in repo/addons.xml for {addon_id} ({version})")
            changed = True

    if changed:
        _write_addons_files(local_root)
        print("Wrote repo/addons.xml and repo/addons.xml.md5")
    else:
        print("No external repository updates found")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
