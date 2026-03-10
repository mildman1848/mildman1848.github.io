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
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO_DIR = ROOT / "repo"
CONFIG_PATH = ROOT / "tools" / "external_repositories.json"
ADDONS_XML_PATH = REPO_DIR / "addons.xml"
ADDONS_MD5_PATH = REPO_DIR / "addons.xml.md5"
DEFAULT_KODI_VERSION = os.environ.get("KODI_REPOSITORY_VERSION", "21.3.0")


def _fetch_bytes_with_curl(url: str, timeout: int) -> bytes:
    result = subprocess.run(  # nosec B603 - controlled URLs from repo config, no shell
        [
            "curl",
            "-fsSL",
            "--retry",
            "3",
            "--retry-all-errors",
            "--connect-timeout",
            "15",
            "--max-time",
            str(timeout),
            "-A",
            "mildman1848-repo-sync/1.0",
            url,
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _fetch_bytes(url: str, timeout: int = 60) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "mildman1848-repo-sync/1.0"})
            with urlopen(req, timeout=timeout) as resp:  # nosec B310 - controlled URLs from repo config
                return resp.read()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)

    try:
        return _fetch_bytes_with_curl(url, timeout)
    except Exception:
        if last_error is not None:
            raise last_error
        raise


def _fetch_text(url: str) -> str:
    return _fetch_bytes(url, timeout=30).decode("utf-8")


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


