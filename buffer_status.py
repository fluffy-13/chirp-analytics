"""Check what Buffer did with every post it was handed: sent (with the Instagram link), still
scheduled, or errored. Fills in missing permalinks in the state file and logs a short table.
Run from Actions (`main.py buffer-status`); the Buffer key only lives in GitHub secrets."""
import logging

import buffer_client
from pipeline import State

log = logging.getLogger("buffer_status")

KINDS = ("reels", "stories", "games", "features", "intros")


def run(state=None):
    state = state or State()
    channel = buffer_client.instagram_channel()
    org = channel.get("organization_id")
    changed, errors = 0, []
    for kind in KINDS:
        for key, info in sorted(state.data.get(kind, {}).items()):
            ids = info.get("media_ids") or info.get("media_id") if isinstance(info, dict) else None
            if not ids or info.get("mode") != "buffer":
                continue
            if info.get("permalink") and kind != "reels":
                continue
            ids = ids if isinstance(ids, list) else [ids]
            for pid in ids:
                try:
                    post = buffer_client._post_status(pid, org)
                except Exception as exc:
                    log.warning("%-8s %-28s %s: status unavailable (%s)", kind, key, pid, exc)
                    continue
                status = str(post.get("status"))
                link = post.get("externalLink")
                log.info("%-8s %-28s %s  %-10s %s  sent %s", kind, key, pid, status, link or "-",
                         post.get("sentAt") or "-")
                if "error" in status.lower() or "fail" in status.lower():
                    errors.append((kind, key, pid, post))
                if link and link != info.get("permalink") and len(ids) == 1:
                    state.data[kind][key]["permalink"] = link
                    changed += 1
                if status.lower() != str(info.get("status", "")).lower():
                    state.data[kind][key]["status"] = status
                    changed += 1
    if changed:
        state._save("Buffer status: permalinks")
    for kind, key, pid, post in errors:
        log.error("Buffer could not publish %s %s (%s): %s", kind, key, pid, post)
    return 1 if errors else 0
