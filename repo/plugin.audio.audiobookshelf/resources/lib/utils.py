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


def tr(msg_id, fallback=""):
    text = ADDON.getLocalizedString(int(msg_id))
    return text or fallback or str(msg_id)


def log(msg, lvl=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, msg), lvl)


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
