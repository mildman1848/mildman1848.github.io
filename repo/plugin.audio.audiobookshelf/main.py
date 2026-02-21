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
    "connection_test": 30021,
    "server_reachable": 30022,
    "server_unreachable": 30023,
    "endpoint": 30024,
    "search": 30025,
    "stats": 30026,
    "home_start": 30027,
    "search_local": 30028,
    "stats_local": 30029,
    "all_podcasts": 30030,
    "newly_added": 30031,
    "alpha_sort": 30032,
    "search_for_library": 30033,
    "stats_title": 30034,
    "stats_items": 30035,
    "stats_authors": 30036,
    "stats_genres": 30037,
    "stats_duration": 30038,
    "stats_tracks": 30039,
    "search_prompt": 30040,
    "menu_library": 30041,
    "menu_series": 30042,
    "menu_authors": 30043,
    "menu_narrators": 30044,
    "menu_collections": 30045,
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
    item = item.get("libraryItem") if isinstance(item, dict) and isinstance(item.get("libraryItem"), dict) else item
    media = item.get("media") or {}
    metadata = media.get("metadata") or {}
    return metadata.get("title") or item.get("title") or item.get("name") or item.get("id")


def item_cover(item_id):
    return "/api/items/%s/cover" % item_id


def item_metadata(item):
    item = item.get("libraryItem") if isinstance(item, dict) and isinstance(item.get("libraryItem"), dict) else item
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
        "comment": plot,
        "genre": genre,
        "duration": duration,
    }
    if year:
        try:
            info["year"] = int(year)
        except Exception:
            pass
    return info


def item_author_name(item):
    metadata = item_metadata(item)
    author = metadata.get("authorName") or metadata.get("author") or ""
    if not author:
        authors = metadata.get("authors") or []
        if isinstance(authors, list) and authors:
            first = authors[0]
            if isinstance(first, dict):
                author = first.get("name") or ""
            elif isinstance(first, str):
                author = first
    return (author or "").strip()


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
    utils.add_dir(t("search", "Search"), "search_root", folder=True)
    utils.add_dir(t("stats", "Stats"), "stats_root", folder=True)
    utils.add_dir(t("sync_strm", "Sync STRM files"), "sync_strm", folder=False)
    utils.add_dir(t("connection_test", "Server Connection Test"), "connection_test", folder=False)
    utils.add_dir(t("auth_test", "Login / Connection Test"), "auth_test", folder=False)
    utils.add_dir(t("settings", "Settings"), "settings", folder=False)
    utils.end("files")


def _select_library_menu(client, kind, action):
    libs = audiobook_libraries(client) if kind == "audiobook" else podcast_libraries(client)
    if len(libs) == 1:
        lib = libs[0]
        if action == "audiobooks_root":
            list_audiobooks_root(client, lib.get("id"))
        else:
            list_podcasts_root(client, lib.get("id"))
        return
    for lib in libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        utils.add_dir(lib.get("name") or lib_id, action, folder=True, library_id=lib_id, kind=kind)
    utils.end("files")


def list_audiobook_libraries(client):
    _select_library_menu(client, "audiobook", "audiobooks_root")


def list_podcast_libraries(client):
    _select_library_menu(client, "podcast", "podcasts_root")


def _personalized_sections(client, library_id):
    payload = client.library_personalized(library_id)
    return payload if isinstance(payload, list) else []


