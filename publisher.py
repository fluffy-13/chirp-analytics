"""Hosts the image publicly, then runs the Instagram container → poll → publish flow."""
import logging
import time
from pathlib import Path

import requests

from config import (GRAPH_API_VERSION, IG_ACCESS_TOKEN, IG_USER_ID, IMAGE_HOST_BASE_URL,
                    SUPABASE_BUCKET, SUPABASE_SERVICE_KEY, SUPABASE_URL)

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


def publish(image_path, caption):
    image_url = host_image(image_path)
    log.info("Image hosted at %s", image_url)
    container = _graph("POST", f"{IG_USER_ID}/media", image_url=image_url, caption=caption)
    _wait_until_ready(container["id"])
    media = _graph("POST", f"{IG_USER_ID}/media_publish", creation_id=container["id"])
    permalink = _graph("GET", media["id"], fields="permalink").get("permalink")
    log.info("Published %s %s", media["id"], permalink or "")
    return {"media_id": media["id"], "permalink": permalink, "image_url": image_url}
