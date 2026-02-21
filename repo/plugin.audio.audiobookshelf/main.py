# -*- coding: utf-8 -*-
import os

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.api import AbsApiError, AbsClient, find_first_key, iter_audio_urls, parse_items, parse_libraries
from resources.lib.player import AbsPlayerMonitor
from resources.lib import utils


def library_kind(lib):
    text = " ".join(
        str(lib.get(k, ""))
        for k in ("mediaType", "libraryType", "type", "name")
    ).lower()
    if "podcast" in text:
        return "podcast"
    if "book" in text or "audio" in text:
        return "audiobook"
    return "unknown"


def item_title(item):
    media = item.get("media") or {}
    metadata = media.get("metadata") or {}
    return metadata.get("title") or item.get("title") or item.get("name") or item.get("id")


def item_author(item):
    media = item.get("media") or {}
    metadata = media.get("metadata") or {}
    author = metadata.get("authorName") or metadata.get("author") or ""
    return author


def item_cover(item_id):
    return "/api/items/%s/cover" % item_id


def item_metadata(item):
    media = item.get("media") or {}
    metadata = media.get("metadata") or {}
    return metadata


def item_info_labels(item, fallback_title=""):
    metadata = item_metadata(item)
    title = metadata.get("title") or fallback_title or item_title(item)
    artist = metadata.get("authorName") or metadata.get("author") or ""
    plot = metadata.get("description") or metadata.get("subtitle") or ""
    genre = metadata.get("genre") or metadata.get("genres") or []
    if isinstance(genre, str):
        genre = [genre]
    year = metadata.get("publishedYear") or metadata.get("year")
    duration = (item.get("media") or {}).get("duration") or 0
    try:
        duration = int(float(duration or 0))
    except Exception:
        duration = 0
    info = {
        "title": title,
        "artist": artist,
        "album": metadata.get("seriesName") or metadata.get("podcastName") or "",
        "plot": plot,
        "genre": genre,
        "duration": duration,
    }
    if year:
        try:
            info["year"] = int(year)
        except Exception:
            pass
    return info


def root(client):
    utils.add_dir("Continue Listening", "continue", folder=True)
    libs = parse_libraries(client.libraries())
    for lib in libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        kind = library_kind(lib)
        label = lib.get("name") or lib_id
        if kind == "audiobook":
            label = "[Audiobooks] %s" % label
        elif kind == "podcast":
            label = "[Podcasts] %s" % label
        utils.add_dir(label, "library", folder=True, library_id=lib_id, library_name=label, kind=kind)
    utils.add_dir("Sync STRM files", "sync_strm", folder=False)
    utils.add_dir("Login / Connection Test", "auth_test", folder=False)
    utils.end("files")


def list_library(client, library_id, kind="unknown"):
    items = parse_items(client.library_items(library_id))
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        title = item_title(item)
        cover = client.stream_url_with_token(item_cover(item_id))
        art = {"thumb": cover, "icon": cover, "poster": cover}
        info = item_info_labels(item, fallback_title=title)

        if kind == "podcast":
            utils.add_dir(title, "episodes", folder=True, item_id=item_id, title=title, art=art, info=info)
        else:
            utils.add_playable(title, "play", item_id=item_id, title=title, art=art, info=info)
    utils.end("songs")


def list_episodes(client, item_id, title="Podcast", art=""):
    item = client.item(item_id)
    media = item.get("media") or {}
    episodes = media.get("episodes") or []
    cover = client.stream_url_with_token(item_cover(item_id))
    if art:
        cover = art
    for ep in episodes:
        ep_id = ep.get("id")
        ep_title = ep.get("title") or ep.get("name") or ep_id
        if not ep_id:
            continue
        label = "%s - %s" % (title, ep_title)
        duration = ep.get("duration") or 0
        try:
            duration = int(float(duration or 0))
        except Exception:
            duration = 0
        info = {
            "title": ep_title,
            "album": title,
            "plot": ep.get("description") or "",
            "duration": duration,
        }
        art_data = {"thumb": cover, "icon": cover, "poster": cover}
        utils.add_playable(label, "play", item_id=item_id, episode_id=ep_id, title=ep_title, art=art_data, info=info)
    utils.end("songs")


def list_continue(client):
    data = client.items_in_progress(limit=200)
    items = parse_items(data)
    for entry in items:
        library_item = entry.get("libraryItem") or entry
        media_progress = entry.get("mediaProgress") or {}
        ep = entry.get("episode") or {}
        item_id = library_item.get("id")
        if not item_id:
            continue
        title = item_title(library_item)
        ep_id = ep.get("id")
        if ep_id:
            title = "%s - %s" % (title, ep.get("title") or ep_id)
        cover = client.stream_url_with_token(item_cover(item_id))
        art = {"thumb": cover, "icon": cover, "poster": cover}
        info = item_info_labels(library_item, fallback_title=title)
        try:
            info["duration"] = int(float(media_progress.get("duration", 0) or 0))
        except Exception:
            pass
        utils.add_playable(
            title,
            "play",
            item_id=item_id,
            episode_id=ep_id or "",
            title=title,
            art=art,
            info=info,
            resume=float(media_progress.get("currentTime", 0) or 0),
            duration=float(media_progress.get("duration", 0) or 0),
        )
    utils.end("songs")


