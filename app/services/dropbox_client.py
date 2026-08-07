# app/services/dropbox_client.py
"""
Thin client for mirroring the Workbench commander queue into Dropbox.

Mirrors app/services/supabase_client.py's pattern: module-level functions, no
class, env vars read fresh via os.environ.get per call, a fresh
httpx.AsyncClient per call, fails open (returns None/False) on any HTTP
error so a down/misconfigured Dropbox app degrades to "no mirror this time"
instead of breaking the Workbench create/resolve endpoints that call it.

Configured via DROPBOX_TOKEN — a scoped-access, App-folder access token
generated at dropbox.com/developers/apps (Permissions: files.content.write,
files.content.read). Paths are relative to the app's own dedicated folder,
not the user's whole Dropbox.
"""

import json
import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


def is_configured() -> bool:
    return bool(os.environ.get("DROPBOX_TOKEN"))


async def get_current_account() -> Optional[dict[str, Any]]:
    """POST /2/users/get_current_account — used purely as a live health probe."""
    token = os.environ.get("DROPBOX_TOKEN", "")
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
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
    token = os.environ.get("DROPBOX_TOKEN", "")
    if not token:
        log.info("Dropbox not configured (DROPBOX_TOKEN) — skipping mirror to '%s'", path)
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Dropbox-API-Arg": json.dumps({"path": path, "mode": "overwrite", "mute": True}),
        "Content-Type": "application/octet-stream",
    }
    body = json.dumps(data, indent=2, default=str).encode("utf-8")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
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
