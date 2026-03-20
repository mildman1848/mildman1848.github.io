#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


SOURCE_HOME = Path("/home/philipp/.var/app/tv.kodi.Kodi/data")
SOURCE_ADDONS = SOURCE_HOME / "addons"
SOURCE_USERDATA = SOURCE_HOME / "userdata"
ADDONS_DB = SOURCE_USERDATA / "Database" / "Addons33.db"

REPO_ROOT = Path("/home/philipp/Dokumente/Github/master/mildman1848.github.io")
BUILD_ROOT = REPO_ROOT / "builds" / "plugin.video.tools"
OUTPUT_ZIP = BUILD_ROOT / "build.zip"
OUTPUT_INFO = BUILD_ROOT / "build-info.json"
OUTPUT_HTML = BUILD_ROOT / "index.html"

BUILTIN_ORIGIN = "b6a50484-93a0-4afb-a01c-8d17e059feda"

ROOT_ADDONS = {
    "metadata.albums.audible",
    "metadata.artists.audible",
    "plugin.audio.audiobookshelf",
    "plugin.googledrive",
    "plugin.video.ardundzdf",
    "plugin.video.jellycon",
    "plugin.video.joyn",
    "plugin.video.sporttotal",
    "plugin.video.themoviedb.helper",
    "plugin.video.tools",
    "plugin.video.twitch",
    "plugin.video.vavootv",
    "pvr.iptvsimple",
    "repository.abratchik",
    "repository.axbmcuser",
    "repository.embycon",
    "repository.jellyfin.kodi",
    "repository.jurialmunkey",
    "repository.kodi.yatse.tv",
    "repository.kodinerds",
    "repository.lattsrepo",
    "repository.marcelveldt",
    "repository.michaz",
    "repository.mildman1848",
    "repository.rector.stuff",
    "repository.resolveurl",
    "repository.sandmann79.plugins",
    "repository.slyguy",
    "repository.slyguy.globalsearch",
    "repository.slyguy.inputstreamhelper",
    "repository.slyguy.youtube",
    "repository.titan.bingie.mod",
    "resource.language.de_de",
    "screensaver.atv4",
    "script.artistslideshow",
    "script.artwork.dump",
    "script.preshowexperience",
    "script.trakt",
    "service.tvtunes",
    "skin.estuary.modv2",
}

KEEP_USERDATA_FILES = {
    "RssFeeds.xml",
    "advancedsettings.xml",
    "favourites.xml",
    "guisettings.xml",
    "profiles.xml",
}

KEEP_USERDATA_DIRS = {
    "addon_data",
    "Database",
    "keymaps",
    "peripheral_data",
    "playlists",
}

KEEP_DATABASES = {
    "Addons33.db",
    "ViewModes6.db",
}

KEEP_ADDON_DATA_SUFFIXES = {
    ".json",
    ".xml",
}

KEEP_ADDON_DATA_NAMES = {
    "settings.db",
}

DROP_PATH_PARTS = {
    "cache",
    "cache_items",
    "cache_children",
    "cache_page",
    "simplecache",
    "thumbnails",
    "tmp",
    "temp",
}

DROP_FILENAMES = {
    "access_manager.json",
    "api_keys.json",
    "auth_tokens",
    "auth.json",
    "passwords.xml",
    "textures13.db",
    "musixmatch_token",
}

SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|pass(word)?|api(_?key)?|client(_?id|_?secret)?|auth|authorization|oauth|session|cookie|username|account|mac(address)?|proxy_(user|passwd)|webserver(user|pass)|httpproxy(user|pass))",
    re.IGNORECASE,
)

SENSITIVE_XML_SETTING_IDS = {
    "base_url",
    "custom_path",
    "download-folder",
    "fanarttv_key",
    "local_artist_path",
    "local_info_path",
    "movies_library",
    "save_lyrics_path",
    "server_address",
    "tvshows_library",
}

URL_CREDENTIAL_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@:\s]+)(?::[^@/\s]*)?@")


def load_enabled_addons() -> dict[str, str]:
    conn = sqlite3.connect(ADDONS_DB)
    try:
        rows = conn.execute(
            "select addonID, origin from installed where enabled=1 order by addonID"
        ).fetchall()
    finally:
        conn.close()
    return {addon_id: origin or "" for addon_id, origin in rows}


def parse_dependencies(addon_id: str) -> set[str]:
    addon_xml = SOURCE_ADDONS / addon_id / "addon.xml"
    if not addon_xml.exists():
        return set()
    root = ET.parse(addon_xml).getroot()
    requires = root.find("requires")
    if requires is None:
        return set()
    deps: set[str] = set()
    for item in requires.findall("import"):
        dep = item.get("addon")
        if dep and dep not in {"xbmc.python"}:
            deps.add(dep)
    return deps


def resolve_addons(enabled: dict[str, str]) -> list[str]:
    selected = {addon for addon in ROOT_ADDONS if (SOURCE_ADDONS / addon).is_dir()}
    queue = list(selected)
    while queue:
        current = queue.pop()
        for dep in parse_dependencies(current):
            if dep in selected:
                continue
            if not (SOURCE_ADDONS / dep).is_dir():
                continue
            origin = enabled.get(dep, "")
            if origin == BUILTIN_ORIGIN and dep.startswith(("xbmc.", "kodi.", "vfs.", "inputstream.")):
                continue
            selected.add(dep)
            queue.append(dep)
    return sorted(selected)