def list_audiobooks_root(client, library_id):
    utils.add_dir(t("home_start", "Home"), "personalized_sections", folder=True, library_id=library_id, kind="audiobook")
    utils.add_dir(t("continue", "Continue Listening"), "continue", folder=True, library_id=library_id)
    utils.add_dir(t("menu_library", "Library"), "library", folder=True, library_id=library_id, kind="audiobook")
    utils.add_dir(t("menu_series", "Series"), "entities", folder=True, library_id=library_id, entity_type="series")
    utils.add_dir(t("menu_authors", "Authors"), "entities", folder=True, library_id=library_id, entity_type="authors")
    utils.add_dir(t("menu_narrators", "Narrators"), "entities", folder=True, library_id=library_id, entity_type="narrators")
    utils.add_dir(t("menu_collections", "Collections"), "entities", folder=True, library_id=library_id, entity_type="collections")
    utils.add_dir(t("search_local", "Search"), "search_library_prompt", folder=False, library_id=library_id, kind="audiobook")
    utils.add_dir(t("stats_local", "Stats"), "library_stats", folder=False, library_id=library_id)
    utils.end("files")


def list_podcasts_root(client, library_id):
    utils.add_dir(t("all_podcasts", "All Podcasts"), "library", folder=True, library_id=library_id, kind="podcast")
    utils.add_dir(t("continue", "Continue Listening"), "continue", folder=True, library_id=library_id)
    utils.add_dir(t("newly_added", "Recently Added"), "library_sorted", folder=True, library_id=library_id, kind="podcast", sort_key="addedAt", desc="1")
    utils.add_dir(t("alpha_sort", "A-Z"), "library_sorted", folder=True, library_id=library_id, kind="podcast", sort_key="media.metadata.title", desc="0")
    utils.add_dir(t("search_local", "Search"), "search_library_prompt", folder=False, library_id=library_id, kind="podcast")
    utils.add_dir(t("stats_local", "Stats"), "library_stats", folder=False, library_id=library_id)
    utils.end("files")


def list_personalized_sections(client, library_id, kind="audiobook"):
    sections = _personalized_sections(client, library_id)
    for section in sections:
        if not isinstance(section, dict):
            continue
        sid = section.get("id")
        label = section.get("label") or sid
        if not sid or not label:
            continue
        total = section.get("total")
        if total is not None:
            label = "%s (%s)" % (label, total)
        utils.add_dir(label, "personalized_section", folder=True, library_id=library_id, kind=kind, section_id=sid)
    utils.end("files")


def list_personalized_section(client, library_id, section_id, kind="audiobook"):
    sections = _personalized_sections(client, library_id)
    section = None
    for row in sections:
        if isinstance(row, dict) and str(row.get("id") or "") == str(section_id or ""):
            section = row
            break
    if not isinstance(section, dict):
        utils.end("files")
        return

    entities = section.get("entities") or []
    section_type = (section.get("type") or "").lower()
    if section_type in ("book", "podcast"):
        _render_items(client, entities, kind=kind)
        return

    if section_type == "series":
        for row in entities:
            series = row.get("series") if isinstance(row, dict) and isinstance(row.get("series"), dict) else row
            if not isinstance(series, dict):
                continue
            sid = series.get("id")
            name = series.get("name") or sid
            if not sid:
                continue
            utils.add_dir(name, "entity_items", folder=True, library_id=library_id, entity_type="series", entity_id=sid, entity_name=name)
        utils.end("files")
        return

    if section_type in ("author", "authors"):
        for row in entities:
            if not isinstance(row, dict):
                continue
            aid = row.get("id")
            name = row.get("name") or aid
            if not aid:
                continue
            utils.add_dir(name, "entity_items", folder=True, library_id=library_id, entity_type="authors", entity_id=aid, entity_name=name)
        utils.end("files")
        return

    _render_items(client, entities, kind=kind)


def _prompt_text(title):
    kb = xbmc.Keyboard("", title)
    kb.doModal()
    if not kb.isConfirmed():
        return ""
    return (kb.getText() or "").strip()


