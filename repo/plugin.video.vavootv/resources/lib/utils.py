# -*- coding: utf-8 -*-
"""
utils.py - Utility Functions Module

This module provides common utility functions used throughout the addon:
- Path handling and file system operations
- Caching (both in-memory and file-based)
- Authentication with Vavoo API
- Kodi dialog helpers
- Plugin URL building and parameter handling
- Logging utilities

The caching system uses two layers:
1. Memory cache (Kodi home window properties) - fastest, lost on restart
2. File cache (JSON files in addon profile) - persistent across restarts
"""


import os
import sys
import time
import json
import traceback

import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon
import xbmcplugin
import requests
from urllib.parse import urlencode, parse_qsl, quote_plus

# =============================================================================
# ADDON INITIALIZATION
# =============================================================================
# These are initialized once when the module is imported

addon = xbmcaddon.Addon()
addonInfo = addon.getAddonInfo
addonID = addonInfo('id')
addonprofile = xbmcvfs.translatePath(addonInfo('profile'))
addonpath = xbmcvfs.translatePath(addonInfo('path'))
cachepath = os.path.join(addonprofile, "cache")

# Home window for memory cache storage
# Window 10000 is the home window, properties persist during Kodi session
home = xbmcgui.Window(10000)

# =============================================================================
# CONSTANTS
# =============================================================================
DEFAULT_CACHE_TIMEOUT = 43200
AUTH_API_URL = 'https://www.vavoo.tv/api/app/ping'


# =============================================================================
# LOGGING
# =============================================================================

def _is_debug():
    """Check if debug logging is enabled."""
    return addon.getSetting("debug") == "true"


def log(msg, header="", force=False):
    """
    Log a message to Kodi's log file.
    
    Args:
        msg: Message to log (string, dict, or any object)
        header: Optional header/function name for context
        force: If True, always log at INFO level regardless of debug setting
    """
    try:
        if isinstance(msg, (dict, list)):
            msg = json.dumps(msg, indent=4, default=str)
        else:
            msg = str(msg)
    except (TypeError, ValueError):
        msg = str(msg)
    
    prefix = f"[{header}] " if header else ""
    output = f"####VAVOO-TV#### {prefix}{msg}"
    
    if _is_debug() or force:
        xbmc.log(output, xbmc.LOGINFO)
    else:
        xbmc.log(output, xbmc.LOGDEBUG)


def log_debug(msg, header=""):
    """
    Log detailed debug information (only when debug is enabled).
    Includes timestamp and more verbose output.
    """
    if not _is_debug():
        return
    
    timestamp = time.strftime("%H:%M:%S")
    log(f"[{timestamp}] {msg}", header)


def log_exception(header=""):
    """
    Log the current exception with full traceback (only when debug is enabled).
    """
    if _is_debug():
        tb = traceback.format_exc()
        log(f"EXCEPTION:\n{tb}", header, force=True)


# =============================================================================
# PATH UTILITIES
# =============================================================================

def translatePath(*args):
    """
    Translate Kodi special paths to real filesystem paths.
    """
    return xbmcvfs.translatePath(*args)


def exists(path):
    """
    Check if a path exists in the filesystem.
    """
    return os.path.exists(translatePath(path))


# =============================================================================
# CACHE DIRECTORY SETUP
# =============================================================================
if not exists(cachepath):
    os.makedirs(cachepath)
    log_debug(f"Created cache directory: {cachepath}", "init")


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

def _clear_expired_cache():
    """
    Remove expired cache files from disk.
    """
    try:
        removed_count = 0
        for filename in os.listdir(cachepath):
            filepath = os.path.join(cachepath, filename)

            if not os.path.isfile(filepath): 
                continue
            try:
                with open(filepath) as f:
                    data = json.load(f)
                expiry = data.get('sigValidUntil', 0)

                if expiry is not False and expiry < int(time.time()):
                    os.remove(filepath)
                    removed_count += 1
            except: 
                pass
        if removed_count > 0:
            log_debug(f"Cleared {removed_count} expired cache files", "_clear_expired_cache")
    except OSError as e:
        log_debug(f"Error clearing cache: {e}", "_clear_expired_cache")


