"""Hosts images publicly, then posts them (single image or carousel).

Routes (POST_MODE):
  preview -> save slides + caption to the `previews` branch; nothing is posted
  make    -> hand image URLs + caption to a Make.com scenario that posts them
  graph   -> Instagram Graph API directly (needs a Meta developer app token)
  buffer  -> Buffer's API (no Meta developer app or Facebook Page needed)
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import (GRAPH_API_VERSION, IG_ACCESS_TOKEN, IG_USER_ID, IMAGE_HOST_BASE_URL,
                    MAKE_WEBHOOK_URL, OUTPUT_DIR, POST_MODE, SUPABASE_BUCKET,
                    SUPABASE_SERVICE_KEY, SUPABASE_URL)

log = logging.getLogger(__name__)


class PublishError(RuntimeError):
    pass


def host_image(path, folder=None):
    """Return a public URL Instagram can fetch."""
    path = Path(path)
    name = f"{folder.strip('/')}/{path.name}" if folder else path.name
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"
        headers = {"apikey": SUPABASE_SERVICE_KEY, "Content-Type": "image/jpeg", "x-upsert": "true"}
        if SUPABASE_SERVICE_KEY.startswith("eyJ"):
            # legacy service_role JWT; new sb_secret_ keys go in `apikey` only and the
            # gateway builds the Authorization header itself
            headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_KEY}"
        resp = requests.post(url, data=path.read_bytes(), timeout=30, headers=headers)
        if resp.status_code >= 400:
            raise PublishError(f"Supabase upload failed: {resp.status_code} {resp.text[:200]}")
        return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"
    if IMAGE_HOST_BASE_URL:
        return f"{IMAGE_HOST_BASE_URL.rstrip('/')}/{name}"
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


def _confirmed(body, where):
    media_id = str(body.get("media_id") or body.get("id") or "").strip()
    if not media_id or media_id in ("None", "null"):
        raise PublishError(
            f"{where} did not confirm an Instagram post id. Check the scenario's History in Make. "
            "(The scenario needs a Webhook response module returning {\"media_id\": ...}.)")
    return media_id


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


# ---------------------------------------------------------------- carousels ---
def _wait_all(ids):
    for cid in ids:
        _wait_until_ready(cid)


def carousel_via_graph(image_urls, caption):
    children = []
    for url in image_urls:
        child = _graph("POST", f"{IG_USER_ID}/media", image_url=url, is_carousel_item="true")
        children.append(child["id"])
    _wait_all(children)
    container = _graph("POST", f"{IG_USER_ID}/media", media_type="CAROUSEL",
                       children=",".join(children), caption=caption)
    _wait_until_ready(container["id"])
    media = _graph("POST", f"{IG_USER_ID}/media_publish", creation_id=container["id"])
    permalink = _graph("GET", media["id"], fields="permalink").get("permalink")
    log.info("Published carousel %s %s", media["id"], permalink or "")
    return {"media_id": media["id"], "permalink": permalink}


def carousel_via_make(image_urls, caption, key, meta=None):
    payload = {"type": "carousel", "image_urls": image_urls, "image_url": image_urls[0],
               "caption": caption, "key": key, "sample": False, **(meta or {})}
    body = _post_to_make(payload)
    media_id = _confirmed(body, "Make")
    log.info("Carousel confirmed via Make: media_id=%s", media_id)
    return {"media_id": media_id, "permalink": body.get("permalink")}


# ------------------------------------------------------------------ previews ---
_preview_store = None


def preview_store():
    global _preview_store
    if _preview_store is None:
        from git_store import default_store
        _preview_store = default_store("previews", OUTPUT_DIR / "previews")
    return _preview_store


def _render_index(entries):
    lines = ["# Chirp Analytics previews", "",
             "Newest first. Slides and caption exactly as they would post.", ""]
    for e in entries:
        lines.append(f"## {e['title']}")
        lines.append(f"`{e['key']}` · rendered {e['at']} · mode: {e['mode']}")
        lines.append("")
        lines.append(" ".join(f'<img src="{f}" width="260">' for f in e["files"]))
        lines.append("")
        lines.append("<details><summary>Caption</summary>")
        lines.append("")
        lines.append("```")
        lines.append(e["caption"])
        lines.append("```")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines).encode()


def save_preview(image_paths, caption, key, title, mode="preview", keep=80):
    store = preview_store()
    folder = key.replace(":", "-")
    files = {f"{folder}/{Path(p).name}": Path(p).read_bytes() for p in image_paths}
    files[f"{folder}/caption.txt"] = caption.encode()
    raw = store.read("index.json")
    entries = json.loads(raw) if raw else []
    entries = [e for e in entries if e["key"] != key]
    entries.insert(0, {"key": key, "title": title, "mode": mode, "caption": caption,
                       "files": [f"{folder}/{Path(p).name}" for p in image_paths],
                       "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
    entries = entries[:keep]
    files["index.json"] = json.dumps(entries, indent=1).encode()
    files["README.md"] = _render_index(entries)
    store.write(files, f"Preview {key}")
    log.info("Preview saved: %s", key)


def publish_carousel(image_paths, caption, key, title, meta=None, mode=None):
    """Post a carousel (or save a preview). Returns a result dict with media_id."""
    mode = (mode or POST_MODE).lower()
    if mode == "preview":
        save_preview(image_paths, caption, key, title)
        return {"media_id": "preview", "permalink": None, "mode": "preview"}
    folder = "posts/" + key.replace(":", "-")
    urls = [host_image(p, folder=folder) for p in image_paths]
    log.info("Hosted %d slides under %s", len(urls), folder)
    if mode == "buffer":
        from buffer_client import create_post
        result = create_post(urls, caption, alt_texts=(meta or {}).get("alt_texts"))
    elif mode == "make":
        if not MAKE_WEBHOOK_URL:
            raise PublishError("POST_MODE=make but MAKE_WEBHOOK_URL is not set")
        result = carousel_via_make(urls, caption, key, meta)
    elif mode == "graph":
        result = carousel_via_graph(urls, caption)
    else:
        raise PublishError(f"Unknown POST_MODE {mode!r} (use preview, buffer, make or graph)")
    try:  # keep a record of what went out alongside the previews
        save_preview(image_paths, caption, key, title, mode=mode)
    except Exception as exc:
        log.warning("Posted, but saving the preview copy failed: %s", exc)
    return {**result, "mode": mode, "image_urls": urls}
