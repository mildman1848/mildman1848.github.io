# -*- coding: utf-8 -*-
"""
vjlive.py - Live TV Channel Management Module

This module handles all live TV streaming functionality including:
- Fetching channel lists from the Vavoo API
- Merging duplicate channels (e.g., "Channel .s" and "Channel .b" -> "Channel")
- Resolving stream URLs for playback
- Managing channel caching for performance
- Handling stream selection and playback
"""

import sys
import re
import json
import time
import datetime
import os

import requests
import xbmc
import xbmcgui
import xbmcvfs

from resources.lib import utils

from urllib.parse import quote as url_quote
from urllib.parse import quote_plus

# =============================================================================
# INFOTAGGER SUPPORT
# =============================================================================
try:
    from infotagger.listitem import ListItemInfoTag
    TAGGER_AVAILABLE = True
except ImportError:
    TAGGER_AVAILABLE = False

# =============================================================================
# CONSTANTS
# =============================================================================
CACHE_TIMEOUT = 10800         # Channel cache duration: 3 hours
COUNTRY_CACHE_TIMEOUT = 18000 # Country list cache duration: 5 hours
REQUEST_TIMEOUT = 10          # HTTP request timeout in seconds

# API endpoints
API_BASE_URL = "https://vavoo.to"
INDEX_URL = "https://www2.vavoo.to/live2/index"


# =============================================================================
# GLOBAL STATE
# =============================================================================
_channels_cache = None
_channels_cache_time = 0
_session = None


# =============================================================================
# HTTP SESSION MANAGEMENT
# =============================================================================

def _get_session():
    """Get or create a persistent requests session."""
    global _session
    if _session is None:
        utils.log_debug("Creating new HTTP session", "_get_session")
        _session = requests.Session()
        _session.headers.update({
            'User-Agent': 'electron-fetch/1.0 electron (+https://github.com/arantes555/electron-fetch)',
            'Accept': '*/*',
            'Accept-Language': 'de',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'close'
        })
    return _session


def _get_api_headers():
    """Get headers required for authenticated API requests."""
    utils.log_debug("Building API headers with auth signature", "_get_api_headers")
    signature = utils.getAuthSignature()
    
    if not signature:
        utils.log("Failed to get auth signature - headers will be incomplete", "_get_api_headers", force=True)
    
    return {
        "accept": "*/*",
        "user-agent": "electron-fetch/1.0 electron (+https://github.com/arantes555/electron-fetch)",
        "Accept-Language": "de",
        "Accept-Encoding": "gzip, deflate",
        "content-type": "application/json; charset=utf-8",
        "Connection": "close",
        "mediahubmx-signature": signature
    }


def _make_request(method, url, silent=False, **kwargs):
    """
    Make an HTTP request with automatic fallback.
    Shows error dialog on failure unless silent=True.
    """
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)
    session = _get_session()
    
    utils.log_debug(f"Making {method.upper()} request to: {url}", "_make_request")
    utils.log_debug(f"Request kwargs: {kwargs}", "_make_request")
    
    try:
        if method == 'get':
            response = session.get(url, **kwargs)
        else:
            response = session.post(url, **kwargs)
        
        utils.log_debug(f"Response status: {response.status_code}", "_make_request")
        utils.log_debug(f"Response headers: {dict(response.headers)}", "_make_request")
        
        result = response.json()
        utils.log_debug(f"Response JSON keys: {list(result.keys()) if isinstance(result, dict) else 'list'}", "_make_request")
        return result
        
    except requests.exceptions.Timeout:
        utils.log(f"Request timed out: {url}", "_make_request", force=True)
        utils.log_exception("_make_request")
        if not silent:
            utils.error_dialog("Request Failed", f"Request timed out.\nPlease check your internet connection.")
        raise
        
    except requests.exceptions.ConnectionError as e:
        utils.log(f"Connection error: {url} - {e}", "_make_request", force=True)
        utils.log_exception("_make_request")
        if not silent:
            utils.error_dialog("Connection Error", f"Could not connect to server.\nPlease check your internet connection.")
        raise
        
    except requests.exceptions.RequestException as e:
        utils.log(f"Request failed: {url} - {e}", "_make_request", force=True)
        utils.log_exception("_make_request")
        if not silent:
            utils.error_dialog("Request Failed", f"Network error: {str(e)}")
        raise
        
    except json.JSONDecodeError as e:
        utils.log(f"Invalid JSON response from: {url}", "_make_request", force=True)
        utils.log_exception("_make_request")
        if not silent:
            utils.error_dialog("Invalid Response", "Server returned invalid data.\nPlease try again later.")
        raise
        
    except Exception as e:
        utils.log(f"Unexpected error during request: {e}", "_make_request", force=True)
        utils.log_exception("_make_request")
        
        # Try fallback without session
        utils.log_debug("Attempting fallback request without session", "_make_request")
        try:
            if method == 'get':
                return requests.get(url, **kwargs).json()
            return requests.post(url, **kwargs).json()
        except Exception as fallback_error:
            utils.log(f"Fallback request also failed: {fallback_error}", "_make_request", force=True)
            if not silent:
                utils.error_dialog("Request Failed", f"Failed to fetch data: {str(e)}")
            raise


