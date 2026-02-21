# -*- coding: utf-8 -*-
import os
import random

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.api import (
    AbsApiError,
    AbsClient,
    find_first_key,
    iter_audio_urls,
    parse_entities,
    parse_items,
    parse_libraries,
)
from resources.lib.player import AbsPlayerMonitor
from resources.lib import utils


# Localization IDs (see resources/language/*/strings.po)
L = {
    "audio": 30000,
    "podcasts": 30001,
    "continue": 30002,
    "sync_strm": 30003,
    "auth_test": 30004,
    "connected_as": 30005,
    "abs_home": 30006,
    "recently_added": 30007,
    "current_series": 30008,
    "discover": 30009,
    "listen_again": 30010,
    "latest_authors": 30011,
    "all_titles": 30012,
    "all_series": 30013,
    "all_collections": 30014,
    "all_authors": 30015,
    "all_narrators": 30016,
    "entity_items_missing": 30017,
    "strm_done": 30018,
    "settings": 30019,
    "continue_series": 30020,
}


def t(key, fallback):
    return utils.tr(L[key], fallback)


def library_kind(lib):
    text = " ".join(str(lib.get(k, "")) for k in ("mediaType", "libraryType", "type", "name")).lower()
    if "podcast" in text:
        return "podcast"
    if "book" in text or "audio" in text:
        return "audiobook"
    return "unknown"


def item_title(item):
    media = item.get("media") or {}
    metadata = media.get("metadata") or {}
    return metadata.get("title") or item.get("title") or item.get("name") or item.get("id")


def item_cover(item_id):
    return "/api/items/%s/cover" % item_id


def item_metadata(item):
    media = item.get("media") or {}
    return media.get("metadata") or {}


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


def art_for_item(client, item_id):
    cover = client.stream_url_with_token(item_cover(item_id))
    return {"thumb": cover, "icon": cover, "poster": cover, "fanart": cover}


def audiobook_libraries(client):
    libs = parse_libraries(client.libraries())
    return [lib for lib in libs if library_kind(lib) == "audiobook"]


def podcast_libraries(client):
    libs = parse_libraries(client.libraries())
    return [lib for lib in libs if library_kind(lib) == "podcast"]


def root(client):
    utils.add_dir(t("audio", "Audiobooks"), "audiobooks", folder=True)
    utils.add_dir(t("podcasts", "Podcasts"), "podcasts", folder=True)
    utils.add_dir(t("continue", "Continue Listening"), "continue", folder=True)
    utils.add_dir(t("sync_strm", "Sync STRM files"), "sync_strm", folder=False)
    utils.add_dir(t("auth_test", "Login / Connection Test"), "auth_test", folder=False)
    utils.add_dir(t("settings", "Settings"), "settings", folder=False)
    utils.end("files")


def list_audiobook_libraries(client):
    libs = audiobook_libraries(client)
    if len(libs) == 1:
        audiobook_home(client, libs[0].get("id"), libs[0].get("name") or "")
        return
    for lib in libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        utils.add_dir(lib.get("name") or lib_id, "audiobooks_home", folder=True, library_id=lib_id, library_name=lib.get("name") or lib_id)
    utils.end("files")


def list_podcast_libraries(client):
    libs = podcast_libraries(client)
    if len(libs) == 1:
        list_library(client, libs[0].get("id"), kind="podcast")
        return
    for lib in libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        utils.add_dir(lib.get("name") or lib_id, "library", folder=True, library_id=lib_id, library_name=lib.get("name") or lib_id, kind="podcast")
    utils.end("files")