def show_library_stats(client, library_id):
    stats = client.library_stats(library_id) or {}
    lines = [
        "%s: %s" % (t("stats_items", "Items"), stats.get("totalItems", "-")),
        "%s: %s" % (t("stats_authors", "Authors"), stats.get("totalAuthors", "-")),
        "%s: %s" % (t("stats_genres", "Genres"), stats.get("totalGenres", "-")),
        "%s: %s" % (t("stats_duration", "Duration"), stats.get("totalDuration", "-")),
        "%s: %s" % (t("stats_tracks", "Tracks"), stats.get("numAudioTracks", "-")),
    ]
    xbmcgui.Dialog().ok(t("stats_title", "Audiobookshelf Stats"), "\n".join(lines))


def list_search_root(client):
    libs = parse_libraries(client.libraries())
    for lib in libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        kind = library_kind(lib)
        label = t("search_for_library", "Search: %s") % (lib.get("name") or lib_id)
        utils.add_dir(label, "search_library_prompt", folder=False, library_id=lib_id, kind=kind)
    utils.end("files")


def list_search_results(client, library_id, kind, query):
    payload = client.library_search(library_id, query, limit=30) or {}
    book_rows = payload.get("book") or payload.get("books") or []
    books = []
    for row in book_rows:
        if isinstance(row, dict) and isinstance(row.get("libraryItem"), dict):
            books.append(row.get("libraryItem"))
        elif isinstance(row, dict):
            books.append(row)
    if books:
        _render_items(client, books, kind=kind)
        return

    series_rows = payload.get("series") or []
    authors_rows = payload.get("authors") or []
    for row in series_rows:
        series = row.get("series") if isinstance(row, dict) and isinstance(row.get("series"), dict) else row
        if not isinstance(series, dict):
            continue
        sid = series.get("id")
        name = series.get("name") or sid
        if sid:
            utils.add_dir(name, "entity_items", folder=True, library_id=library_id, entity_type="series", entity_id=sid, entity_name=name)
    for row in authors_rows:
        if not isinstance(row, dict):
            continue
        aid = row.get("id")
        name = row.get("name") or aid
        if aid:
            utils.add_dir(name, "entity_items", folder=True, library_id=library_id, entity_type="authors", entity_id=aid, entity_name=name)
    utils.end("files")


def list_stats_root(client):
    libs = parse_libraries(client.libraries())
    for lib in libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        utils.add_dir(lib.get("name") or lib_id, "library_stats", folder=False, library_id=lib_id)
    utils.end("files")


def audiobook_home(client, library_id, library_name=""):
    # Backward-compatible alias.
    libs = audiobook_libraries(client)
    if libs:
        list_audiobooks_root(client, library_id)


def list_library(client, library_id, kind="unknown"):
    items = fetch_library_items_all(client, library_id, max_pages=10)
    if not items:
        items = parse_items(client.library_items(library_id))
    _render_items(client, items, kind=kind)


def list_library_sorted(client, library_id, sort_key, desc=1, kind="audiobook"):
    items = parse_items(client.library_items_sorted(library_id, sort_key=sort_key, desc=desc))
    if not items:
        items = fetch_library_items_all(client, library_id, max_pages=10)
    _render_items(client, items, kind=kind)


def fetch_library_items_all(client, library_id, max_pages=12, page_size=200):
    all_items = []
    for page in range(0, max_pages):
        try:
            batch = parse_items(client.library_items(library_id, page=page, limit=page_size))
        except Exception:
            batch = []
        if not batch:
            break
        all_items.extend(batch)
        if len(batch) < page_size:
            break
    return all_items