# =============================================================================
# CHANNEL NAME NORMALIZATION
# =============================================================================

def _normalize_channel_name(name):
    """
    Normalize channel name by removing suffixes like .s, .b, etc.
    """
    normalized = re.sub(r'\s+\.[a-zA-Z]$', '', name.strip())
    utils.log_debug(f"Normalized '{name}' -> '{normalized}'", "_normalize_channel_name")
    return normalized


# =============================================================================
# STREAM RESOLUTION
# =============================================================================

def _follow_stream_url(url, timeout=10):
    """
    Follow a resolved URL through any redirects to get the final stream URL.
    Also returns any headers needed for playback.
    Bypasses interstitial/ad pages (e.g. 'Download Looke' prompts).
    """
    utils.log_debug(f"Following stream URL: {url}", "_follow_stream_url")
    
    stream_headers = {
        'User-Agent': 'electron-fetch/1.0 electron (+https://github.com/arantes555/electron-fetch)',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'close',
    }
    
    try:
        session = _get_session()
        # Follow redirects manually to capture the final URL
        resp = session.head(url, headers=stream_headers, timeout=timeout, allow_redirects=True)
        final_url = resp.url
        utils.log_debug(f"Final URL after redirects: {final_url}", "_follow_stream_url")
        
        # If the final URL looks like an HTML page (ad/paywall), try GET to extract stream
        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' in content_type:
            utils.log_debug("Detected HTML redirect (possible ad page), trying to extract stream URL", "_follow_stream_url")
            resp_get = session.get(url, headers=stream_headers, timeout=timeout, allow_redirects=True)
            # Look for .m3u8 or .ts URLs in the page
            import re
            m3u8_matches = re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', resp_get.text)
            if m3u8_matches:
                final_url = m3u8_matches[0]
                utils.log_debug(f"Extracted m3u8 URL from HTML: {final_url}", "_follow_stream_url")
            else:
                # Try finding any stream-like URL
                stream_matches = re.findall(r'(https?://[^\s"\'<>]+(?:\.ts|/live/|/stream/|/playlist|/index)[^\s"\'<>]*)', resp_get.text)
                if stream_matches:
                    final_url = stream_matches[0]
                    utils.log_debug(f"Extracted stream URL from HTML: {final_url}", "_follow_stream_url")
        
        return final_url, stream_headers
        
    except Exception as e:
        utils.log_debug(f"Failed to follow URL, using original: {e}", "_follow_stream_url")
        return url, stream_headers


def resolve_link(link, timeout=10, silent=False):
    """
    Resolve a channel link to a playable stream URL.
    
    Args:
        link: The channel URL to resolve
        timeout: Request timeout in seconds (default 10)
        silent: If True, suppress error dialogs (for auto-play)
    """
    utils.log_debug(f"Resolving link: {link} (timeout={timeout}s, silent={silent})", "resolve_link")
    
    headers = _get_api_headers()
    signature = headers.get("mediahubmx-signature", "")
    data = {
        "language": "de",
        "region": "AT",
        "url": link,
        "clientVersion": "3.1.4"
    }
    url = f"{API_BASE_URL}/mediahubmx-resolve.json"
    
    utils.log_debug(f"Resolve request data: {data}", "resolve_link")
    
    try:
        result = _make_request('post', url, silent=silent, data=json.dumps(data), headers=headers, timeout=timeout)
        utils.log_debug(f"Resolve response: {result}", "resolve_link")
        
        resolved_url = result[0]["url"]
        utils.log_debug(f"Resolved URL (raw): {resolved_url}", "resolve_link")
        
        # Extract any custom headers the API wants us to use
        resolve_headers = result[0].get("headers", {})
        utils.log_debug(f"Resolve headers from API: {resolve_headers}", "resolve_link")
        
        # Follow redirects to get the actual stream URL (bypass ad/interstitial pages)
        final_url, stream_headers = _follow_stream_url(resolved_url, timeout=timeout)
        
        # Merge any API-provided headers
        if resolve_headers:
            stream_headers.update(resolve_headers)
        
        # Pass the auth signature to the CDN - it may use this to determine watermark
        if signature:
            stream_headers["mediahubmx-signature"] = signature
        
        # Set Referer to vavoo.to
        stream_headers["Referer"] = "https://vavoo.to/"
        stream_headers["Origin"] = "https://vavoo.to"
        
        utils.log_debug(f"Final resolved URL: {final_url}", "resolve_link")
        return final_url, stream_headers
        
    except (KeyError, IndexError, TypeError) as e:
        utils.log(f"Failed to parse resolve response: {e}", "resolve_link", force=True)
        utils.log_exception("resolve_link")
        raise


# =============================================================================
# COUNTRY/REGION MANAGEMENT
# =============================================================================

