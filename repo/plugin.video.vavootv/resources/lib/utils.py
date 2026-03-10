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

# Safe imports for futhure updates

# import re
# import urllib3
# import resolveurl
# import base64
# import random
# import string

from zlib import compress, decompress

# from urllib.parse import urlencode, parse_qsl, quote_plus
from urllib.parse import urlencode, urlparse, parse_qsl, quote_plus, urlsplit, quote

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
# ADDON INITIALIZATION
# =============================================================================
# These are initialized once when the module is imported

addon = xbmcaddon.Addon()
addonInfo = addon.getAddonInfo
addonID = addonInfo('id')
addonprofile = translatePath(addonInfo('profile'))
addonpath = translatePath(addonInfo('path'))
cachepath = os.path.join(addonprofile, "cache")

# Home window for memory cache storage
# Window 10000 is the home window, properties persist during Kodi session
home = xbmcgui.Window(10000)

# =============================================================================
# CONSTANTS
# =============================================================================
DEFAULT_CACHE_TIMEOUT = 43200
AUTH_API_URL = 'https://www.vavoo.tv/api/app/ping'
AUTH_API_URL_LOKKE = 'https://www.lokke.app/api/app/ping'

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
            except (json.JSONDecodeError, IOError):
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
                except (json.JSONDecodeError, IOError):
                    pass
            else:
                os.remove(filepath)
                removed_count += 1
        
        log_debug(f"Removed {removed_count} cache files", "clear")
    except OSError as e:
        log_debug(f"Error clearing cache: {e}", "clear")


# Cache Clearup in Settings
def clearhard(auto=False):
	for a in os.listdir(cachepath):
		file = os.path.join(cachepath, a)
		key = a.replace(".json", "")
		if auto:
			m = open(file, "rb").read()
			try: data = decompress(m)
			except: data = m
			r = json.loads(data)
			sigValidUntil = r.get('sigValidUntil', 0)
			if sigValidUntil != False and sigValidUntil < int(time.time()):
				os.remove(file)
				home.clearProperty(key)
		else: 
			os.remove(file)
			home.clearProperty(key)
		
clearhard(auto=True)


# =============================================================================
# AUTHENTICATION
# =============================================================================

_auth_cache = {"signature": None, "expires": 0}
AUTH_CACHE_TTL = 3600   # Cache auth signature for 60 minutes

# import resources.lib.authpathdesktop OLD VERSION

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
    

    i = 0
    while i < 5:
        i+=1
        try:
            # Use Android (Vavoo app) user-agent

            _headers = {
				"user-agent": "okhttp/4.11.0", 
				"accept": "application/json", 
				"content-type": "application/json; charset=utf-8", 
				"content-length": "1106", 
				"accept-encoding": "gzip"
				}

            # Standard Vavoo Auth Payload lokke
            _data = {
				"token":"ldCvE092e7gER0rVIajfsXIvRhwlrAzP6_1oEJ4q6HH89QHt24v6NNL_jQJO219hiLOXF2hqEfsUuEWitEIGN4EaHHEHb7Cd7gojc5SQYRFzU3XWo_kMeryAUbcwWnQrnf0-",
				"reason":"app-blur",
				"locale":"de",
				"theme":"dark",
				"metadata":{
					"device":{
						"type":"Handset",
						"brand":"google",
						"model":"Nexus",
						"name":"21081111RG",
						"uniqueId":"d10e5d99ab665233"
						},
						"os":{
							"name":"android",
							"version":"7.1.2",
							"abis":["arm64-v8a"],
							"host":"android"
						},
						"app":{
							"platform":"android",
							"version":"1.1.0",
							"buildId":"97215000",
							"engine":"hbc85",
							"signatures":["6e8a975e3cbf07d5de823a760d4c2547f86c1403105020adee5de67ac510999e"],
							"installer":"com.android.vending"
						},
						"version":{
							"package":"app.lokke.main",
							"binary":"1.1.0",
							"js":"1.1.0"
						},
						"platform":{
							"isAndroid":True,
							"isIOS":False,
							"isTV":False,
							"isWeb":False,
							"isMobile":True,
							"isWebTV":False,
							"isElectron":False}
						},
						"appFocusTime":0,
						"playerActive":False,
						"playDuration":0,
						"devMode":True,
						"hasAddon":True,
						"castConnected":False,
						"package":"app.lokke.main",
						"version":"1.1.0",
						"process":"app",
						"firstAppStart":1772388338206,
						"lastAppStart":1772388338206,
						"ipLocation":None,
						"adblockEnabled":False,
						"proxy":{
							"supported":["ss","openvpn"],
							"engine":"openvpn","ssVersion":1,
							"enabled":False,
							"autoServer":True,
							"id":"fi-hel"
						},
						"iap":{"supported":True}
					}
            log_debug(f"POST {AUTH_API_URL_LOKKE}", "getAuthSignature")
            req = requests.post('https://www.lokke.app/api/app/ping', json=_data, headers=_headers).json()
            log_debug(f"Response status: {req.status_code}", "getAuthSignature")
            return req.get("addonSig")
        except: continue

