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
        # Some reverse proxies fail on /api/authorize; fallback to /api/me.
        try:
            return self.post("/api/authorize")
        except AbsApiError as exc:
            if "HTTP 502" not in str(exc):
                raise
        return self.get("/api/me")

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
            response = self._request_once(method, path, params=params, payload=payload)
            last_status = response.status_code
            if response.status_code < 400:
                return self._json_or_empty(response)

            # Retry once with a fresh user/pass token.
            if response.status_code in (401, 403) and self.auth_mode == 1 and attempt == 0:
                self.addon.setSetting("token", "")
                continue

            # Proxy fallback: retry GET with query token (no Authorization header).
            if response.status_code == 502 and method == "GET":
                query_response = self._request_get_with_query_token(path, params=params)
                last_status = query_response.status_code
                if query_response.status_code < 400:
                    return self._json_or_empty(query_response)

            break

        raise AbsApiError("%s %s failed: HTTP %s" % (method, path, last_status))

    def _request_once(self, method, path, params=None, payload=None):
        url = self._full(path)
        headers = self.auth_headers()
        if method == "GET":
            return self.session.get(url, headers=headers, params=params or {}, timeout=30)
        if method == "POST":
            return self.session.post(url, headers=headers, data=json.dumps(payload or {}), timeout=30)
        if method == "PATCH":
            return self.session.patch(url, headers=headers, data=json.dumps(payload or {}), timeout=30)
        raise AbsApiError("Unsupported HTTP method: %s" % method)

    def _request_get_with_query_token(self, path, params=None):
        query = dict(params or {})
        query.setdefault("token", self._token())
        return self.session.get(self._full(path), params=query, timeout=30)

    @staticmethod
    def _json_or_empty(response):
        if not response.text:
            return {}
        try:
            return response.json()
        except Exception:
            return {}

    def libraries(self):
        return self.get("/api/libraries")

    def library_items(self, library_id, page=0, limit=200):
        return self.get(
            "/api/libraries/%s/items" % library_id,
            params={"minified": 1, "sort": "media.metadata.title", "desc": 0, "limit": limit, "page": page, "collapseseries": 0},
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
        return payload
    if isinstance(payload, dict):
        for key in ("libraries", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def parse_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "libraryItems", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