def get_available_countries(use_cache=True):
    """Get list of countries/regions that have available streams."""
    utils.log_debug(f"Getting available countries (use_cache={use_cache})", "get_available_countries")
    cache_key = "available_countries"
    
    if use_cache:
        cached = utils.get_cache(cache_key)
        if cached:
            utils.log_debug(f"Returning cached countries: {cached}", "get_available_countries")
            return cached
    
    available_countries = []
    
    try:
        utils.log_debug(f"Fetching countries from: {INDEX_URL}", "get_available_countries")
        group_data = _make_request('get', INDEX_URL, params={"output": "json"}, timeout=10)
        
        utils.log_debug(f"Received {len(group_data)} items from API", "get_available_countries")
        
        seen = set()
        for item in group_data:
            group = item.get("group")
            # Dynamic fetching: accept any group returned by the API
            # Removed hardcoded VALID_COUNTRIES check
            if group and group not in seen:
                available_countries.append(group)
                seen.add(group)
                utils.log_debug(f"Found country: {group}", "get_available_countries")
                
    except Exception as e:
        utils.log(f"Failed to fetch countries: {e}", "get_available_countries", force=True)
        utils.log_exception("get_available_countries")
        # Fallback set to Germany only
        available_countries = ["Germany"]
        utils.log_debug(f"Using fallback countries: {available_countries}", "get_available_countries")
    
    available_countries.sort()
    utils.log_debug(f"Final country list: {available_countries}", "get_available_countries")
    
    if available_countries:
        utils.set_cache(cache_key, available_countries, COUNTRY_CACHE_TIMEOUT)
    
    return available_countries


# =============================================================================
# CHANNEL FETCHING
# =============================================================================

def _fetch_channels_page(group, cursor=0):
    """Fetch a single page of channels for a group."""
    utils.log_debug(f"Fetching channels page: group={group}, cursor={cursor}", "_fetch_channels_page")
    
    headers = _get_api_headers()
    data = {
        "language": "de",
        "region": "AT",
        "catalogId": "vto-iptv",
        "id": "vto-iptv",
        "adult": False,
        "search": "",
        "sort": "name",
        "filter": {"group": group},
        "cursor": cursor,
        "count": 9999,
        "clientVersion": "3.1.4"
    }
    
    url = f"{API_BASE_URL}/mediahubmx-catalog.json"
    result = _make_request('post', url, data=json.dumps(data), headers=headers)
    
    items_count = len(result.get("items", []))
    next_cursor = result.get("nextCursor")
    utils.log_debug(f"Received {items_count} items, nextCursor={next_cursor}", "_fetch_channels_page")
    
    return result


def _collect_channels(group, channels, germany_filter=False):
    """
    Collect all channels for a group (handles pagination).
    Normalizes channel names to merge duplicates.
    Paginates through ALL pages to ensure no channels are missing.
    """
    utils.log_debug(f"Collecting channels for group: {group} (germany_filter={germany_filter})", "_collect_channels")
    cursor = 0
    total_collected = 0
    page_num = 0
    max_pages = 100  # Safety limit to prevent infinite loops
    seen_cursors = set()
    
    while page_num < max_pages:
        page_num += 1
        utils.log_debug(f"Fetching page {page_num} for group '{group}' (cursor={cursor})", "_collect_channels")
        
        response = _fetch_channels_page(group, cursor)
        items = response.get("items", [])
        
        utils.log_debug(f"Processing {len(items)} items from page {page_num}", "_collect_channels")
        
        if not items:
            utils.log_debug(f"No items on page {page_num}, stopping pagination", "_collect_channels")
            break
        
        for item in items:
            raw_name = item.get("name", "").strip()
            item_url = item.get("url")
            
            if not item_url or not raw_name:
                utils.log_debug(f"Skipping invalid item: name='{raw_name}', url={bool(item_url)}", "_collect_channels")
                continue
            
            if germany_filter:
                if not any(marker in raw_name for marker in ["DE :", " |D"]):
                    continue
            
            normalized_name = _normalize_channel_name(raw_name)
            
            if normalized_name not in channels:
                channels[normalized_name] = []
            channels[normalized_name].append(item_url)
            total_collected += 1
        
        # Get next cursor - handle both int and string cursor types
        next_cursor = response.get("nextCursor")
        
        if next_cursor is None or next_cursor == "" or next_cursor == 0 or next_cursor == "null":
            utils.log_debug(f"No more pages (nextCursor={next_cursor})", "_collect_channels")
            break
        
        # Prevent infinite loop from repeated cursors
        cursor_key = str(next_cursor)
        if cursor_key in seen_cursors:
            utils.log_debug(f"Duplicate cursor detected ({cursor_key}), stopping", "_collect_channels")
            break
        seen_cursors.add(cursor_key)
        
        cursor = next_cursor
    
    if page_num >= max_pages:
        utils.log(f"WARNING: Hit max pages limit ({max_pages}) for group '{group}'", "_collect_channels", force=True)
    
    utils.log_debug(f"Collected {total_collected} channel URLs across {page_num} page(s) for group: {group}", "_collect_channels")