def _iter_entity_names(metadata, entity_type):
    if entity_type == "series":
        for s in metadata.get("series") or []:
            if isinstance(s, dict):
                name = (s.get("name") or "").strip()
                sid = str(s.get("id") or "")
                if name:
                    yield name, sid
            elif isinstance(s, str):
                name = s.strip()
                if name:
                    yield name, ""
        sname = (metadata.get("seriesName") or "").strip()
        if sname:
            yield sname, ""
    elif entity_type == "authors":
        for a in metadata.get("authors") or []:
            if isinstance(a, dict):
                name = (a.get("name") or "").strip()
                aid = str(a.get("id") or "")
                if name:
                    yield name, aid
            elif isinstance(a, str):
                name = a.strip()
                if name:
                    yield name, ""
        aname = (metadata.get("authorName") or metadata.get("author") or "").strip()
        if aname:
            yield aname, ""
    elif entity_type == "narrators":
        narrators = metadata.get("narrators") or []
        if isinstance(narrators, list):
            for n in narrators:
                if isinstance(n, dict):
                    name = (n.get("name") or "").strip()
                    nid = str(n.get("id") or "")
                    if name:
                        yield name, nid
                elif isinstance(n, str):
                    name = n.strip()
                    if name:
                        yield name, ""
        nname = (metadata.get("narratorName") or "").strip()
        if nname:
            yield nname, ""
    elif entity_type == "collections":
        for c in metadata.get("collections") or []:
            if isinstance(c, dict):
                name = (c.get("name") or "").strip()
                cid = str(c.get("id") or "")
                if name:
                    yield name, cid
            elif isinstance(c, str):
                name = c.strip()
                if name:
                    yield name, ""


def build_local_entities(items, entity_type):
    by_name = {}
    for it in items:
        it = it.get("libraryItem") if isinstance(it, dict) and isinstance(it.get("libraryItem"), dict) else it
        metadata = item_metadata(it)
        for name, eid in _iter_entity_names(metadata, entity_type):
            key = name.lower()
            row = by_name.get(key)
            if not row:
                row = {"name": name, "id": eid, "count": 0}
                by_name[key] = row
            row["count"] += 1
            if not row["id"] and eid:
                row["id"] = eid
    return sorted(by_name.values(), key=lambda x: x["name"].lower())


def _render_items(client, items, kind="audiobook"):
    for item in items:
        item = item.get("libraryItem") if isinstance(item, dict) and isinstance(item.get("libraryItem"), dict) else item
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
        info = {"title": ep_title, "album": title, "comment": ep.get("description") or "", "duration": duration}
        art_data = {"thumb": cover, "icon": cover, "poster": cover}
        utils.add_playable(label, "play", item_id=item_id, episode_id=ep_id, title=ep_title, art=art_data, info=info)
    utils.end("songs")