def audiobook_home(client, library_id, library_name=""):
    utils.add_dir(t("continue_series", "Series fortsetzen"), "audiobook_continue", folder=True, library_id=library_id)
    utils.add_dir(t("recently_added", "Kürzlich hinzugefügt"), "audiobook_recent", folder=True, library_id=library_id)
    utils.add_dir(t("current_series", "Aktuelle Serien"), "entities", folder=True, library_id=library_id, entity_type="series")
    utils.add_dir(t("discover", "Entdecken"), "audiobook_discover", folder=True, library_id=library_id)
    utils.add_dir(t("listen_again", "Erneut Anhören"), "audiobook_listen_again", folder=True, library_id=library_id)
    utils.add_dir(t("latest_authors", "Neuste Autoren"), "entities", folder=True, library_id=library_id, entity_type="authors", sort="addedAt", desc="1")
    utils.add_dir(t("all_titles", "Bibliothek: Alle Titel"), "library", folder=True, library_id=library_id, kind="audiobook")
    utils.add_dir(t("all_series", "Serien: Alle Serien"), "entities", folder=True, library_id=library_id, entity_type="series")
    utils.add_dir(t("all_collections", "Sammlungen: Alle Sammlungen"), "entities", folder=True, library_id=library_id, entity_type="collections")
    utils.add_dir(t("all_authors", "Autoren: Alle Autoren"), "entities", folder=True, library_id=library_id, entity_type="authors")
    utils.add_dir(t("all_narrators", "Erzähler: Alle Erzähler"), "entities", folder=True, library_id=library_id, entity_type="narrators")
    utils.end("files")


def list_library(client, library_id, kind="unknown"):
    items = parse_items(client.library_items(library_id))
    _render_items(client, items, kind=kind)


def list_library_sorted(client, library_id, sort_key, desc=1, kind="audiobook"):
    items = parse_items(client.library_items_sorted(library_id, sort_key=sort_key, desc=desc))
    _render_items(client, items, kind=kind)


def _render_items(client, items, kind="audiobook"):
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        title = item_title(item)
        art = art_for_item(client, item_id)
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
        cover = art if isinstance(art, str) else (art.get("thumb") or cover)
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
        info = {"title": ep_title, "album": title, "plot": ep.get("description") or "", "duration": duration}
        art_data = {"thumb": cover, "icon": cover, "poster": cover}
        utils.add_playable(label, "play", item_id=item_id, episode_id=ep_id, title=ep_title, art=art_data, info=info)
    utils.end("songs")


def list_continue(client, library_id=""):
    data = client.items_in_progress(limit=200)
    items = parse_items(data)
    for entry in items:
        library_item = entry.get("libraryItem") or entry
        media_progress = entry.get("mediaProgress") or {}
        lib_id = (library_item.get("libraryId") or library_item.get("library") or {}).get("id") if isinstance(library_item.get("library"), dict) else library_item.get("libraryId")
        if library_id and lib_id and library_id != lib_id:
            continue

        ep = entry.get("episode") or {}
        item_id = library_item.get("id")
        if not item_id:
            continue
        title = item_title(library_item)
        ep_id = ep.get("id")
        if ep_id:
            title = "%s - %s" % (title, ep.get("title") or ep_id)
        art = art_for_item(client, item_id)
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


def list_discover(client, library_id):
    items = parse_items(client.library_items(library_id))
    random.shuffle(items)
    _render_items(client, items[:80], kind="audiobook")


def list_listen_again(client, library_id):
    # Approximation for ABS "Listen Again": last listening sessions, unique items.
    data = client.listening_sessions(limit=200)
    sessions = parse_items(data)
    seen = set()
    out = []
    for s in sessions:
        library_item = s.get("libraryItem") or s.get("item") or {}
        item_id = library_item.get("id")
        if not item_id or item_id in seen:
            continue
        lib_id = library_item.get("libraryId")
        if library_id and lib_id and library_id != lib_id:
            continue
        seen.add(item_id)
        out.append(library_item)
    if not out:
        list_library_sorted(client, library_id, sort_key="updatedAt", desc=1, kind="audiobook")
        return
    _render_items(client, out, kind="audiobook")


def entity_name(entity):
    return entity.get("name") or entity.get("title") or entity.get("authorName") or entity.get("narrator") or entity.get("id")


def extract_entity_item_ids(entity):
    candidates = []
    for key in ("libraryItemIds", "bookIds", "items", "books"):
        val = entity.get(key)
        if isinstance(val, list):
            if val and isinstance(val[0], dict):
                candidates.extend([x.get("id") for x in val if isinstance(x, dict) and x.get("id")])
            else:
                candidates.extend([x for x in val if isinstance(x, str)])
    # ABS detail payloads may nest ids.
    nested = find_first_key(entity, ["libraryItemIds", "bookIds"])
    if isinstance(nested, list):
        candidates.extend([x for x in nested if isinstance(x, str)])
    return list(dict.fromkeys([x for x in candidates if x]))