# Run cache cleanup on import
_clear_expired_cache()


def clear(auto=False):
    """
    Clear cache files.
    """
    log_debug(f"Clearing cache (auto={auto})", "clear")
    try:
        removed_count = 0
        for filename in os.listdir(cachepath):
            filepath = os.path.join(cachepath, filename)

            if not os.path.isfile(filepath): 
                continue
            
            if auto:
                try:
                    with open(filepath) as f: 
                        data = json.load(f)
                    expiry = data.get('sigValidUntil', 0)
                    if expiry is not False and expiry < int(time.time()):
                        os.remove(filepath)
                        removed_count += 1
                except: 
                    pass
            else:
                os.remove(filepath)
                removed_count += 1

        log_debug(f"Removed {removed_count} cache files", "clear")
    except OSError as e:
        log_debug(f"Error clearing cache: {e}", "clear")

# =============================================================================
# AUTHENTICATION
# =============================================================================

_auth_cache = {"signature": None, "expires": 0}
AUTH_CACHE_TTL = 3600   # Cache auth signature for 60 minutes


def getAuthSignature():
    """
    Get authentication signature from Vavoo API.
    Caches the signature for AUTH_CACHE_TTL seconds to avoid redundant requests.
    Returns None and shows error dialog on failure.
    """
    global _auth_cache

    # Return cached signature if still valid
    if _auth_cache["signature"] and time.time() < _auth_cache["expires"]:
        log_debug("Using cached auth signature", "getAuthSignature")
        return _auth_cache["signature"]
    
    log_debug("Requesting fresh auth signature...", "getAuthSignature")
    
    # Use Electron (desktop Vavoo app) user-agent - this is what working proxies use
    headers = {
        "accept": "*/*",
        "user-agent": "electron-fetch/1.0 electron (+https://github.com/arantes555/electron-fetch)",
        "Accept-Language": "de",
        "Accept-Encoding": "gzip, deflate",
        "content-type": "application/json; charset=utf-8",
        "Connection": "close"
    }
    
    import uuid as _uuid
    unique_id = _uuid.uuid4().hex[:16]
    
    # Standard Vavoo Auth Payload
    data = {
        "token": "8Us2TfjeOFrzqFFTEjL3E5KfdAWGa5PV3wQe60uK4BmzlkJRMYFu0ufaM_eeDXKS2U04XUuhbDTgGRJrJARUwzDyCcRToXhW5AcDekfFMfwNUjuieeQ1uzeDB9YWyBL2cn5Al3L3gTnF8Vk1t7rPwkBob0swvxA",
        "reason": "player.enter",
        "locale": "de",
        "theme": "dark",
        "metadata": {
            "device": {
                "type": "Desktop",
                "brand": "Unknown",
                "model": "Unknown",
                "name": "Unknown",
                "uniqueId": unique_id
            },
            "os": {
                "name": "windows",
                "version": "10.0.22631",
                "abis": [],
                "host": "electron"
            },
            "app": {
                "platform": "electron",
                "version": "3.1.4",
                "buildId": "288045000",
                "engine": "jsc",
                "signatures": [],
                "installer": "unknown"
            },
            "version": {
                "package": "tv.vavoo.app",
                "binary": "3.1.4",
                "js": "3.1.4"
            }
        },
        "appFocusTime": 27229,
        "playerActive": True,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": False,
        "castConnected": False,
        "package": "tv.vavoo.app",
        "version": "3.1.4",
        "process": "app",
        "firstAppStart": int(time.time() * 1000) - 86400000,
        "lastAppStart": int(time.time() * 1000),
        "ipLocation": "",
        "adblockEnabled": False,
        "proxy": {
            "supported": ["ss"],
            "engine": "ss",
            "enabled": False,
            "autoServer": True,
            "id": "ca-bhs"
        },
        "iap": {"supported": True}
    }
    
    try:
        log_debug(f"POST {AUTH_API_URL}", "getAuthSignature")
        response = requests.post(AUTH_API_URL, json=data, headers=headers, timeout=10)
        log_debug(f"Response status: {response.status_code}", "getAuthSignature")
        
        result = response.json()
        
        # Log the full response for debugging (helps diagnose watermark/auth issues)
        log(f"Auth ping full response: {json.dumps(result, indent=2)}", "getAuthSignature", force=True)
        
        signature = result.get("addonSig")

        if signature:
            log_debug("Auth signature obtained successfully", "getAuthSignature")
            
            # Decode and log signature data to check status
            try:
                import base64
                sig_data = json.loads(base64.b64decode(signature + '=='))
                inner = json.loads(sig_data.get("data", "{}"))
                log(f"Auth status: status={inner.get('status')}, verified={inner.get('verified')}, app_ok={inner.get('app', {}).get('ok')}", "getAuthSignature", force=True)
            except Exception:
                pass
            
            _auth_cache["signature"] = signature
            _auth_cache["expires"] = time.time() + AUTH_CACHE_TTL
            return signature
        else:
            log(f"No addonSig in response: {result}", "getAuthSignature", force=True)
            error_dialog("Authentication Failed", "Failed to get auth signature from server.")
            return None

    except requests.exceptions.Timeout:
        log("Auth request timed out", "getAuthSignature", force=True)
        log_exception("getAuthSignature")
        error_dialog("Authentication Failed", "Request timed out. Please check your internet connection.")
        return None
    except requests.exceptions.RequestException as e:
        log(f"Auth request failed: {e}", "getAuthSignature", force=True)
        log_exception("getAuthSignature")
        error_dialog("Authentication Failed", f"Network error: {str(e)}")
        return None
    except Exception as e:
        log(f"Unexpected auth error: {e}", "getAuthSignature", force=True)
        log_exception("getAuthSignature")
        error_dialog("Authentication Failed", f"Unexpected error: {str(e)}")
        return None