def list_continue(client, library_id=""):
    threshold = utils.as_seconds(utils.ADDON.getSetting("mark_finished_threshold") or 97)
    if threshold <= 0 or threshold > 100:
        threshold = 97

    seen = set()
    utils.debug("Loading continue list (library_id=%s)" % (library_id or "all"))

    def resolve_library_id(entry_obj, item_obj):
        lib = ""
        raw_library_id = item_obj.get("libraryId") if isinstance(item_obj, dict) else ""
        if isinstance(raw_library_id, dict):
            lib = str(raw_library_id.get("id") or "")
        elif raw_library_id:
            lib = str(raw_library_id)
        if not lib and isinstance(item_obj, dict) and isinstance(item_obj.get("library"), dict):
            lib = str((item_obj.get("library") or {}).get("id") or "")
        if not lib and isinstance(entry_obj, dict):
            entry_library_id = entry_obj.get("libraryId")
            if isinstance(entry_library_id, dict):
                lib = str(entry_library_id.get("id") or "")
            elif entry_library_id:
                lib = str(entry_library_id)
            if not lib and isinstance(entry_obj.get("library"), dict):
                lib = str((entry_obj.get("library") or {}).get("id") or "")
        return lib

    def add_continue_item(library_item, media_progress=None, episode=None):
        library_item = library_item or {}
        media_progress = media_progress or {}
        episode = episode or {}

        item_id = str(library_item.get("id") or "")
        if not item_id:
            return
        ep_id = str(episode.get("id") or "")
        key = (item_id, ep_id)
        if key in seen:
            return

        current_time = float(media_progress.get("currentTime", 0) or 0)
        duration = float(media_progress.get("duration", 0) or 0)
        if duration > 0:
            percent = (current_time / duration) * 100.0
            if percent >= threshold:
                return

        title = item_title(library_item)
        if ep_id:
            title = "%s - %s" % (title, episode.get("title") or ep_id)
        art = art_for_item(client, item_id)
        info = item_info_labels(library_item, fallback_title=title)
        try:
            info["duration"] = int(float(duration or 0))
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
            resume=current_time,
            duration=duration,
        )
        seen.add(key)

    data = client.items_in_progress(limit=200)
    items = parse_items(data)
    for entry in items:
        library_item = entry.get("libraryItem") or entry or {}
        media_progress = entry.get("mediaProgress") or entry.get("userMediaProgress") or {}

        ep = entry.get("episode") or {}
        item_id = (
            (library_item.get("id") if isinstance(library_item, dict) else "")
            or str(entry.get("itemId") or "")
            or str(entry.get("libraryItemId") or "")
            or str(media_progress.get("itemId") or "")
            or str(media_progress.get("libraryItemId") or "")
        )
        if not item_id:
            continue

        # Some ABS variants return only IDs in items-in-progress. Fetch full item lazily.
        if not isinstance(library_item, dict) or not library_item:
            try:
                library_item = client.item(item_id) or {}
            except Exception:
                library_item = {"id": item_id}

        lib_id = resolve_library_id(entry, library_item)
        if library_id:
            # strict filter: when filtering for a concrete library, unknown ids are excluded
            if not lib_id or library_id != lib_id:
                continue
        add_continue_item(library_item, media_progress=media_progress, episode=ep)

    # Fallback/merge for ABS variants where items-in-progress misses audiobook entries.
    for page in range(0, 8):
        try:
            payload = client.listening_sessions(limit=50, page=page)
        except Exception:
            break
        sessions = []
        if isinstance(payload, dict):
            sessions = payload.get("sessions") or payload.get("results") or payload.get("items") or []
        elif isinstance(payload, list):
            sessions = payload
        if not sessions:
            break

        for s in sessions:
            if not isinstance(s, dict):
                continue

            item_id = str(s.get("libraryItemId") or "")
            if not item_id:
                continue
            episode = {}
            if s.get("episodeId"):
                episode = {"id": str(s.get("episodeId") or ""), "title": ""}
            media_progress = {
                "currentTime": float(s.get("currentTime", 0) or 0),
                "duration": float(s.get("duration", 0) or 0),
            }

            try:
                library_item = client.item(item_id) or {"id": item_id}
            except Exception:
                library_item = {"id": item_id}

            sid_lib = str(s.get("libraryId") or "") or resolve_library_id(s, library_item)
            if library_id:
                if not sid_lib or sid_lib != library_id:
                    continue

            add_continue_item(library_item, media_progress=media_progress, episode=episode)

        if len(sessions) < 50:
            break

    utils.end("songs")
    utils.debug("Continue list built with %d entries" % len(seen))


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


def entity_display_name(entity):
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
    utils.debug("Loading entities type=%s library_id=%s" % (entity_type, library_id))
    entities = []
    try:
        payload = client.library_entities(library_id, entity_type, sort=sort, desc=int(desc))
        entities = parse_entities(payload, entity_type=entity_type)
    except Exception:
        entities = []

    if entities:
        for entity in entities:
            name = entity_display_name(entity) or ""
            if not name:
                continue
            num = entity.get("numBooks") or entity.get("numItems") or entity.get("totalItems") or entity.get("count") or ""
            eid = str(entity.get("id") or "")
            label = "%s (%s)" % (name, num) if num else name
            utils.add_dir(
                label,
                "entity_items",
                folder=True,
                library_id=library_id,
                entity_type=entity_type,
                entity_id=eid,
                entity_name=name,
            )
        utils.end("files")
        return

    items = fetch_library_items_all(client, library_id, max_pages=20)
    entities = build_local_entities(items, entity_type)
    for entity in entities:
        name = entity.get("name") or ""
        if not name:
            continue
        num = entity.get("count") or ""
        eid = entity.get("id") or ""
        label = "%s (%s)" % (name, num) if num else name
        utils.add_dir(
            label,
            "entity_items",
            folder=True,
            library_id=library_id,
            entity_type=entity_type,
            entity_id=eid,
            entity_name=name,
        )
    utils.end("files")


