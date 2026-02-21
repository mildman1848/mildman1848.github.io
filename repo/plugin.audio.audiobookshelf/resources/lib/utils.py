# -*- coding: utf-8 -*-
import os
import re
import sys
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
HANDLE = int(sys.argv[1])
BASE = sys.argv[0]

_EN_OVERRIDES = {
    30000: "Audiobooks",
    30001: "Podcasts",
    30002: "Continue Listening",
    30003: "Sync STRM files",
    30004: "Login / Connection Test",
    30005: "Connected as",
    30006: "Home",
    30007: "Recently Added",
    30008: "Current Series",
    30009: "Discover",
    30010: "Listen Again",
    30011: "Latest Authors",
    30012: "Library: All Titles",
    30013: "Series: All Series",
    30014: "Collections: All Collections",
    30015: "Authors: All Authors",
    30016: "Narrators: All Narrators",
    30017: "No items exposed by this ABS endpoint",
    30018: "STRM sync complete",
    30019: "Settings",
    30020: "Continue Series",
    30021: "Server Connection Test",
    30022: "Server reachable",
    30023: "Server not reachable",
    30024: "Endpoint",
    30025: "Search",
    30026: "Stats",
    30027: "Home",
    30028: "Search",
    30029: "Stats",
    30030: "All Podcasts",
    30031: "Recently Added",
    30032: "A-Z",
    30033: "Search: %s",
    30034: "Audiobookshelf Stats",
    30035: "Items",
    30036: "Authors",
    30037: "Genres",
    30038: "Duration",
    30039: "Tracks",
    30040: "Audiobookshelf Search",
    30041: "Library",
    30042: "Series",
    30043: "Authors",
    30044: "Narrators",
    30045: "Collections",
}

_DE_OVERRIDES = {
    30000: "Hörbücher",
    30001: "Podcasts",
    30002: "Weiterhören",
    30003: "STRM-Dateien synchronisieren",
    30004: "Login- / Verbindungstest",
    30005: "Verbunden als",
    30006: "Startseite",
    30007: "Kürzlich hinzugefügt",
    30008: "Aktuelle Serien",
    30009: "Entdecken",
    30010: "Erneut anhören",
    30011: "Neueste Autoren",
    30012: "Bibliothek: Alle Titel",
    30013: "Serien: Alle Serien",
    30014: "Sammlungen: Alle Sammlungen",
    30015: "Autoren: Alle Autoren",
    30016: "Erzähler: Alle Erzähler",
    30017: "Keine Titel über diesen ABS-Endpunkt verfügbar",
    30018: "STRM-Sync abgeschlossen",
    30019: "Einstellungen",
    30020: "Serien fortsetzen",
    30021: "Server-Verbindungstest",
    30022: "Server erreichbar",
    30023: "Server nicht erreichbar",
    30024: "Endpunkt",
    30025: "Suche",
    30026: "Statistiken",
    30027: "Startseite",
    30028: "Suche",
    30029: "Statistiken",
    30030: "Alle Podcasts",
    30031: "Neu hinzugefügt",
    30032: "A-Z",
    30033: "Suche: %s",
    30034: "Audiobookshelf-Statistiken",
    30035: "Titel",
    30036: "Autoren",
    30037: "Genres",
    30038: "Dauer",
    30039: "Tracks",
    30040: "Audiobookshelf Suche",
    30041: "Bibliothek",
    30042: "Serien",
    30043: "Autoren",
    30044: "Erzähler",
    30045: "Sammlungen",
}


def _language_mode():
    raw = (ADDON.getSetting("ui_language") or "").strip()
    if raw.isdigit():
        return int(raw)
    low = raw.lower()
    if "de" in low:
        return 1
    if "en" in low:
        return 2
    return 0


def tr(msg_id, fallback=""):
    mode = _language_mode()
    if mode == 1:
        text = _DE_OVERRIDES.get(int(msg_id), "")
        if text:
            return text
    elif mode == 2:
        text = _EN_OVERRIDES.get(int(msg_id), "")
        if text:
            return text
    text = ADDON.getLocalizedString(int(msg_id))
    return text or fallback or str(msg_id)


def log(msg, lvl=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, msg), lvl)


def debug(msg):
    if ADDON.getSetting("debug_logging") == "true":
        log("DEBUG: %s" % msg, xbmc.LOGINFO)


def notify(title, message):
    xbmcgui.Dialog().notification(title, message, xbmcgui.NOTIFICATION_INFO)


def error(message):
    xbmcgui.Dialog().ok("Audiobookshelf", message)


def params():
    q = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else ""
    return dict(parse_qsl(q))


def plugin_url(**kwargs):
    return BASE + "?" + urlencode(kwargs)


def add_dir(label, action, folder=True, art=None, info=None, **kwargs):
    url = plugin_url(action=action, **kwargs)
    li = xbmcgui.ListItem(label=label)
    if art:
        if isinstance(art, str):
            art = {"thumb": art, "icon": art, "poster": art}
        li.setArt(art)
    if info:
        li.setInfo("music", info)
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=folder)


def add_playable(label, action, art=None, info=None, **kwargs):
    url = plugin_url(action=action, **kwargs)
    li = xbmcgui.ListItem(label=label)
    li.setProperty("IsPlayable", "true")
    if art:
        if isinstance(art, str):
            art = {"thumb": art, "icon": art, "poster": art}
        li.setArt(art)
    if info:
        li.setInfo("music", info)
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)


def end(content="songs"):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def pick_folder(default_path=""):
    return xbmcgui.Dialog().browseSingle(0, "Choose folder", "files", defaultt=default_path)


def ensure_dir(path):
    if not path:
        return False
    if xbmcvfs.exists(path):
        return True
    return xbmcvfs.mkdirs(path)


def safe_filename(name):
    name = re.sub(r"[\\/:*?\"<>|]", "_", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "unnamed"


def write_text(path, text):
    f = xbmcvfs.File(path, "w")
    try:
        f.write(text)
    finally:
        f.close()


def copy_file(src, dst):
    try:
        return bool(xbmcvfs.copy(src, dst))
    except Exception:
        return False


def as_seconds(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def profile_path(*parts):
    base = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
    if parts:
        return os.path.join(base, *parts)
    return base