# =============================================================================
# URL/HEADER UTILITIES
# =============================================================================

def append_headers(headers):
    """
    Format headers dictionary for use in URL parameter string.
    """
    return '|' + '&'.join(
        f'{key}={quote_plus(value)}'
        for key, value in headers.items()
    )


# =============================================================================
# DIALOG UTILITIES
# =============================================================================

def error_dialog(heading, message):
    """
    Show an error dialog that requires user to press OK.
    
    Args:
        heading: Dialog title
        message: Error message to display
    """
    log_debug(f"Showing error dialog: {heading} - {message}", "error_dialog")
    xbmcgui.Dialog().ok(f"VavooTV - {heading}", message)


def selectDialog(options, heading=None, multiselect=False):
    """
    Show a selection dialog to the user.
    """
    if heading is None: 
        heading = addonInfo('name')

    log_debug(f"Selection dialog: {heading}, options={len(options)}, multiselect={multiselect}", "selectDialog")

    dialog = xbmcgui.Dialog()
    if multiselect:
        result = dialog.multiselect(str(heading), options)
    else:
        result = dialog.select(str(heading), options)
    
    log_debug(f"Selection result: {result}", "selectDialog")
    return result
    

# =============================================================================
# CACHING SYSTEM
# =============================================================================

def _get_cache_path(key):
    """
    Convert a cache key to a valid filename.
    """
    if isinstance(key, dict):
        parts = [urlencode({k: str(v) if isinstance(v, int) else v})
                 for k, v in key.items()]
        return '&'.join(parts)
    return key