def list_entity_items(client, library_id, entity_type, entity_id, entity_name=""):
    utils.debug(
        "Loading entity items type=%s entity_id=%s entity_name=%s"
        % (entity_type, entity_id, entity_name or "")
    )
    items = []
    detail = client.entity_detail(entity_type, entity_id, library_id=library_id)
    ids = extract_entity_item_ids(detail)

    # Some ABS servers only expose item refs in the entity list payload (e.g. series[].books),
    # not in /series/{id} detail payload.
    if not ids:
        target_id = (entity_id or "").strip()
        target_name = (entity_name or "").strip().lower()
        for page in range(0, 20):
            try:
                payload = client.library_entities(library_id, entity_type, page=page, limit=200, sort="name", desc=0)
            except Exception:
                break
            entities = parse_entities(payload, entity_type=entity_type)
            if not entities:
                break
            matched = None
            for ent in entities:
                eid = str(ent.get("id") or "")
                ename = str(entity_display_name(ent) or "").strip().lower()
                if target_id and eid and eid == target_id:
                    matched = ent
                    break
                if target_name and ename and ename == target_name:
                    matched = ent
                    break
            if matched:
                ids = extract_entity_item_ids(matched)
                if ids:
                    break
            if len(entities) < 200:
                break

    if ids:
        for iid in ids[:300]:
            try:
                items.append(client.item(iid))
            except Exception:
                continue
        if items:
            _render_items(client, items, kind="audiobook")
            return

    all_items = fetch_library_items_all(client, library_id, max_pages=20)
    target_name = (entity_name or "").strip().lower()
    target_id = (entity_id or "").strip()

    for it in all_items:
        it = it.get("libraryItem") if isinstance(it, dict) and isinstance(it.get("libraryItem"), dict) else it
        metadata = item_metadata(it)
        matched = False
        for name, eid in _iter_entity_names(metadata, entity_type):
            if target_id and eid and eid == target_id:
                matched = True
                break
            if target_name and name.strip().lower() == target_name:
                matched = True
                break
        if matched:
            items.append(it)

    if not items:
        utils.notify("Audiobookshelf", t("entity_items_missing", "No items exposed by this ABS endpoint"))
        utils.end("files")
        return
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

    # Bring music player UI to foreground automatically.
    for cmd in ("ActivateWindow(visualisation)", "ActivateWindow(MusicVisualisation)", "ActivateWindow(fullscreenmusic)"):
        try:
            xbmc.executebuiltin(cmd)
        except Exception:
            pass

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
    expected_files = set()
    written = 0
    removed = 0

    selected = []
    for lib in libs:
        kind = library_kind(lib)
        lib_id = lib.get("id")
        if not lib_id:
            continue
        if kind == "podcast" and not include_podcasts:
            continue
        if kind == "audiobook" and not include_audiobooks:
            continue
        selected.append((lib, kind))

    total_items = 0
    cache_items = {}
    for lib, kind in selected:
        lib_id = lib.get("id")
        lib_items = parse_items(client.library_items(lib_id))
        cache_items[lib_id] = lib_items
        total_items += len(lib_items)
    total_items = max(1, total_items)
    processed_items = 0

    progress = xbmcgui.DialogProgressBG()
    progress.create("Audiobookshelf", "STRM sync running...")
    try:
        for lib, kind in selected:
            lib_id = lib.get("id")
            sub = "Podcasts" if kind == "podcast" else "Audiobooks"
            out_dir = os.path.join(path, sub)
            utils.ensure_dir(out_dir)

            items = cache_items.get(lib_id) or []
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
                        expected_files.add(os.path.normpath(fpath))
                        written += 1
                else:
                    author_dir = item_author_name(item) or "Unknown Author"
                    author_dir = os.path.join(out_dir, utils.safe_filename(author_dir))
                    utils.ensure_dir(author_dir)
                    content = utils.plugin_url(action="play", item_id=item_id, title=title)
                    fpath = os.path.join(author_dir, "%s.strm" % utils.safe_filename(title))
                    utils.write_text(fpath, content)
                    expected_files.add(os.path.normpath(fpath))
                    written += 1

                processed_items += 1
                pct = int((processed_items * 100.0) / total_items)
                progress.update(max(1, min(100, pct)), "STRM sync running...", title[:80])
    finally:
        progress.close()

    # Remove stale .strm files from previous syncs.
    for root, dirs, files in os.walk(path, topdown=False):
        for fname in files:
            if not fname.lower().endswith(".strm"):
                continue
            fpath = os.path.normpath(os.path.join(root, fname))
            if fpath not in expected_files:
                try:
                    os.remove(fpath)
                    removed += 1
                    utils.debug("Removed stale STRM file: %s" % fpath)
                except Exception as exc:
                    utils.debug("Failed to remove stale STRM file %s: %s" % (fpath, exc))
        # Remove empty directories after cleanup.
        try:
            if root != os.path.normpath(path) and not os.listdir(root):
                os.rmdir(root)
        except Exception:
            pass

    utils.notify("Audiobookshelf", t("strm_done", "STRM sync complete") + ": %d (+%d removed)" % (written, removed))
    utils.debug("STRM sync complete: written=%d removed=%d" % (written, removed))


