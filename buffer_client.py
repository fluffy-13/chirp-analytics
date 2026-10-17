"""Post to Instagram through Buffer's GraphQL API (https://developers.buffer.com).

Buffer is an approved Meta app, so this route needs no Meta developer account and no Facebook
Page: @chirpanalytics is connected inside Buffer with Instagram login, and we hand Buffer
public image URLs + a caption with mode=shareNow.
"""
import logging
import time

import requests

from config import BUFFER_API_KEY, BUFFER_CHANNEL_ID, IG_HANDLE

log = logging.getLogger(__name__)
API = "https://api.buffer.com"


class BufferError(RuntimeError):
    pass


def _gql(query, variables=None, timeout=60):
    if not BUFFER_API_KEY:
        raise BufferError("BUFFER_API_KEY is not set")
    resp = requests.post(API, json={"query": query, "variables": variables or {}}, timeout=timeout,
                         headers={"Authorization": f"Bearer {BUFFER_API_KEY}",
                                  "Content-Type": "application/json"})
    try:
        body = resp.json()
    except ValueError:
        raise BufferError(f"Buffer returned {resp.status_code}: {resp.text[:300]}")
    if resp.status_code >= 400 or body.get("errors"):
        msgs = "; ".join(e.get("message", "") for e in body.get("errors", [])) or resp.text[:300]
        raise BufferError(f"Buffer API error ({resp.status_code}): {msgs}")
    return body.get("data") or {}


ORGS = "query { account { organizations { id name } } }"
CHANNELS = """query Channels($org: OrganizationId!) {
  channels(input: { organizationId: $org }) { id name displayName service isQueuePaused }
}"""


def list_channels():
    out = []
    for org in _gql(ORGS)["account"]["organizations"]:
        for ch in _gql(CHANNELS, {"org": org["id"]}).get("channels", []):
            out.append({**ch, "organization_id": org["id"]})
    return out


_channel = None


def instagram_channel():
    """The Buffer channel for our Instagram account (BUFFER_CHANNEL_ID wins if set)."""
    global _channel
    if _channel:
        return _channel
    channels = list_channels()
    if BUFFER_CHANNEL_ID:
        match = [c for c in channels if c["id"] == BUFFER_CHANNEL_ID]
    else:
        ig = [c for c in channels if str(c.get("service", "")).lower() == "instagram"]
        handle = IG_HANDLE.lstrip("@").lower()
        named = [c for c in ig if handle in (str(c.get("name", "")) + str(c.get("displayName", ""))).lower()]
        match = named or ig
    if not match:
        raise BufferError("No Instagram channel found in Buffer. Connect @chirpanalytics in Buffer "
                          f"first. Channels seen: {[(c['service'], c['name']) for c in channels]}")
    if len(match) > 1:
        raise BufferError("Several Instagram channels in Buffer; set BUFFER_CHANNEL_ID to pick one: "
                          f"{[(c['id'], c['name']) for c in match]}")
    _channel = match[0]
    if _channel.get("isQueuePaused"):
        log.warning("Buffer queue for %s is paused; shareNow should still publish", _channel["name"])
    return _channel


CREATE = """mutation Create($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status externalLink } }
    ... on MutationError { message }
  }
}"""

STATUS = """query Status($input: PostInput!) {
  post(input: $input) { id status externalLink sentAt }
}"""


def _post_status(post_id, org_id=None):
    return _gql(STATUS, {"input": {"id": post_id}})["post"]


def _asset(url, alt, thumb_ms=None):
    if url.lower().endswith(".mp4"):
        return {"video": {"url": url, "metadata": {"thumbnailOffset": int(thumb_ms or 0)}}}
    return {"image": {"url": url, "metadata": {"altText": alt or "Chirp Analytics slide"}}}