def list_entities(client, library_id, entity_type, sort="name", desc=0):
    payload = client.library_entities(library_id, entity_type, sort=sort, desc=int(desc))
    entities = parse_entities(payload, entity_type=entity_type)
    for entity in entities:
        eid = entity.get("id")
        if not eid:
            continue
        name = entity_name(entity)
        num = entity.get("numBooks") or entity.get("numItems") or entity.get("totalItems") or ""
        label = "%s (%s)" % (name, num) if num else name
        utils.add_dir(label, "entity_items", folder=True, library_id=library_id, entity_type=entity_type, entity_id=eid, entity_name=name)
    utils.end("files")


def list_entity_items(client, library_id, entity_type, entity_id, entity_name=""):
    detail = client.entity_detail(entity_type, entity_id)
    ids = extract_entity_item_ids(detail)
    if not ids:
        utils.notify("Audiobookshelf", t("entity_items_missing", "No items exposed by this ABS endpoint"))
        utils.end("files")
        return

    items = []
    for iid in ids[:300]:
        try:
            items.append(client.item(iid))
        except Exception:
            continue
    _render_items(client, items, kind="audiobook")


def resolve_play_url(client, item_id, episode_id=None):
    play = client.play_item(item_id, episode_id=episode_id)
    for candidate in iter_audio_urls(play):
        return client.stream_url_with_token(candidate)

    item = client.item(item_id)
    for candidate in iter_audio_urls(item):
        return client.stream_url_with_token(candidate)

    inode = find_first_key(item, ["ino", "inode"])
    if inode:
        return client.stream_url_with_token("/api/items/%s/file/%s" % (item_id, inode))
    return ""


def play_item(client, item_id, episode_id=None, resume=0.0, duration=0.0, title=""):
    if resume <= 0:
        try:
            p = client.progress(item_id, episode_id=episode_id or None) or {}
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

    utils.notify("Audiobookshelf", t("strm_done", "STRM sync complete") + ": %d" % written)


def serve_cover(client, item_id):
    url = client.stream_url_with_token(item_cover(item_id))
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
            utils.notify("Audiobookshelf", "%s %s" % (t("connected_as", "Connected as"), user.get("username") or "unknown"))
            xbmc.executebuiltin("Container.Refresh")
            return

        if action == "settings":
            utils.ADDON.openSettings()
            return

        if action == "audiobooks":
            list_audiobook_libraries(client)
            return

        if action == "podcasts":
            list_podcast_libraries(client)
            return

        if action == "audiobooks_home":
            audiobook_home(client, p.get("library_id", ""), p.get("library_name", ""))
            return

        if action == "library":
            list_library(client, p.get("library_id", ""), p.get("kind", "unknown"))
            return

        if action == "episodes":
            list_episodes(client, p.get("item_id", ""), p.get("title", "Podcast"), p.get("art", ""))
            return

        if action == "continue":
            list_continue(client)
            return

        if action == "audiobook_continue":
            list_continue(client, library_id=p.get("library_id", ""))
            return

        if action == "audiobook_recent":
            list_library_sorted(client, p.get("library_id", ""), sort_key="addedAt", desc=1, kind="audiobook")
            return

        if action == "audiobook_discover":
            list_discover(client, p.get("library_id", ""))
            return

        if action == "audiobook_listen_again":
            list_listen_again(client, p.get("library_id", ""))
            return

        if action == "entities":
            list_entities(
                client,
                p.get("library_id", ""),
                p.get("entity_type", "series"),
                sort=p.get("sort", "name"),
                desc=int(p.get("desc", "0") or 0),
            )
            return

        if action == "entity_items":
            list_entity_items(
                client,
                p.get("library_id", ""),
                p.get("entity_type", "series"),
                p.get("entity_id", ""),
                p.get("entity_name", ""),
            )
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