def set_cache(key, value, timeout=DEFAULT_CACHE_TIMEOUT):
    """
    Store a value in the cache.
    """
    path = _get_cache_path(key)
    log_debug(f"Setting cache: {path} (timeout={timeout}s)", "set_cache")
    
    expiry = False if timeout is False else int(time.time()) + timeout
    data = {"sigValidUntil": expiry, "value": value}
    
    home.setProperty(path, json.dumps(data))
    
    filepath = os.path.join(cachepath, f"{path}.json")
    try:
        with xbmcvfs.File(filepath, "w") as f:
            json.dump(data, f, indent=4)
        log_debug(f"Cache written to file: {filepath}", "set_cache")
    except Exception as e:
        log(f"Failed to write cache: {e}", "set_cache")
        log_exception("set_cache")


def get_cache(key):
    """
    Retrieve a value from the cache.
    """
    path = _get_cache_path(key)
    current_time = int(time.time())

    log_debug(f"Getting cache: {path}", "get_cache")
    
    # Try memory cache first
    cached = home.getProperty(path)
    if cached:
        try:
            data = json.loads(cached)
            expiry = data.get('sigValidUntil', 0)

            if expiry is False or expiry > current_time: 
                log_debug(f"Cache hit (memory): {path}", "get_cache")
                return data.get('value')
            
            log_debug(f"Cache expired (memory): {path}", "get_cache")
            home.clearProperty(path)
        except json.JSONDecodeError:
            home.clearProperty(path)
    
    # Try file cache
    filepath = os.path.join(cachepath, f"{path}.json")
    try:
        with open(filepath) as f: 
            data = json.load(f)

        expiry = data.get('sigValidUntil', 0)

        if expiry is False or expiry > current_time:
            value = data.get('value')
            home.setProperty(path, json.dumps({"sigValidUntil": expiry, "value": value}))
            log_debug(f"Cache hit (file): {path}", "get_cache")
            return value
        
        log_debug(f"Cache expired (file): {path}", "get_cache")
        os.remove(filepath)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    
    log_debug(f"Cache miss: {path}", "get_cache")
    return None

# =============================================================================
# PLUGIN FRAMEWORK UTILITIES
# =============================================================================

def _get_handle(): 
    """
    Get the plugin handle from command line arguments.
    """
    return int(sys.argv[1])


def end(succeeded=True, cacheToDisc=True): 
    """
    End the directory listing.
    """
    log_debug(f"Ending directory (succeeded={succeeded}, cacheToDisc={cacheToDisc})", "end")
    return xbmcplugin.endOfDirectory(_get_handle(), succeeded=succeeded, cacheToDisc=cacheToDisc)


def add(params, listitem, isFolder=False): 
    
    url = url_for(params)
    log_debug(f"Adding item: {url}, isFolder={isFolder}", "add")
    return xbmcplugin.addDirectoryItem(_get_handle(), url, listitem, isFolder)


def add_items(items):
    """
    Add multiple items to the directory listing at once (faster than individual adds).
    
    Args:
        items: list of (url_params_dict, listitem, isFolder) tuples
    """
    handle = _get_handle()
    entries = []
    for params, listitem, isFolder in items:
        url = url_for(params)
        entries.append((url, listitem, isFolder))
    log_debug(f"Batch adding {len(entries)} items", "add_items")
    return xbmcplugin.addDirectoryItems(handle, entries, len(entries))


def notify(message, heading="VavooTV", icon=xbmcgui.NOTIFICATION_INFO, time_ms=3000):
    """
    Show a non-blocking notification toast.
    """
    xbmcgui.Dialog().notification(heading, message, icon, time_ms)

def set_category(category):
    """
    Set the plugin category for the current listing.
    """
    log_debug(f"Setting category: {category}", "set_category")
    xbmcplugin.setPluginCategory(_get_handle(), category)


def set_content(content_type): 
    """
    Set the content type for the directory.
    """
    log_debug(f"Setting content type: {content_type}", "set_content")
    xbmcplugin.setContent(_get_handle(), content_type)


def set_resolved(listitem): 
    """
    Set the resolved URL for playback.
    """
    log_debug("Setting resolved URL", "set_resolved")
    xbmcplugin.setResolvedUrl(_get_handle(), True, listitem)


