# app/services/dropbox_client.py
"""
Thin client for mirroring the Workbench commander queue into Dropbox.

Mirrors app/services/supabase_client.py's pattern: module-level functions, no
class, env vars read fresh via os.environ.get per call, fails open (returns
None/False) on any HTTP error so a down/misconfigured Dropbox app degrades to
"no mirror this time" instead of breaking the Workbench create/resolve
endpoints that call it.

Auth: Dropbox's own "Generated access token" (DROPBOX_TOKEN, a bare static
bearer token) is short-lived by default on current apps — it expires after 4
hours with no way to renew it, which is a real problem for a hackathon judged
a day after the code freeze. The supported path here is an OAuth refresh
token (DROPBOX_APP_KEY + DROPBOX_APP_SECRET + DROPBOX_REFRESH_TOKEN, obtained
once via the authorization-code flow with token_access_type=offline): this
client exchanges the refresh token for a fresh short-lived access token on
demand, caches it in memory until shortly before it expires, and refreshes
again automatically — no manual token regeneration needed before a demo.
DROPBOX_TOKEN alone still works as a fallback for local/manual testing, but
will die after 4 hours exactly as before.
"""

import logging
import os
import time
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_TOKEN_REFRESH_URL = "https://api.dropboxapi.com/oauth2/token"

# In-memory cache for the access token obtained via the refresh-token flow.
_cached_access_token: Optional[str] = None
_cached_access_token_expiry: float = 0.0  # epoch seconds


def is_configured() -> bool:
    has_refresh_flow = bool(
        os.environ.get("DROPBOX_REFRESH_TOKEN")
        and os.environ.get("DROPBOX_APP_KEY")
        and os.environ.get("DROPBOX_APP_SECRET")
    )
    return has_refresh_flow or bool(os.environ.get("DROPBOX_TOKEN"))


async def _refresh_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """Exchange the long-lived DROPBOX_REFRESH_TOKEN for a fresh short-lived
    access token. Returns None (never raises) if the refresh flow isn't
    configured or the exchange fails."""
    refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN", "")
    app_key = os.environ.get("DROPBOX_APP_KEY", "")
    app_secret = os.environ.get("DROPBOX_APP_SECRET", "")
    if not (refresh_token and app_key and app_secret):
        return None

    try:
        response = await client.post(
            _TOKEN_REFRESH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_key,
                "client_secret": app_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        log.warning("Dropbox access token refresh failed: %s", exc)
        return None

    global _cached_access_token, _cached_access_token_expiry
    _cached_access_token = payload.get("access_token")
    # Refresh 60s early so a call in-flight doesn't race the real expiry.
    _cached_access_token_expiry = time.time() + payload.get("expires_in", 14400) - 60
    return _cached_access_token


async def _get_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """Return a usable access token: a cached one from the refresh flow if
    still fresh, a newly refreshed one if configured, or the static
    DROPBOX_TOKEN fallback."""
    if os.environ.get("DROPBOX_REFRESH_TOKEN"):
        if _cached_access_token and time.time() < _cached_access_token_expiry:
            return _cached_access_token
        token = await _refresh_access_token(client)
        if token:
            return token
        # Fall through to the static token if refresh failed but one is set.

    return os.environ.get("DROPBOX_TOKEN") or None


async def get_current_account() -> Optional[dict[str, Any]]:
    """POST /2/users/get_current_account — used purely as a live health probe."""
    if not is_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            token = await _get_access_token(client)
            if not token:
                return None
            response = await client.post(
                "https://api.dropboxapi.com/2/users/get_current_account",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        log.warning("Dropbox get_current_account failed: %s", exc)
        return None


async def upload_json(path: str, data: Any) -> bool:
    """
    Overwrite a JSON file at `path` (relative to the app's own folder, e.g.
    "/commander-queue/pending.json") with `data`. Returns False on any
    failure or missing configuration rather than raising — this is a
    best-effort mirror, not a system of record in its own right.
    """
    import json

    if not is_configured():
        log.info("Dropbox not configured — skipping mirror to '%s'", path)
        return False

    body = json.dumps(data, indent=2, default=str).encode("utf-8")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            token = await _get_access_token(client)
            if not token:
                return False
            headers = {
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": json.dumps({"path": path, "mode": "overwrite", "mute": True}),
                "Content-Type": "application/octet-stream",
            }
            response = await client.post(
                "https://content.dropboxapi.com/2/files/upload",
                headers=headers,
                content=body,
            )
            response.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        log.warning("Dropbox upload failed for '%s': %s", path, exc)
        return False