def maybe_auto_sync_strm(client, action):
    if utils.ADDON.getSetting("strm_auto_sync") != "true":
        return
    # Run only at plugin root to avoid frequent sync in submenus.
    if action:
        return
    path = (utils.ADDON.getSetting("strm_export_path") or "").strip()
    if not path:
        utils.debug("Auto STRM sync skipped: export path not set")
        return
    try:
        interval_h = float(utils.ADDON.getSetting("strm_auto_sync_interval_hours") or 24)
    except Exception:
        interval_h = 24.0
    if interval_h <= 0:
        interval_h = 24.0

    try:
        last_ts = float(utils.ADDON.getSetting("strm_last_auto_sync_ts") or 0)
    except Exception:
        last_ts = 0.0
    import time
    now = time.time()
    if last_ts > 0 and (now - last_ts) < (interval_h * 3600.0):
        utils.debug("Auto STRM sync skipped: interval not reached")
        return
    utils.debug("Starting auto STRM sync")
    sync_strm(client)
    utils.ADDON.setSetting("strm_last_auto_sync_ts", str(now))


def serve_cover(client, item_id):
    url = client.stream_url_with_token(item_cover(item_id))
    li = xbmcgui.ListItem(path=url)
    xbmcplugin.setResolvedUrl(utils.HANDLE, True, li)