def create_post(image_urls, caption, alt_texts=None, wait=240, interval=10, post_type="post",
                thumb_ms=None):
    """Publish now. post_type: "post" (single/carousel, images and/or videos) or "reel".
    Returns {"media_id", "permalink", "status"}; raises if Buffer rejects it."""
    ch = instagram_channel()
    alt_texts = alt_texts or [""] * len(image_urls)
    assets = [_asset(url, alt, thumb_ms) for url, alt in zip(image_urls, alt_texts)]
    if any(a.get("video") for a in assets):
        wait = max(wait, 600)  # Instagram processes video before it goes live
    data = _gql(CREATE, {"input": {
        "text": caption, "channelId": ch["id"], "schedulingType": "automatic", "mode": "shareNow",
        "assets": assets, "metadata": {"instagram": {"type": post_type, "shouldShareToFeed": True}},
    }})
    res = data.get("createPost") or {}
    if res.get("__typename") != "PostActionSuccess":
        raise BufferError(f"Buffer refused the post: {res.get('message') or res}")
    post = res["post"]
    log.info("Buffer accepted post %s (status %s)", post["id"], post.get("status"))
    deadline = time.time() + wait
    while time.time() < deadline and not post.get("externalLink"):
        status = str(post.get("status", "")).lower()
        if "error" in status or "fail" in status:
            raise BufferError(f"Buffer could not publish post {post['id']} (status {post['status']}). "
                              "Open Buffer to see the reason.")
        if status == "sent":
            break
        time.sleep(interval)
        try:
            post = {**post, **_post_status(post["id"], ch["organization_id"])}
        except BufferError as exc:
            log.warning("Couldn't read post status yet: %s", exc)
    if post.get("externalLink"):
        log.info("Live on Instagram: %s", post["externalLink"])
    else:
        log.warning("Buffer accepted post %s but hasn't confirmed it's live yet (status %s)",
                    post["id"], post.get("status"))
    return {"media_id": post["id"], "permalink": post.get("externalLink"),
            "status": post.get("status")}


SCHEMA_PROBE = """query {
  create: __type(name: "CreatePostInput") { inputFields { name type { name kind ofType { name kind } } } }
  image: __type(name: "ImageAssetInput") { inputFields { name type { name kind ofType { name } } } }
  ig: __type(name: "InstagramPostMetadataInput") { inputFields { name type { name ofType { name } } } }
  mode: __type(name: "ShareMode") { enumValues { name } }
  status: __type(name: "PostStatus") { enumValues { name } }
  postInput: __type(name: "PostInput") { inputFields { name } }
}"""


def check():
    """Read-only: show channels and the schema bits we rely on. Posts nothing."""
    chans = list_channels()
    log.info("Buffer channels: %s", [(c["service"], c["name"], c["id"]) for c in chans])
    try:
        log.info("Using Instagram channel: %s", instagram_channel())
    except BufferError as exc:
        log.error("%s", exc)
    try:
        schema = _gql(SCHEMA_PROBE)
        for k, v in schema.items():
            if not v:
                log.info("schema %s: (not exposed)", k)
            elif "enumValues" in v:
                log.info("schema %s: %s", k, [e["name"] for e in v["enumValues"]])
            else:
                log.info("schema %s: %s", k, [f["name"] for f in v["inputFields"]])
    except BufferError as exc:
        log.info("Schema introspection not available: %s", exc)
    try:  # every asset / Instagram / video type, with fields or enum values
        names = [t["name"] for t in _gql("query { __schema { types { name } } }")["__schema"]["types"]]
        wanted = [n for n in names if any(k in n.lower() for k in ("asset", "instagram", "video", "reel", "posttype"))]
        log.info("schema types: %s", wanted)
        for n in wanted:
            t = _gql('query($n: String!) { __type(name: $n) { kind inputFields { name type { name kind '
                     'ofType { name kind ofType { name } } } } fields { name } enumValues { name } } }',
                     {"n": n})["__type"]
            if t:
                vals = (t.get("enumValues") and [e["name"] for e in t["enumValues"]]) or \
                       (t.get("inputFields") and [(f["name"], f["type"]["name"] or
                                                   (f["type"]["ofType"] or {}).get("name"))
                                                  for f in t["inputFields"]]) or \
                       [f["name"] for f in (t.get("fields") or [])]
                log.info("type %s (%s): %s", n, t["kind"], vals)
    except Exception as exc:
        log.info("Type listing not available: %s", exc)