def sort_method(): 
    """
    Add video title sort method to the directory.
    """  
    log_debug("Adding sort method: VIDEO_TITLE", "sort_method")
    xbmcplugin.addSortMethod(_get_handle(), xbmcplugin.SORT_METHOD_VIDEO_TITLE)


# =============================================================================
# URL BUILDING
# =============================================================================

def convertPluginParams(params):
    """
    Convert a parameters dictionary to URL-encoded string.
    """
    if isinstance(params, dict):
        parts = [urlencode({k: str(v) if isinstance(v, int) else v}) 
                 for k, v in params.items()]
        return '&'.join(parts)
    return params

def url_for(params):
    """
    Build a plugin URL from parameters.
    """
    return f"{sys.argv[0]}?{convertPluginParams(params)}"


# =============================================================================
# TV FAVORITES MANAGEMENT
# =============================================================================
# Favorites are stored as a JSON file in the addon profile directory.
# Each favorite is {"name": "ChannelName", "group": "GroupName", "nickname": "OptionalNick"}

_favorites_path = os.path.join(addonprofile, "tv_favorites.json")


def _load_favorites():
    """Load TV favorites from disk. Returns list of dicts."""
    try:
        if os.path.exists(_favorites_path):
            with open(_favorites_path, "r") as f:
                data = json.load(f)
            # Ensure it's a list of dicts (not old-style list of strings)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, IOError, OSError) as e:
        log_debug(f"Error loading favorites: {e}", "_load_favorites")
    return []


def _save_favorites(favorites):
    """Save TV favorites to disk."""
    try:
        with open(_favorites_path, "w") as f:
            json.dump(favorites, f, indent=2)
        log_debug(f"Saved {len(favorites)} favorites", "_save_favorites")
    except (IOError, OSError) as e:
        log(f"Error saving favorites: {e}", "_save_favorites", force=True)


def get_favorites():
    """Get list of TV favorites."""
    return _load_favorites()


def get_favorite_names():
    """Get set of favorite channel names for quick lookup."""
    return {fav["name"] for fav in _load_favorites() if isinstance(fav, dict)}


def add_favorite(name, group):
    """Add a channel to TV favorites."""
    favorites = _load_favorites()
    # Check if already exists
    for fav in favorites:
        if isinstance(fav, dict) and fav.get("name") == name:
            log_debug(f"Channel already in favorites: {name}", "add_favorite")
            return
    # Add with empty nickname by default
    favorites.append({"name": name, "group": group, "nickname": ""})
    _save_favorites(favorites)
    log_debug(f"Added to favorites: {name} (group={group})", "add_favorite")


def rename_favorite(name, new_nickname):
    """Rename a favorite (add/update nickname)."""
    favorites = _load_favorites()
    found = False
    for fav in favorites:
        if isinstance(fav, dict) and fav.get("name") == name:
            fav["nickname"] = new_nickname
            found = True
            break
    if found:
        _save_favorites(favorites)
        log_debug(f"Renamed favorite {name} to {new_nickname}", "rename_favorite")


def move_favorite(name, direction):
    """
    Move a favorite in the list.
    Direction: 'up', 'down', 'top', or 'bottom'
    """
    favorites = _load_favorites()
    # Find index of item
    idx = -1
    for i, fav in enumerate(favorites):
        if isinstance(fav, dict) and fav.get("name") == name:
            idx = i
            break
            
    if idx == -1:
        return

    if direction == "up" and idx > 0:
        # Swap with previous
        favorites[idx], favorites[idx-1] = favorites[idx-1], favorites[idx]
        _save_favorites(favorites)
        log_debug(f"Moved favorite {name} UP", "move_favorite")
        
    elif direction == "down" and idx < len(favorites) - 1:
        # Swap with next
        favorites[idx], favorites[idx+1] = favorites[idx+1], favorites[idx]
        _save_favorites(favorites)
        log_debug(f"Moved favorite {name} DOWN", "move_favorite")

    elif direction == "top" and idx > 0:
        # Move to beginning of list
        item = favorites.pop(idx)
        favorites.insert(0, item)
        _save_favorites(favorites)
        log_debug(f"Moved favorite {name} TO TOP", "move_favorite")

    elif direction == "bottom" and idx < len(favorites) - 1:
        # Move to end of list
        item = favorites.pop(idx)
        favorites.append(item)
        _save_favorites(favorites)
        log_debug(f"Moved favorite {name} TO BOTTOM", "move_favorite")


