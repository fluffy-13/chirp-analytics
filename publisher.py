"""Hosts the image publicly, then posts it.

Two routes, picked automatically:
  * MAKE_WEBHOOK_URL set  -> hand image URL + caption to a Make.com scenario that posts it
  * otherwise             -> Instagram Graph API directly (needs a Meta developer app token)
"""
import logging
import time
from pathlib import Path

import requests

from config import (GRAPH_API_VERSION, IG_ACCESS_TOKEN, IG_USER_ID, IMAGE_HOST_BASE_URL,
                    MAKE_WEBHOOK_URL, SUPABASE_BUCKET, SUPABASE_SERVICE_KEY, SUPABASE_URL)

log = logging.getLogger(__name__)


class PublishError(RuntimeError):
    pass


def host_image(path):
    """Return a public URL Instagram can fetch."""
    path = Path(path)
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path.name}"
        headers = {"apikey": SUPABASE_SERVICE_KEY, "Content-Type": "image/jpeg", "x-upsert": "true"}
        if SUPABASE_SERVICE_KEY.startswith("eyJ"):
            # legacy service_role JWT; new sb_secret_ keys go in `apikey` only and the
            # gateway builds the Authorization header itself
            headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_KEY}"
        resp = requests.post(url, data=path.read_bytes(), timeout=30, headers=headers)
        if resp.status_code >= 400:
            raise PublishError(f"Supabase upload failed: {resp.status_code} {resp.text[:200]}")
        return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{path.name}"
    if IMAGE_HOST_BASE_URL:
        return f"{IMAGE_HOST_BASE_URL.rstrip('/')}/{path.name}"
    raise PublishError("No image host configured: set SUPABASE_* or IMAGE_HOST_BASE_URL")


def _graph(method, endpoint, **params):
    if not (IG_ACCESS_TOKEN and IG_USER_ID):
        raise PublishError("IG_ACCESS_TOKEN and IG_USER_ID must be set")
    # Instagram-Login tokens (IGAA..., IGQV...) use graph.instagram.com;
    # Facebook-Login tokens (EAA...) use graph.facebook.com
    host = "graph.instagram.com" if IG_ACCESS_TOKEN.startswith("IG") else "graph.facebook.com"
    url = f"https://{host}/{GRAPH_API_VERSION}/{endpoint}"
    params["access_token"] = IG_ACCESS_TOKEN
    resp = requests.request(method, url, params=params if method == "GET" else None,
                            data=params if method != "GET" else None, timeout=30)
    try:
        body = resp.json()
    except ValueError:
        raise PublishError(f"Non-JSON response {resp.status_code} from {endpoint}")
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        raise PublishError(f"{endpoint}: {err.get('message', body)} (code {err.get('code')})")
    return body


def _wait_until_ready(container_id, timeout=180, interval=4):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _graph("GET", container_id, fields="status_code,status").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"Container {container_id} status {status}")
        time.sleep(interval)
    raise PublishError(f"Container {container_id} not ready after {timeout}s")


def _make_payload(image_url, caption, post=None, sample=False):
    post = post or {}
    return {"image_url": image_url, "caption": caption, "sample": sample,
            "game_id": post.get("game_id"), "player": post.get("player_name"),
            "date": post.get("date")}


def _post_to_make(payload, timeout=200):
    """POST to the Make webhook. Returns the parsed JSON reply, or {} for a plain 'Accepted'."""
    resp = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise PublishError(f"Make webhook returned {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and body.get("error"):
        raise PublishError(f"Make scenario reported an error: {body['error']}")
    log.info("Make replied %s: %s", resp.status_code, resp.text[:300])
    return body if isinstance(body, dict) else {}


def publish_via_make(image_url, caption, post=None):
    body = _post_to_make(_make_payload(image_url, caption, post))
    media_id = str(body.get("media_id") or body.get("id") or "").strip()
    if not media_id or media_id in ("None", "null"):
        # A bare "Accepted" only means Make queued it; Instagram may still have refused.
        raise PublishError(
            "Make did not confirm an Instagram post id. Check the scenario's History in Make. "
            "(The scenario needs a Webhook response module returning {\"media_id\": ...}.)")
    log.info("Instagram post confirmed via Make: media_id=%s", media_id)
    return {"media_id": media_id, "permalink": body.get("permalink"), "image_url": image_url}


def send_make_sample():
    """Teach Make the payload shape. Run BEFORE adding the Instagram module to the scenario."""
    if not MAKE_WEBHOOK_URL:
        raise PublishError("MAKE_WEBHOOK_URL is not set")
    _post_to_make(_make_payload(
        "https://cxmkjvnrovgkeslypmix.supabase.co/storage/v1/object/public/ig-posts/sample.jpg",
        "Sample caption from Chirp Analytics (not a real post).",
        {"game_id": 0, "player_name": "Sample Player", "date": "2026-01-01"}, sample=True),
        timeout=60)
    log.info("Sample payload sent to Make")


def publish(image_path, caption, post=None):
    image_url = host_image(image_path)
    log.info("Image hosted at %s", image_url)
    if MAKE_WEBHOOK_URL:
        return publish_via_make(image_url, caption, post)
    container = _graph("POST", f"{IG_USER_ID}/media", image_url=image_url, caption=caption)
    _wait_until_ready(container["id"])
    media = _graph("POST", f"{IG_USER_ID}/media_publish", creation_id=container["id"])
    permalink = _graph("GET", media["id"], fields="permalink").get("permalink")
    log.info("Published %s %s", media["id"], permalink or "")
    return {"media_id": media["id"], "permalink": permalink, "image_url": image_url}
