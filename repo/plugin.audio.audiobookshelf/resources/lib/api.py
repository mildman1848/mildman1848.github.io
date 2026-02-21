# -*- coding: utf-8 -*-
import json
from urllib.parse import urljoin

import requests
import xbmcaddon


class AbsApiError(Exception):
    pass


class AbsClient:
    def __init__(self):
        self.addon = xbmcaddon.Addon()
        self.base_url = (self.addon.getSetting("base_url") or "").strip().rstrip("/")
        if not self.base_url:
            raise AbsApiError("Audiobookshelf URL is empty")

        self.auth_mode = self._parse_auth_mode(self.addon.getSetting("auth_mode"))
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    @staticmethod
    def _parse_auth_mode(raw):
        """
        Kodi select settings may return either index ("0"/"1") or label text.
        """
        value = (raw or "").strip()
        if not value:
            return 0
        if value.isdigit():
            return int(value)
        low = value.lower()
        if "user" in low or "pass" in low:
            return 1
        if "api" in low or "key" in low or "token" in low:
            return 0
        return 0

    def _full(self, path):
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _token(self):
        if self.auth_mode == 0:
            return (self.addon.getSetting("api_key") or "").strip()
        cached = (self.addon.getSetting("token") or "").strip()
        if cached:
            return cached
        return self.login()

    def auth_headers(self):
        token = self._token()
        if not token:
            raise AbsApiError("Missing API token")
        return {"Authorization": "Bearer %s" % token}

    def login(self):
        username = (self.addon.getSetting("username") or "").strip()
        password = (self.addon.getSetting("password") or "").strip()
        if not username or not password:
            raise AbsApiError("Username/password not set")

        r = self.session.post(self._full("/login"), data=json.dumps({"username": username, "password": password}), timeout=20)
        if r.status_code >= 400:
            raise AbsApiError("Login failed: HTTP %s" % r.status_code)
        data = r.json()
        token = (((data or {}).get("user") or {}).get("token") or "").strip()
        if not token:
            raise AbsApiError("Login succeeded but no token returned")
        self.addon.setSetting("token", token)
        return token

    def authorize(self):
        r = self.session.post(self._full("/api/authorize"), headers=self.auth_headers(), timeout=20)
        if r.status_code >= 400:
            raise AbsApiError("Authorize failed: HTTP %s" % r.status_code)
        return r.json()

    def get(self, path, params=None):
        return self._request_json("GET", path, params=params)

    def post(self, path, payload=None):
        return self._request_json("POST", path, payload=payload)

    def patch(self, path, payload=None):
        return self._request_json("PATCH", path, payload=payload)

    def _request_json(self, method, path, params=None, payload=None):
        attempts = 2 if self.auth_mode == 1 else 1
        last_status = None
        for attempt in range(attempts):
            headers = self.auth_headers()
            url = self._full(path)
            if method == "GET":
                r = self.session.get(url, headers=headers, params=params or {}, timeout=30)
            elif method == "POST":
                r = self.session.post(url, headers=headers, data=json.dumps(payload or {}), timeout=30)
            elif method == "PATCH":
                r = self.session.patch(url, headers=headers, data=json.dumps(payload or {}), timeout=30)
            else:
                raise AbsApiError("Unsupported HTTP method: %s" % method)

            last_status = r.status_code
            if r.status_code < 400:
                if not r.text:
                    return {}
                try:
                    return r.json()
                except Exception:
                    return {}

            # Token retry for user/pass mode.
            if r.status_code in (401, 403) and self.auth_mode == 1 and attempt == 0:
                self.addon.setSetting("token", "")
                continue

            break

        raise AbsApiError("%s %s failed: HTTP %s" % (method, path, last_status))

    def libraries(self):
        return self.get("/api/libraries")

    def library_items(self, library_id, page=0, limit=200):
        return self.get(
            "/api/libraries/%s/items" % library_id,
            params={"minified": 1, "sort": "media.metadata.title", "desc": 0, "limit": limit, "page": page, "collapseseries": 0},
        )

    def library_items_sorted(self, library_id, sort_key, desc=1, page=0, limit=200):
        return self.get(
            "/api/libraries/%s/items" % library_id,
            params={
                "minified": 1,
                "sort": sort_key,
                "desc": int(bool(desc)),
                "limit": limit,
                "page": page,
                "collapseseries": 0,
            },
        )

    def library_entities(self, library_id, entity_type, page=0, limit=200, sort="name", desc=0):
        return self.get(
            "/api/libraries/%s/%s" % (library_id, entity_type),
            params={"minified": 1, "sort": sort, "desc": int(bool(desc)), "limit": limit, "page": page},
        )

    def item(self, item_id):
        return self.get("/api/items/%s" % item_id)

    def items_in_progress(self, limit=200):
        return self.get("/api/me/items-in-progress", params={"limit": limit})

    def progress(self, item_id, episode_id=None):
        path = "/api/me/progress/%s" % item_id
        if episode_id:
            path = "/api/me/progress/%s/%s" % (item_id, episode_id)
        return self.get(path)

    def listening_sessions(self, limit=200):
        return self.get("/api/me/listening-sessions", params={"limit": limit})

    def entity_detail(self, entity_type, entity_id, library_id=None):
        # Different ABS versions expose entities differently; try common routes.
        paths = []
        if library_id:
            paths.extend(
                [
                    "/api/libraries/%s/%s/%s" % (library_id, entity_type, entity_id),
                    "/api/libraries/%s/%s/%s" % (library_id, entity_type.rstrip("s"), entity_id),
                ]
            )
        paths.extend([
            "/api/%s/%s" % (entity_type, entity_id),
            "/api/%s/%s" % (entity_type.rstrip("s"), entity_id),
        ])
        for path in paths:
            try:
                return self.get(path)
            except Exception:
                continue
        return {}

    def play_item(self, item_id, episode_id=None):
        path = "/api/items/%s/play" % item_id
        if episode_id:
            path = "/api/items/%s/play/%s" % (item_id, episode_id)
        payload = {"deviceInfo": {"clientName": "Kodi", "clientVersion": "1.0", "manufacturer": "Kodi", "model": "Kodi", "sdkVersion": "1.0"}}
        return self.post(path, payload=payload)

    def patch_progress(self, item_id, current_time, duration, is_finished=False, episode_id=None):
        path = "/api/me/progress/%s" % item_id
        if episode_id:
            path = "/api/me/progress/%s/%s" % (item_id, episode_id)
        payload = {
            "currentTime": float(max(0.0, current_time)),
            "duration": float(max(0.0, duration)),
            "isFinished": bool(is_finished),
        }
        return self.patch(path, payload=payload)

    def stream_url_with_token(self, url):
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            base = url
        else:
            base = self._full(url)
        token = self._token()
        if "token=" in base:
            return base
        joiner = "&" if "?" in base else "?"
        return "%s%stoken=%s" % (base, joiner, token)


def find_first_key(data, candidates):
    if isinstance(data, dict):
        for key in candidates:
            if key in data and data[key]:
                return data[key]
        for value in data.values():
            got = find_first_key(value, candidates)
            if got:
                return got
    elif isinstance(data, list):
        for value in data:
            got = find_first_key(value, candidates)
            if got:
                return got
    return None


def iter_audio_urls(data):
    if isinstance(data, dict):
        for key, value in data.items():
            low = key.lower()
            if low in ("contenturl", "url", "streamurl") and isinstance(value, str):
                v = value.lower()
                if any(x in v for x in (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".flac", "/hls", "/stream", "/file/")):
                    yield value
            for nested in iter_audio_urls(value):
                yield nested
    elif isinstance(data, list):
        for value in data:
            for nested in iter_audio_urls(value):
                yield nested


def parse_libraries(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("libraries", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def parse_items(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("results", "libraryItems", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def parse_entities(payload, entity_type=None):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        keys = []
        if entity_type:
            keys.extend([entity_type, entity_type.rstrip("s") + "s"])
        keys.extend(["results", "items", "series", "collections", "authors", "narrators"])
        seen = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