def getchannels(selected_groups=None, use_cache=True):
    """Get all channels from selected groups."""
    global _channels_cache, _channels_cache_time
    
    utils.log_debug(f"Getting channels (selected_groups={selected_groups}, use_cache={use_cache})", "getchannels")
    
    if use_cache and _channels_cache is not None:
        cache_age = time.time() - _channels_cache_time
        if cache_age < CACHE_TIMEOUT:
            utils.log_debug(f"Returning cached channels (age={cache_age:.0f}s)", "getchannels")
            return _channels_cache
        utils.log_debug(f"Cache expired (age={cache_age:.0f}s > {CACHE_TIMEOUT}s)", "getchannels")
    
    channels = {}
    
    if selected_groups is None:
        selected_groups = get_available_countries(use_cache)
    
    utils.log_debug(f"Fetching channels for groups: {selected_groups}", "getchannels")
    
    if "Germany" in selected_groups:
        utils.log_debug("Adding German channels from Balkans group", "getchannels")
        _collect_channels("Balkans", channels, germany_filter=True)
    
    for group in selected_groups:
        _collect_channels(group, channels)
    
    _channels_cache = channels
    _channels_cache_time = time.time()
    
    utils.log_debug(f"Total unique channels: {len(channels)}", "getchannels")
    return channels


def getchannels_by_group(group):
    """Get channels for a specific group. Uses file cache and populates global cache for playback."""
    global _channels_cache, _channels_cache_time
    
    utils.log_debug(f"Getting channels for single group: {group}", "getchannels_by_group")
    
    # Try file-based cache first (survives across plugin invocations)
    cache_key = f"channels_group_{group}"
    cached = utils.get_cache(cache_key)
    if cached:
        utils.log_debug(f"Returning cached channels for group: {group} ({len(cached)} channels)", "getchannels_by_group")
        # Still populate global cache for playback
        if _channels_cache is None:
            _channels_cache = {}
        _channels_cache.update(cached)
        _channels_cache_time = time.time()
        return cached
    
    channels = {}
    
    # For Germany, also pull DE-tagged channels from Balkans (same logic as getchannels)
    if group == "Germany":
        utils.log_debug("Adding German channels from Balkans group", "getchannels_by_group")
        _collect_channels("Balkans", channels, germany_filter=True)
    
    _collect_channels(group, channels)
    utils.log_debug(f"Found {len(channels)} channels in group: {group}", "getchannels_by_group")
    
    # Cache to file for faster subsequent loads
    utils.set_cache(cache_key, channels, CACHE_TIMEOUT)
    
    # Merge into global cache so channels are available for playback via livePlay
    if _channels_cache is None:
        _channels_cache = {}
    _channels_cache.update(channels)
    _channels_cache_time = time.time()
    utils.log_debug(f"Global cache updated, total channels: {len(_channels_cache)}", "getchannels_by_group")
    
    return channels


# =============================================================================
# STREAM SELECTION UI
# =============================================================================

def refresh_channels():
    """Force-clear all channel caches."""
    global _channels_cache, _channels_cache_time
    _channels_cache = None
    _channels_cache_time = 0
    utils.clear(auto=False)
    utils.log_debug("All channel caches cleared", "refresh_channels")