def run():
    p = utils.params()
    action = p.get("action")
    utils.debug("Router action=%s params=%s" % (action or "root", p))

    try:
        client = None

        def require_client():
            nonlocal client
            if client is None:
                client = AbsClient()
            return client

        if action == "settings":
            utils.ADDON.openSettings()
            return

        if action == "connection_test":
            c = require_client()
            ok, status, path = c.ping_server()
            if ok:
                utils.notify(
                    "Audiobookshelf",
                    "%s (HTTP %s, %s %s)" % (
                        t("server_reachable", "Server reachable"),
                        status,
                        t("endpoint", "Endpoint"),
                        path,
                    ),
                )
            else:
                utils.error(t("server_unreachable", "Server not reachable"))
            return

        if not action:
            maybe_auto_sync_strm(require_client(), action)
            root(client)
            return

        if action == "cover":
            serve_cover(require_client(), p.get("item_id", ""))
            return

        if action == "auth_test":
            c = require_client()
            ok, status, path = c.ping_server()
            if not ok:
                raise AbsApiError(t("server_unreachable", "Server not reachable"))
            data = c.authorize()
            user = (data or {}).get("user") or {}
            utils.notify("Audiobookshelf", "%s %s" % (t("connected_as", "Connected as"), user.get("username") or "unknown"))
            xbmc.executebuiltin("Container.Refresh")
            return

        if action == "audiobooks":
            list_audiobook_libraries(require_client())
            return

        if action == "podcasts":
            list_podcast_libraries(require_client())
            return

        if action == "audiobooks_root":
            list_audiobooks_root(require_client(), p.get("library_id", ""))
            return

        if action == "podcasts_root":
            list_podcasts_root(require_client(), p.get("library_id", ""))
            return

        if action == "personalized_sections":
            list_personalized_sections(require_client(), p.get("library_id", ""), p.get("kind", "audiobook"))
            return

        if action == "personalized_section":
            list_personalized_section(
                require_client(),
                p.get("library_id", ""),
                p.get("section_id", ""),
                p.get("kind", "audiobook"),
            )
            return

        if action == "search_root":
            list_search_root(require_client())
            return

        if action == "search_library_prompt":
            query = _prompt_text(t("search_prompt", "Audiobookshelf Search"))
            if not query:
                xbmc.executebuiltin("Container.Refresh")
                return
            list_search_results(require_client(), p.get("library_id", ""), p.get("kind", "audiobook"), query)
            return

        if action == "stats_root":
            list_stats_root(require_client())
            return

        if action == "library_stats":
            show_library_stats(require_client(), p.get("library_id", ""))
            return

        if action == "audiobooks_home":
            audiobook_home(require_client(), p.get("library_id", ""), p.get("library_name", ""))
            return

        if action == "library":
            list_library(require_client(), p.get("library_id", ""), p.get("kind", "unknown"))
            return

        if action == "library_sorted":
            list_library_sorted(
                require_client(),
                p.get("library_id", ""),
                sort_key=p.get("sort_key", "addedAt"),
                desc=int(p.get("desc", "1") or 1),
                kind=p.get("kind", "audiobook"),
            )
            return

        if action == "episodes":
            list_episodes(require_client(), p.get("item_id", ""), p.get("title", "Podcast"), p.get("art", ""))
            return

        if action == "continue":
            list_continue(require_client())
            return

        if action == "audiobook_continue":
            list_continue(require_client(), library_id=p.get("library_id", ""))
            return

        if action == "audiobook_recent":
            list_library_sorted(require_client(), p.get("library_id", ""), sort_key="addedAt", desc=1, kind="audiobook")
            return

        if action == "audiobook_discover":
            list_discover(require_client(), p.get("library_id", ""))
            return

        if action == "audiobook_listen_again":
            list_listen_again(require_client(), p.get("library_id", ""))
            return

        if action == "entities":
            list_entities(
                require_client(),
                p.get("library_id", ""),
                p.get("entity_type", "series"),
                sort=p.get("sort", "name"),
                desc=int(p.get("desc", "0") or 0),
            )
            return

        if action == "entity_items":
            list_entity_items(
                require_client(),
                p.get("library_id", ""),
                p.get("entity_type", "series"),
                p.get("entity_id", ""),
                p.get("entity_name", ""),
            )
            return

        if action == "play":
            play_item(
                require_client(),
                item_id=p.get("item_id", ""),
                episode_id=p.get("episode_id") or None,
                resume=utils.as_seconds(p.get("resume", 0)),
                duration=utils.as_seconds(p.get("duration", 0)),
                title=p.get("title", ""),
            )
            return

        if action == "sync_strm":
            sync_strm(require_client())
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