def gettsSignature():
    i = 0
    while i < 5:
        i+=1
        try:
            vec = {"vec": "9frjpxPjxSNilxJPCJ0XGYs6scej3dW/h/VWlnKUiLSG8IP7mfyDU7NirOlld+VtCKGj03XjetfliDMhIev7wcARo+YTU8KPFuVQP9E2DVXzY2BFo1NhE6qEmPfNDnm74eyl/7iFJ0EETm6XbYyz8IKBkAqPN/Spp3PZ2ulKg3QBSDxcVN4R5zRn7OsgLJ2CNTuWkd/h451lDCp+TtTuvnAEhcQckdsydFhTZCK5IiWrrTIC/d4qDXEd+GtOP4hPdoIuCaNzYfX3lLCwFENC6RZoTBYLrcKVVgbqyQZ7DnLqfLqvf3z0FVUWx9H21liGFpByzdnoxyFkue3NzrFtkRL37xkx9ITucepSYKzUVEfyBh+/3mtzKY26VIRkJFkpf8KVcCRNrTRQn47Wuq4gC7sSwT7eHCAydKSACcUMMdpPSvbvfOmIqeBNA83osX8FPFYUMZsjvYNEE3arbFiGsQlggBKgg1V3oN+5ni3Vjc5InHg/xv476LHDFnNdAJx448ph3DoAiJjr2g4ZTNynfSxdzA68qSuJY8UjyzgDjG0RIMv2h7DlQNjkAXv4k1BrPpfOiOqH67yIarNmkPIwrIV+W9TTV/yRyE1LEgOr4DK8uW2AUtHOPA2gn6P5sgFyi68w55MZBPepddfYTQ+E1N6R/hWnMYPt/i0xSUeMPekX47iucfpFBEv9Uh9zdGiEB+0P3LVMP+q+pbBU4o1NkKyY1V8wH1Wilr0a+q87kEnQ1LWYMMBhaP9yFseGSbYwdeLsX9uR1uPaN+u4woO2g8sw9Y5ze5XMgOVpFCZaut02I5k0U4WPyN5adQjG8sAzxsI3KsV04DEVymj224iqg2Lzz53Xz9yEy+7/85ILQpJ6llCyqpHLFyHq/kJxYPhDUF755WaHJEaFRPxUqbparNX+mCE9Xzy7Q/KTgAPiRS41FHXXv+7XSPp4cy9jli0BVnYf13Xsp28OGs/D8Nl3NgEn3/eUcMN80JRdsOrV62fnBVMBNf36+LbISdvsFAFr0xyuPGmlIETcFyxJkrGZnhHAxwzsvZ+Uwf8lffBfZFPRrNv+tgeeLpatVcHLHZGeTgWWml6tIHwWUqv2TVJeMkAEL5PPS4Gtbscau5HM+FEjtGS+KClfX1CNKvgYJl7mLDEf5ZYQv5kHaoQ6RcPaR6vUNn02zpq5/X3EPIgUKF0r/0ctmoT84B2J1BKfCbctdFY9br7JSJ6DvUxyde68jB+Il6qNcQwTFj4cNErk4x719Y42NoAnnQYC2/qfL/gAhJl8TKMvBt3Bno+va8ve8E0z8yEuMLUqe8OXLce6nCa+L5LYK1aBdb60BYbMeWk1qmG6Nk9OnYLhzDyrd9iHDd7X95OM6X5wiMVZRn5ebw4askTTc50xmrg4eic2U1w1JpSEjdH/u/hXrWKSMWAxaj34uQnMuWxPZEXoVxzGyuUbroXRfkhzpqmqqqOcypjsWPdq5BOUGL/Riwjm6yMI0x9kbO8+VoQ6RYfjAbxNriZ1cQ+AW1fqEgnRWXmjt4Z1M0ygUBi8w71bDML1YG6UHeC2cJ2CCCxSrfycKQhpSdI1QIuwd2eyIpd4LgwrMiY3xNWreAF+qobNxvE7ypKTISNrz0iYIhU0aKNlcGwYd0FXIRfKVBzSBe4MRK2pGLDNO6ytoHxvJweZ8h1XG8RWc4aB5gTnB7Tjiqym4b64lRdj1DPHJnzD4aqRixpXhzYzWVDN2kONCR5i2quYbnVFN4sSfLiKeOwKX4JdmzpYixNZXjLkG14seS6KR0Wl8Itp5IMIWFpnNokjRH76RYRZAcx0jP0V5/GfNNTi5QsEU98en0SiXHQGXnROiHpRUDXTl8FmJORjwXc0AjrEMuQ2FDJDmAIlKUSLhjbIiKw3iaqp5TVyXuz0ZMYBhnqhcwqULqtFSuIKpaW8FgF8QJfP2frADf4kKZG1bQ99MrRrb2A="}
            url = 'https://www.vavoo.tv/api/box/ping2'
            req = requests.post(url, data=vec).json()
            return req['response'].get('signed')
        except: continue

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
    #  except Exception as e:s
        # log(f"Failed to write cache: {e}", "set_cache")
        # log_exception("set_cache")

    except: pass


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