def refresh_country_cache():
    """Clear only the country list cache so it re-fetches from API."""
    utils.log_debug("Clearing country cache", "refresh_country_cache")
    # Clear the file/memory cache for the country key
    cache_key = "available_countries"
    try:
        import os
        filepath = os.path.join(utils.cachepath, f"{cache_key}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass
    utils.home.clearProperty(cache_key)


def refresh_group_cache(group):
    """Clear channel cache for a specific group so it re-fetches from API."""
    global _channels_cache
    utils.log_debug(f"Clearing cache for group: {group}", "refresh_group_cache")
    cache_key = f"channels_group_{group}"
    try:
        import os
        filepath = os.path.join(utils.cachepath, f"{cache_key}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass
    utils.home.clearProperty(cache_key)
    # Invalidate the whole in-memory cache since we can't tell which keys belong to this group
    if _channels_cache is not None:
        _channels_cache = None

def _show_stream_selection_dialog(channel_name, stream_count):
    """Show dialog for stream selection with Auto Play as first option."""
    utils.log_debug(f"Showing stream selection: {channel_name} ({stream_count} streams)", "_show_stream_selection_dialog")
    options = ["Auto Play"] + [f"STREAM {i}" for i in range(1, stream_count + 1)]
    return utils.selectDialog(options)


def _select_stream(name, urls):
    """
    Select which stream to play.
    
    Returns:
        (index, title, None) where index is:
            -2  = auto play (try all streams)
            -1  = user cancelled
             0+ = specific stream index
    """
    stream_count = len(urls)
    
    utils.log_debug(f"Selecting stream for '{name}' ({stream_count} available)", "_select_stream")
    
    if stream_count <= 1:
        utils.log_debug("Only one stream available, auto-selecting", "_select_stream")
        return 0, name, None
    
    # Show selection dialog (index 0 = Auto Play, 1+ = specific stream)
    dialog_index = _show_stream_selection_dialog(name, stream_count)
    if dialog_index < 0:
        utils.log_debug("User cancelled stream selection", "_select_stream")
        return -1, None, None
    
    if dialog_index == 0:
        # Auto Play selected
        utils.log_debug("User selected Auto Play", "_select_stream")
        return -2, name, None
    
    # Specific stream selected (dialog index 1 = stream 0, etc.)
    stream_idx = dialog_index - 1
    title = f"{name} ({stream_idx + 1}/{stream_count})"
    utils.log_debug(f"User selected stream index {stream_idx}: {title}", "_select_stream")
    
    return stream_idx, title, None


# =============================================================================
# LISTITEM CONFIGURATION
# =============================================================================

def _configure_listitem_stream(listitem, url, stream_headers=None):
    """
    Configure a ListItem with appropriate stream settings.
    Uses inputstream.ffmpegdirect (mandatory dependency).
    Passes headers to bypass ad/interstitial pages.
    """
    utils.log_debug(f"Configuring listitem for URL: {url}", "_configure_listitem_stream")
    
    # Build header string for URL if headers are provided
    if stream_headers:
        header_str = '|' + '&'.join(
            f'{k}={url_quote(v)}' for k, v in stream_headers.items()
        )
        full_url = url + header_str
        utils.log_debug(f"URL with headers: {full_url}", "_configure_listitem_stream")
    else:
        full_url = url
    
    listitem.setPath(full_url)
    listitem.setMimeType("application/vnd.apple.mpegurl")
    
    utils.log_debug("Using inputstream.ffmpegdirect", "_configure_listitem_stream")
    listitem.setProperty("inputstream", "inputstream.ffmpegdirect")
    listitem.setProperty("inputstream.ffmpegdirect.is_realtime_stream", "true")
    listitem.setProperty("inputstream.ffmpegdirect.stream_mode", "default")
    listitem.setProperty("inputstream.ffmpegdirect.manifest_type", "hls")
    
    openmode = utils.addon.getSetting("openmode")
    if openmode != "0":
        mode = "ffmpeg" if openmode == "1" else "curl"
        listitem.setProperty("inputstream.ffmpegdirect.open_mode", mode)
        utils.log_debug(f"FFmpeg open_mode: {mode}", "_configure_listitem_stream")
    
    # Pass headers via inputstream properties as well
    if stream_headers:
        header_value = '&'.join(f'{k}={v}' for k, v in stream_headers.items())
        listitem.setProperty("inputstream.ffmpegdirect.headers", header_value)
        utils.log_debug(f"Set ffmpegdirect headers: {header_value}", "_configure_listitem_stream")
    
    listitem.setProperty("IsPlayable", "true")


def _set_listitem_info(listitem, title, name, stream_index, stream_count):
    """Set info labels on a ListItem."""
    info_labels = {
        "title": title,
        "plot": f"[B]{name}[/B] - Stream {stream_index + 1} of {stream_count}"
    }
    
    utils.log_debug(f"Setting listitem info: {info_labels}", "_set_listitem_info")
    
    if TAGGER_AVAILABLE:
        info_tag = ListItemInfoTag(listitem, 'video')
        info_tag.set_info(info_labels)
    else:
        listitem.setInfo("Video", info_labels)


# =============================================================================
# PLAYBACK
# =============================================================================

def livePlay(name, urls=None, group=None):
    """
    Play a live channel stream.
    
    - Auto Play: tries all available streams in order, plays the first that works.
    - Specific stream: tries only the selected stream.
    - If no URLs provided but group is known (e.g. from favorites), fetches that group's channels.
    """
    utils.log_debug(f"Starting playback for: {name}", "livePlay")
    utils.log_debug(f"Provided URLs: {urls}, group: {group}", "livePlay")
    
    if urls is None:
        utils.log_debug("No URLs provided, checking cache", "livePlay")
        if _channels_cache is not None and name in _channels_cache:
            urls = _channels_cache[name]
            utils.log_debug(f"Found URLs in cache: {urls}", "livePlay")
        elif group:
            # Fetch group channels on demand (uses file cache if available)
            utils.log_debug(f"Fetching group '{group}' to find URLs for: {name}", "livePlay")
            try:
                group_channels = getchannels_by_group(group)
                urls = group_channels.get(name)
            except Exception as e:
                utils.log(f"Failed to fetch group {group}: {e}", "livePlay", force=True)
        
        if not urls:
            utils.log(f"Channel not found: {name}", "livePlay", force=True)
            utils.error_dialog("Channel Not Found", f"The channel '{name}' was not found.\nPlease refresh the channel list and try again.")
            return
    
    stream_index, title, _ = _select_stream(name, urls)
    if stream_index == -1:
        utils.log_debug("Playback cancelled by user", "livePlay")
        return
    
    auto_play = (stream_index == -2)
    total = len(urls)
    
    # Show progress dialog
    progress = xbmcgui.DialogProgress()
    progress.create('VavooTV', f'Resolving {name}...')
    progress.update(30)
    
    resolved_url = None
    resolved_headers = None
    final_index = 0
    
    if auto_play:
        # Auto Play: try each stream, skip to next on failure
        utils.log_debug(f"Auto Play: trying all {total} streams", "livePlay")
        for idx in range(total):
            if progress.iscanceled():
                utils.log_debug("User cancelled during auto play resolve", "livePlay")
                progress.close()
                return
            
            pct = 30 + int(60 * ((idx + 1) / total))
            progress.update(pct, f'Trying stream {idx + 1}/{total}...')
            
            try:
                utils.log_debug(f"Auto Play: resolving stream {idx + 1}/{total}: {urls[idx]}", "livePlay")
                resolved_url, resolved_headers = resolve_link(urls[idx], silent=True)
                if resolved_url:
                    final_index = idx
                    utils.log_debug(f"Auto Play: stream {idx + 1} resolved successfully", "livePlay")
                    break
            except Exception as e:
                utils.log(f"Auto Play: stream {idx + 1} failed: {e}", "livePlay", force=True)
                continue
    else:
        # Specific stream: try only the selected one
        utils.log_debug(f"Playing specific stream {stream_index + 1}/{total}", "livePlay")
        progress.update(50, f'Resolving {name}...')
        
        try:
            resolved_url, resolved_headers = resolve_link(urls[stream_index])
            final_index = stream_index
        except Exception as e:
            progress.close()
            utils.log(f"Failed to resolve stream {stream_index + 1}: {e}", "livePlay", force=True)
            utils.log_exception("livePlay")
            utils.error_dialog("Stream Failed", f"All streams from \n{name} \nare currently down.\nPlease refresh the channel list or try again later.")
            return
    
    progress.close()
    
    if not resolved_url:
        utils.log("No stream could be resolved", "livePlay", force=True)
        utils.error_dialog("No Stream Available", f"All streams from \n{name} \nare currently down.\nPlease refresh the channel list or try again later.")
        return
    
    utils.log_debug(f"Playing resolved URL: {resolved_url}", "livePlay")
    
    listitem = xbmcgui.ListItem(name)
    _configure_listitem_stream(listitem, resolved_url, resolved_headers)
    
    display_title = f"{name} ({final_index + 1}/{total})" if total > 1 else name
    _set_listitem_info(listitem, display_title, name, final_index, total)
    
    utils.set_resolved(listitem)
    utils.end()
    
    utils.log_debug("Playback initiated successfully", "livePlay")


# =============================================================================
# DIRECTORY LISTING
# =============================================================================

def _create_channel_listitem(name, url_count, group=None):
    """Create a ListItem for a channel in the directory listing."""
    # Always show count if > 1 (hardcoded setting)
    show_count = url_count > 1
    title = f"{name}  ({url_count})" if show_count else name
    
    utils.log_debug(f"Creating listitem: {name} ({url_count} streams)", "_create_channel_listitem")
    
    listitem = xbmcgui.ListItem(name)
    
    # Build context menu with favorites support
    cm = []
    safe_name = name.replace("&", "%26").replace("+", "%2b")
    
    if group:
        safe_group = group.replace("&", "%26").replace("+", "%2b")
        if utils.is_favorite(name):
            cm.append(("Remove TV Favorite",
                       f"RunPlugin({sys.argv[0]}?action=delTvFavorit&name={safe_name})"))
        else:
            cm.append(("Add to TV Favorites",
                       f"RunPlugin({sys.argv[0]}?action=addTvFavorit&name={safe_name}&group={safe_group})"))
    
    cm.append(("Settings", f"RunPlugin({sys.argv[0]}?action=settings)"))
    listitem.addContextMenuItems(cm)
    
    # Mark favorites visually in plot
    plot = "[COLOR darkorange]TV Favorite[/COLOR]" if utils.is_favorite(name) else ""
    
    info_labels = {"title": title, "plot": plot}
    if TAGGER_AVAILABLE:
        info_tag = ListItemInfoTag(listitem, 'video')
        info_tag.set_info(info_labels)
    else:
        listitem.setInfo("Video", info_labels)
    
    listitem.setProperty("IsPlayable", "true")
    return listitem


def channels():
    """Display all channels from all categories."""
    utils.log_debug("Displaying all channels", "channels")
    results = getchannels(use_cache=True)
    
    utils.log_debug(f"Building directory with {len(results)} channels", "channels")
    
    items = []
    for name, urls in results.items():
        name = name.strip()
        listitem = _create_channel_listitem(name, len(urls))
        items.append(({"name": name, "urls": json.dumps(urls)}, listitem, False))
    
    utils.add_items(items)
    utils.sort_method()
    utils.end()
    
    utils.log_debug("Channel directory completed", "channels")


def channels_by_group(group):
    """Display channels from a specific group/country. Red refresh entry at top."""
    utils.log_debug(f"Displaying channels for group: {group}", "channels_by_group")
    
    # --- Red Refresh entry at top ---
    refresh_label = "[COLOR red]Refresh Channel List[/COLOR]"
    refresh_li = xbmcgui.ListItem(refresh_label)
    info_labels = {"title": refresh_label, "plot": ""}
    if TAGGER_AVAILABLE:
        info_tag = ListItemInfoTag(refresh_li, 'video')
        info_tag.set_info(info_labels)
    else:
        refresh_li.setInfo("Video", info_labels)
    utils.add({"action": "refresh_channels", "group": group}, refresh_li, isFolder=True)
    
    # --- Channel entries ---
    results = getchannels_by_group(group)
    
    utils.log_debug(f"Building directory with {len(results)} channels", "channels_by_group")
    
    items = []
    for name, urls in results.items():
        name = name.strip()
        listitem = _create_channel_listitem(name, len(urls), group=group)
        items.append(({"name": name, "urls": json.dumps(urls)}, listitem, False))
    
    utils.add_items(items)
    utils.sort_method()
    utils.end()
    
    utils.log_debug("Channel directory completed", "channels_by_group")


# =============================================================================
# TV FAVORITES
# =============================================================================

def favchannels():
    """
    Display TV Favorites list.
    
    Features:
    - Lists channels in the order stored in JSON (supports manual sorting).
    - Shows Nickname if available, otherwise Real Name.
    - Context Menu for Rename and Move Up/Down.
    - Always handles empty state gracefully (shows dummy item or empty folder).
    """
    utils.log_debug("Displaying TV Favorites", "favchannels")
    
    favorites = utils.get_favorites()
    items = []
    
    # We do NOT sort alphabetically here anymore, so the user order is preserved.
    # Users can reorder via context menu (Move Up/Down).
    if favorites:
        for fav in favorites:
            if not isinstance(fav, dict):
                continue
            
            real_name = fav.get("name")
            group = fav.get("group")
            nickname = fav.get("nickname", "")
            
            if not real_name or not group:
                continue
            
            # Display name: Nickname if set, else Real Name
            display_name = nickname if nickname else real_name
            
            listitem = xbmcgui.ListItem(display_name)
            safe_name = real_name.replace("&", "%26").replace("+", "%2b")
            
            # Build Context Menu
            cm = [
                ("Remove TV Favorite",
                 f"RunPlugin({sys.argv[0]}?action=delTvFavorit&name={safe_name})"),
                ("Change Channel Name",
                 f"RunPlugin({sys.argv[0]}?action=renameTvFavorit&name={safe_name})"),
                ("Move to Top",
                 f"RunPlugin({sys.argv[0]}?action=moveTvFavoritTop&name={safe_name})"),
                ("Move Up",
                 f"RunPlugin({sys.argv[0]}?action=moveTvFavoritUp&name={safe_name})"),
                ("Move Down",
                 f"RunPlugin({sys.argv[0]}?action=moveTvFavoritDown&name={safe_name})"),
                ("Move to Bottom",
                 f"RunPlugin({sys.argv[0]}?action=moveTvFavoritBottom&name={safe_name})"),
                ("Settings", f"RunPlugin({sys.argv[0]}?action=settings)")
            ]
            listitem.addContextMenuItems(cm)
            
            # Build Plot info
            plot_info = f"[COLOR darkorange]TV Favorite[/COLOR] ({group})"
            if nickname:
                plot_info += f"\nReal Name: {real_name}"
                
            info_labels = {
                "title": display_name,
                "plot": plot_info
            }
            if TAGGER_AVAILABLE:
                info_tag = ListItemInfoTag(listitem, 'video')
                info_tag.set_info(info_labels)
            else:
                listitem.setInfo("Video", info_labels)
            
            listitem.setProperty("IsPlayable", "true")
            
            # PARAMETERS: Must use Real Name so livePlay finds the channel
            safe_group = group.replace("&", "%26").replace("+", "%2b")
            items.append(({"name": real_name, "group": safe_group}, listitem, False))
    else:
        # Show a placeholder item so the directory isn't confusingly empty
        li = xbmcgui.ListItem("[COLOR gray]No favorites added yet[/COLOR]")
        if TAGGER_AVAILABLE:
            ListItemInfoTag(li, 'video').set_info({"title": "No favorites added yet", "plot": "Use the context menu on any channel to add it here."})
        else:
            li.setInfo("Video", {"title": "No favorites added yet", "plot": "Use the context menu on any channel to add it here."})
        items.append(({"action": "noop"}, li, False))

    if items:
        utils.add_items(items)
    
    # Do NOT add sort method here, we want custom order
    utils.end()
    
    utils.log_debug(f"Displayed {len(items)} favorites", "favchannels")


def change_favorit(name, group=None, delete=False):
    """
    Add or remove a channel from TV favorites.
    """
    if delete:
        utils.remove_favorite(name)
        utils.notify(f"Removed: {name}")
        utils.log_debug(f"Removed from favorites: {name}", "change_favorit")
    else:
        if not group:
            utils.log("Cannot add favorite without group", "change_favorit", force=True)
            return
        utils.add_favorite(name, group)
        utils.notify(f"Added: {name}")
        utils.log_debug(f"Added to favorites: {name} (group={group})", "change_favorit")
    
    # Refresh the current container
    xbmc.executebuiltin("Container.Refresh")


def rename_favorit_dialog(name):
    """
    Open keyboard dialog to rename a favorite.
    """
    favorites = utils.get_favorites()
    # Find current nickname if exists
    current_nick = ""
    for fav in favorites:
        if fav.get("name") == name:
            current_nick = fav.get("nickname", "")
            break
            
    kb = xbmc.Keyboard(current_nick, f"Rename: {name}")
    kb.doModal()
    
    if kb.isConfirmed():
        new_nick = kb.getText()
        utils.rename_favorite(name, new_nick)
        utils.notify(f"Renamed to: {new_nick}" if new_nick else "Nickname removed")
        xbmc.executebuiltin("Container.Refresh")


def move_favorit_logic(name, direction):
    """
    Move favorite up or down.
    """
    utils.move_favorite(name, direction)
    xbmc.executebuiltin("Container.Refresh")


# =============================================================================
# M3U CREATION
# =============================================================================

def makem3u(group):
    """
    Generate an M3U playlist for a specific group/country or Favorites and save it.
    The M3U will contain plugin:// links that trigger playback via this addon.
    """
    
    if not group:
        utils.error_dialog("Error", "No group specified.")
        return

    # Check if this is the special "favorites" group request
    if group == "favorites":
        # 1. Load Favorites
        progress = xbmcgui.DialogProgress()
        progress.create("VavooTV", "Loading Favorites...")
        
        channels_data = utils.get_favorites()
        if not channels_data:
            progress.close()
            utils.notify("No favorites found")
            return
            
        progress.update(50, "Generating M3U data...")
        
        lines = ["#EXTM3U\n"]
        
        for fav in channels_data:
            if not isinstance(fav, dict): continue
            
            name = fav.get("name")
            grp = fav.get("group")
            nickname = fav.get("nickname", "") # Get nickname
            
            if not name or not grp: continue
            
            # Determine display name: Nickname if available, else Real Name
            display_name = nickname if nickname else name
            
            # Escape real name for URL (Must be real name for playback)
            safe_name = quote_plus(name)
            safe_group = quote_plus(grp)
            
            # Construct plugin path
            base_url = f"plugin://{utils.addonID}/"
            stream_url = f"{base_url}?name={safe_name}&group={safe_group}"
            
            # Use display_name for the label, but keep original group
            lines.append(f'#EXTINF:-1 group-title="{grp}",{display_name}\n{stream_url}\n')
            
        clean_group = "Favorites"
        
    else:
        # Existing logic for standard country groups
        progress = xbmcgui.DialogProgress()
        progress.create("VavooTV", f"Fetching channels for {group}...")
        
        # Ensure cache is populated
        try:
            channels = getchannels_by_group(group)
        except Exception as e:
            progress.close()
            utils.error_dialog("Error", f"Could not fetch channels: {e}")
            return
        
        if not channels:
            progress.close()
            utils.notify(f"No channels found for {group}")
            return

        progress.update(50, "Generating M3U data...")
        
        lines = ["#EXTM3U\n"]
        
        for name in sorted(channels.keys()):
            # Escape special chars for URL
            safe_name = quote_plus(name)
            safe_group = quote_plus(group)
            
            # Construct plugin path
            base_url = f"plugin://{utils.addonID}/"
            stream_url = f"{base_url}?name={safe_name}&group={safe_group}"
            
            lines.append(f'#EXTINF:-1 group-title="{group}",{name}\n{stream_url}\n')
            
        clean_group = re.sub(r'[\\/*?:"<>| ]', "_", group)

    progress.update(100, "Waiting for save location...")
    progress.close()

    # 3. Select Save Directory
    dialog = xbmcgui.Dialog()
    # type 0: Browse for folder (all sources including network)
    save_path = dialog.browse(0, 'Select Save Directory for M3U', 'files')
    
    if not save_path:
        return

    # 4. Save File
    # Format: VavooTV-GroupName-YYYY-MM-DD.m3u
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filename = f"VavooTV-{clean_group}-{date_str}.m3u"
    
    full_path = os.path.join(save_path, filename)
    
    try:
        f = xbmcvfs.File(full_path, 'w')
        success = f.write("".join(lines))
        f.close()
        
        if success:
            xbmcgui.Dialog().ok(
                "M3U Created Successfully",
                f"File: {filename}\nSaved to: {full_path}"
            )
            utils.log_debug(f"M3U saved to {full_path}", "makem3u")
        else:
            utils.error_dialog("Save Error", "Failed to write file.")
            
    except Exception as e:
        utils.log_exception("makem3u")
        utils.error_dialog("Save Error", f"Failed to save M3U:\n{e}")