def should_drop_addon_data_file(path: Path) -> bool:
    lower_name = path.name.lower()
    lower_parts = {part.lower() for part in path.parts}
    if lower_name in DROP_FILENAMES:
        return True
    if any(part in DROP_PATH_PARTS for part in lower_parts):
        return True
    if path.suffix == ".db" and path.name not in KEEP_ADDON_DATA_NAMES:
        return True
    if path.suffix and path.suffix not in KEEP_ADDON_DATA_SUFFIXES and path.name not in KEEP_ADDON_DATA_NAMES:
        return True
    return False


def sanitize_json_value(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(key):
                out[key] = ""
            else:
                out[key] = sanitize_json_value(item)
        return out
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, str):
        return strip_url_credentials(value)
    return value


def sanitize_json_file(src: Path, dest: Path) -> None:
    with src.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    with dest.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_json_value(data), handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def sanitize_settings_xml(src: Path, dest: Path) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    for setting in root.findall(".//setting"):
        setting_id = (setting.get("id") or "").strip()
        if not setting_id:
            continue
        if SENSITIVE_KEY_RE.search(setting_id) or setting_id in SENSITIVE_XML_SETTING_IDS:
            setting.text = ""
        elif setting.text:
            setting.text = strip_url_credentials(setting.text)
    tree.write(dest, encoding="utf-8", xml_declaration=False)


def sanitize_guisettings(src: Path, dest: Path) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    for setting in root.findall(".//setting"):
        setting_id = (setting.get("id") or "").strip()
        if SENSITIVE_KEY_RE.search(setting_id):
            setting.text = ""
        elif setting.text:
            setting.text = strip_url_credentials(setting.text)
    tree.write(dest, encoding="utf-8", xml_declaration=False)


def sanitize_advancedsettings(src: Path, dest: Path) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    for tag in ("user", "pass"):
        for node in root.findall(f".//{tag}"):
            node.text = ""
    for node in root.findall(".//to"):
        if node.text:
            node.text = strip_url_credentials(node.text)
    tree.write(dest, encoding="utf-8", xml_declaration=False)


def copy_text_file(src: Path, dest: Path) -> None:
    shutil.copy2(src, dest)


def strip_url_credentials(value: str) -> str:
    return URL_CREDENTIAL_RE.sub(r"\1", value)


def copy_user_data(staging_root: Path) -> None:
    target_user = staging_root / "userdata"
    target_user.mkdir(parents=True, exist_ok=True)

    for item in SOURCE_USERDATA.iterdir():
        if item.is_file() and item.name in KEEP_USERDATA_FILES:
            dest = target_user / item.name
            if item.name == "guisettings.xml":
                sanitize_guisettings(item, dest)
            elif item.name == "advancedsettings.xml":
                sanitize_advancedsettings(item, dest)
            else:
                copy_text_file(item, dest)
        elif item.is_dir() and item.name in KEEP_USERDATA_DIRS:
            if item.name == "Database":
                copy_databases(item, target_user / item.name)
            elif item.name == "addon_data":
                copy_addon_data(item, target_user / item.name)
            else:
                shutil.copytree(item, target_user / item.name, dirs_exist_ok=True)


def copy_databases(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file() and item.name in KEEP_DATABASES:
            shutil.copy2(item, dest / item.name)


def copy_addon_data(src: Path, dest: Path) -> None:
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        if should_drop_addon_data_file(rel):
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix == ".json":
            sanitize_json_file(item, out)
        elif item.suffix == ".xml":
            sanitize_settings_xml(item, out)
        else:
            shutil.copy2(item, out)


def copy_addons(staging_root: Path, addon_ids: Iterable[str]) -> None:
    target_addons = staging_root / "addons"
    target_addons.mkdir(parents=True, exist_ok=True)
    for addon_id in addon_ids:
        src = SOURCE_ADDONS / addon_id
        if src.is_dir():
            shutil.copytree(
                src,
                target_addons / addon_id,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "*.pyo",
                    "*.md",
                    "LICENSE*",
                    "license*",
                    "changelog*",
                    "CHANGELOG*",
                    "screenshot*.png",
                    "screenshot*.jpg",
                    "screenshot*.jpeg",
                    "fanart.jpg",
                    "fanart.png",
                    "setup_ap.png",
                    "views",
                    "preshow_feature.mp4",
                    "NEXT.mp4",
                    "PREV.mp4",
                ),
            )


def zip_dir(source_dir: Path, output_zip: Path) -> None:
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_dir.rglob("*")):
            archive.write(path, arcname=path.relative_to(source_dir))


def write_metadata(addon_ids: list[str]) -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    info = {
        "source": str(SOURCE_HOME),
        "zip": OUTPUT_ZIP.name,
        "addon_count": len(addon_ids),
        "addons": addon_ids,
        "notes": [
            "Overlay built from the local Kodi profile.",
            "Caches, package downloads, thumbnails, passwords, tokens, and API keys were removed or blanked.",
            "Only selected active addons plus their local dependencies are included to keep the archive GitHub-friendly.",
        ],
    }
    OUTPUT_INFO.write_text(json.dumps(info, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    OUTPUT_HTML.write_text(
        """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kodi Build Overlay</title>
</head>
<body>
  <h1>Kodi Build Overlay</h1>
  <p><a href="build.zip">build.zip</a></p>
  <p><a href="build-info.json">build-info.json</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    enabled = load_enabled_addons()
    addon_ids = resolve_addons(enabled)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kodi-overlay-") as temp_dir:
        staging_root = Path(temp_dir)
        copy_addons(staging_root, addon_ids)
        copy_user_data(staging_root)
        if OUTPUT_ZIP.exists():
            OUTPUT_ZIP.unlink()
        zip_dir(staging_root, OUTPUT_ZIP)
    write_metadata(addon_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