def resolve_play_url(client, item_id, episode_id=None):
    play = client.play_item(item_id, episode_id=episode_id)
    # First use explicit stream URLs from play payload.
    for candidate in iter_audio_urls(play):
        return client.stream_url_with_token(candidate)

    # Fallback: look for audio files/tracks in item payload.
    item = client.item(item_id)
    for candidate in iter_audio_urls(item):
        return client.stream_url_with_token(candidate)

    # Last-resort fallback to item file endpoint.
    inode = find_first_key(item, ["ino", "inode"])
    if inode:
        return client.stream_url_with_token("/api/items/%s/file/%s" % (item_id, inode))
    return ""


def play_item(client, item_id, episode_id=None, resume=0.0, duration=0.0, title=""):
    if resume <= 0:
        try:
            p = client.progress(item_id, episode_id=episode_id or None) or {}
            # ABS may return progress directly or nested as mediaProgress.
            source = p.get("mediaProgress") if isinstance(p, dict) and p.get("mediaProgress") else p
            resume = float((source or {}).get("currentTime", 0) or 0)
            if not duration:
                duration = float((source or {}).get("duration", 0) or 0)
        except Exception:
            resume = 0.0

    stream_url = resolve_play_url(client, item_id, episode_id=episode_id or None)
    if not stream_url:
        raise AbsApiError("No stream URL found for selected item")

    li = xbmcgui.ListItem(path=stream_url)
    li.setProperty("IsPlayable", "true")
    if resume > 0:
        li.setProperty("ResumeTime", str(resume))
        if duration > 0:
            li.setProperty("TotalTime", str(duration))
    if title:
        li.setInfo("music", {"title": title})

    xbmcplugin.setResolvedUrl(utils.HANDLE, True, li)

    monitor = AbsPlayerMonitor(client, item_id=item_id, episode_id=(episode_id or None), resume_time=resume)
    monitor.run()


def sync_strm(client):
    path = (utils.ADDON.getSetting("strm_export_path") or "").strip()
    if not path:
        path = utils.pick_folder("")
        if not path:
            return
        utils.ADDON.setSetting("strm_export_path", path)

    if not utils.ensure_dir(path):
        raise AbsApiError("Could not create/export to folder: %s" % path)

    include_podcasts = utils.ADDON.getSetting("strm_include_podcasts") == "true"
    include_audiobooks = utils.ADDON.getSetting("strm_include_audiobooks") == "true"

    libs = parse_libraries(client.libraries())
    written = 0

    for lib in libs:
        kind = library_kind(lib)
        lib_id = lib.get("id")
        if not lib_id:
            continue
        if kind == "podcast" and not include_podcasts:
            continue
        if kind == "audiobook" and not include_audiobooks:
            continue

        sub = "Podcasts" if kind == "podcast" else "Audiobooks"
        out_dir = os.path.join(path, sub)
        utils.ensure_dir(out_dir)

        items = parse_items(client.library_items(lib_id))
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            title = item_title(item)

            if kind == "podcast":
                detail = client.item(item_id)
                episodes = (detail.get("media") or {}).get("episodes") or []
                pod_dir = os.path.join(out_dir, utils.safe_filename(title))
                utils.ensure_dir(pod_dir)
                for ep in episodes:
                    ep_id = ep.get("id")
                    ep_title = ep.get("title") or ep_id
                    if not ep_id:
                        continue
                    content = utils.plugin_url(action="play", item_id=item_id, episode_id=ep_id, title=ep_title)
                    fpath = os.path.join(pod_dir, "%s.strm" % utils.safe_filename(ep_title))
                    utils.write_text(fpath, content)
                    written += 1
            else:
                content = utils.plugin_url(action="play", item_id=item_id, title=title)
                fpath = os.path.join(out_dir, "%s.strm" % utils.safe_filename(title))
                utils.write_text(fpath, content)
                written += 1

    utils.notify("Audiobookshelf", "STRM sync complete: %d files" % written)


def serve_cover(client, item_id):
    url = client.stream_url_with_token("/api/items/%s/cover" % item_id)
    li = xbmcgui.ListItem(path=url)
    xbmcplugin.setResolvedUrl(utils.HANDLE, True, li)


def run():
    p = utils.params()
    action = p.get("action")

    try:
        client = AbsClient()

        if action == "cover":
            serve_cover(client, p.get("item_id", ""))
            return

        if action == "auth_test":
            data = client.authorize()
            user = (data or {}).get("user") or {}
            utils.notify("Audiobookshelf", "Connected as %s" % (user.get("username") or "unknown"))
            xbmc.executebuiltin("Container.Refresh")
            return

        if action == "library":
            list_library(client, p.get("library_id", ""), p.get("kind", "unknown"))
            return

        if action == "episodes":
            list_episodes(client, p.get("item_id", ""), p.get("title", "Podcast"), p.get("art", ""))
            return

        if action == "play":
            play_item(
                client,
                item_id=p.get("item_id", ""),
                episode_id=p.get("episode_id") or None,
                resume=utils.as_seconds(p.get("resume", 0)),
                duration=utils.as_seconds(p.get("duration", 0)),
                title=p.get("title", ""),
            )
            return

        if action == "continue":
            list_continue(client)
            return

        if action == "sync_strm":
            sync_strm(client)
            xbmc.executebuiltin("Container.Refresh")
            return

        root(client)

    except AbsApiError as exc:
        utils.error(str(exc))
    except Exception as exc:
        utils.log("Unhandled exception: %s" % exc, xbmc.LOGERROR)
        utils.error("Unhandled error: %s" % exc)


if __name__ == "__main__":
    run()