def remove_favorite(name):
    """Remove a channel from TV favorites."""
    favorites = _load_favorites()
    favorites = [fav for fav in favorites if not (isinstance(fav, dict) and fav.get("name") == name)]
    _save_favorites(favorites)
    log_debug(f"Removed from favorites: {name}", "remove_favorite")


def clear_all_favorites():
    """Remove all TV favorites."""
    _save_favorites([])
    log_debug("All favorites cleared", "clear_all_favorites")


def is_favorite(name):
    """Check if a channel is in TV favorites."""
    return name in get_favorite_names()


def export_favorites():
    """
    Export TV favorites to a user-chosen location via file manager.
    Saves as VavooTV-Favorites-YYYY-MM-DD.json.
    """
    from datetime import datetime

    favorites = _load_favorites()
    if not favorites:
        xbmcgui.Dialog().ok("VavooTV", "No favorites to export.")
        return

    # Prompt user to pick a folder
    dest_folder = xbmcgui.Dialog().browse(0, "Select Export Location", "files")
    if not dest_folder:
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"VavooTV-Favorites-{date_str}.json"
    # Use dest_folder directly (keep VFS protocol paths like smb:// intact)
    dest_path = dest_folder + filename

    try:
        content = json.dumps(favorites, indent=2)
        f = xbmcvfs.File(dest_path, "w")
        f.write(content)
        f.close()
        log_debug(f"Exported {len(favorites)} favorites to {dest_path}", "export_favorites")
        xbmcgui.Dialog().ok(
            "VavooTV",
            "Favorites successfully exported!\n"
            f"Path: {dest_path}"
        )
    except (IOError, OSError) as e:
        log(f"Error exporting favorites: {e}", "export_favorites", force=True)
        xbmcgui.Dialog().ok("VavooTV", f"Export failed:\n{e}")


def import_favorites():
    """
    Import TV favorites from a user-chosen JSON file via file manager.
    Replaces current favorites with imported ones.
    """
    # Prompt user to pick a .json file
    source_file = xbmcgui.Dialog().browse(1, "Select Favorites File", "files", ".json")
    if not source_file:
        return

    # source_file is already a VFS-compatible path from the browse dialog
    source_path = source_file

    try:
        f = xbmcvfs.File(source_path, "r")
        content = f.read()
        f.close()
        data = json.loads(content)

        # Validate structure: must be a list of dicts with at least "name"
        if not isinstance(data, list):
            xbmcgui.Dialog().ok("VavooTV", "Invalid file format.\nExpected a list of favorites.")
            return

        for item in data:
            if not isinstance(item, dict) or "name" not in item:
                xbmcgui.Dialog().ok("VavooTV", "Invalid file format.\nEach entry must have a 'name' field.")
                return

        _save_favorites(data)
        log_debug(f"Imported {len(data)} favorites from {source_path}", "import_favorites")
        xbmcgui.Dialog().ok(
            "VavooTV",
            f"Favorites imported successfully!\n{len(data)} channels loaded."
        )
        xbmc.executebuiltin("Container.Refresh")

    except json.JSONDecodeError:
        xbmcgui.Dialog().ok("VavooTV", "Invalid JSON file.\nPlease select a valid favorites file.")
    except (IOError, OSError) as e:
        log(f"Error importing favorites: {e}", "import_favorites", force=True)
        xbmcgui.Dialog().ok("VavooTV", f"Import failed:\n{e}")