def _parse_version_tuple(version: str | None) -> tuple[int, ...] | None:
    if not version:
        return None
    match = re.match(r"^\d+(?:\.\d+)*", version.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def _dir_matches_kodi_version(directory: ET.Element, kodi_version: str) -> bool:
    target = _parse_version_tuple(kodi_version)
    if target is None:
        return False

    min_version = _parse_version_tuple(directory.attrib.get("minversion"))
    max_version = _parse_version_tuple(directory.attrib.get("maxversion"))

    if min_version is not None and target < min_version:
        return False
    if max_version is not None and target > max_version:
        return False
    return True


def _ensure_root_requires(addon: ET.Element) -> None:
    requires = addon.find("requires")
    if requires is not None:
        return

    requires = ET.Element("requires")
    import_node = ET.SubElement(requires, "import")
    import_node.set("addon", "xbmc.addon")
    import_node.set("version", "12.0.0")
    addon.insert(0, requires)


def _normalize_repository_addon(addon: ET.Element) -> list[str]:
    notes: list[str] = []
    repo_extension = addon.find("./extension[@point='xbmc.addon.repository']")
    if repo_extension is None:
        return notes

    extension_requires = repo_extension.find("requires")
    if extension_requires is not None:
        repo_extension.remove(extension_requires)
        notes.append("moved <requires> from repository extension to addon root")

    direct_repo_children = [
        child
        for child in list(repo_extension)
        if child.tag in {"info", "checksum", "datadir", "artdir", "hashes"}
    ]
    if direct_repo_children:
        new_dir = ET.Element("dir")
        insert_at = list(repo_extension).index(direct_repo_children[0])
        for child in direct_repo_children:
            repo_extension.remove(child)
            new_dir.append(child)
        repo_extension.insert(insert_at, new_dir)
        notes.append("converted legacy repository schema to <dir> format")

    _ensure_root_requires(addon)
    return notes


def _validate_repository_addon(addon: ET.Element, kodi_version: str) -> list[str]:
    warnings: list[str] = []
    addon_id = addon.attrib.get("id", "<unknown>")
    repo_extension = addon.find("./extension[@point='xbmc.addon.repository']")
    if repo_extension is None:
        warnings.append(f"{addon_id}: missing xbmc.addon.repository extension")
        return warnings

    if repo_extension.find("requires") is not None:
        warnings.append(f"{addon_id}: repository extension still contains <requires>")

    directories = repo_extension.findall("dir")
    if not directories:
        warnings.append(f"{addon_id}: repository extension has no <dir> definitions")
        return warnings

    if not any(_dir_matches_kodi_version(directory, kodi_version) for directory in directories):
        warnings.append(f"{addon_id}: no repository <dir> matches Kodi {kodi_version}")

    for directory in directories:
        for node_name in ("info", "checksum", "datadir", "artdir"):
            node = directory.find(node_name)
            if node is None or not (node.text and node.text.strip()):
                continue
            text = node.text.strip()
            if text.startswith("http://"):
                warnings.append(f"{addon_id}: uses plain HTTP in <{node_name}>: {text}")

    return warnings


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


def _rewrite_addon_xml_in_zip(data: bytes, expected_addon_id: str, addon_xml: str) -> bytes:
    source_buffer = io.BytesIO(data)
    target_buffer = io.BytesIO()

    with zipfile.ZipFile(source_buffer) as source_zip, zipfile.ZipFile(
        target_buffer, "w"
    ) as target_zip:
        replaced = False
        for member in source_zip.infolist():
            member_bytes = source_zip.read(member.filename)
            if member.filename.endswith("addon.xml"):
                addon_root = ET.fromstring(member_bytes.decode("utf-8"))
                if addon_root.tag == "addon" and addon_root.attrib.get("id") == expected_addon_id:
                    member_bytes = addon_xml.encode("utf-8")
                    replaced = True

            clone_info = zipfile.ZipInfo(member.filename, member.date_time)
            clone_info.compress_type = member.compress_type
            clone_info.comment = member.comment
            clone_info.extra = member.extra
            clone_info.create_system = member.create_system
            clone_info.external_attr = member.external_attr
            clone_info.internal_attr = member.internal_attr
            clone_info.flag_bits = member.flag_bits
            target_zip.writestr(clone_info, member_bytes)

    if not replaced:
        raise ValueError(
            f"Could not rewrite addon.xml in zip for addon id '{expected_addon_id}'"
        )

    return target_buffer.getvalue()


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


def _addon_xml_text(addon: ET.Element) -> str:
    clone = ET.fromstring(ET.tostring(addon, encoding="unicode"))
    ET.indent(clone, space="    ")
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(
        clone, encoding="unicode"
    )


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
        print(f"Syncing {addon_id}...")
        extracted_artifacts_changed = False
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
            extracted_artifacts_changed = True

        incoming_addon = ET.fromstring(ET.tostring(source_addon, encoding="unicode"))
        normalization_notes = _normalize_repository_addon(incoming_addon)
        for note in normalization_notes:
            print(f"Normalized {addon_id}: {note}")

        validation_warnings = _validate_repository_addon(incoming_addon, DEFAULT_KODI_VERSION)
        for warning in validation_warnings:
            print(f"Warning: {warning}")

        normalized_zip_bytes = _rewrite_addon_xml_in_zip(
            target_zip.read_bytes(),
            addon_id,
            _addon_xml_text(incoming_addon),
        )
        existing_zip_bytes = target_zip.read_bytes()
        if normalized_zip_bytes != existing_zip_bytes:
            target_zip.write_bytes(normalized_zip_bytes)
            print(f"Rewrote {target_zip.name} with normalized addon.xml")
            changed = True
            extracted_artifacts_changed = True

        # Keep only the newest synced zip for this external repository addon.
        for old_zip in sorted(target_dir.glob(f"{addon_id}-*.zip")):
            if old_zip.name == target_zip.name:
                continue
            old_zip.unlink()
            print(f"Removed stale zip {old_zip.name}")
            changed = True
            extracted_artifacts_changed = True

        # Cleanup from legacy layout where external zips were stored at repo root.
        for root_zip in sorted(REPO_DIR.glob(f"{addon_id}-*.zip")):
            root_zip.unlink()
            print(f"Removed legacy root zip {root_zip.name}")
            changed = True
            extracted_artifacts_changed = True

        if extracted_artifacts_changed or not (target_dir / "index.html").exists():
            _clear_extracted_artifacts(target_dir)
            _extract_zip_contents(target_zip, addon_id, target_dir)
            _write_repository_dir_index(addon_id, target_dir)

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
