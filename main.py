"""Daily pipeline: fetch last night's games → compute metrics → pick spotlight → copy → card → publish.

  python main.py                       # dry run for yesterday (renders card + caption, no post)
  python main.py --publish             # post to Instagram
  python main.py --date 2026-10-14     # a specific night
  python main.py --fixtures tests/fixtures   # offline run on saved JSON
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from config import STATE_FILE
from content_generator import build_caption, generate_copy
from metrics import analyze_game, build_post, pick_spotlight
from nhl_fetcher import FixtureSource, LiveSource, completed_games, default_target_date, load_game
from renderer import render_card

log = logging.getLogger("pipeline")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"posted_game_ids": [], "history": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def run(date, source, publish=False):
    state = load_state()
    games = [g for g in completed_games(source, date) if g["id"] not in state["posted_game_ids"]]
    if not games:
        log.info("No new completed games for %s", date)
        return None

    analyses = []
    for g in games:
        try:
            analyses.append(analyze_game(load_game(source, g)))
        except Exception:
            log.exception("Skipping game %s", g.get("id"))
    if not analyses:
        raise RuntimeError("Every game failed to load")

    game, player = pick_spotlight(analyses)
    post = build_post(game, player)
    log.info("Spotlight: %s (%s) Game Score %.2f, ixG %.2f",
             post["player_name"], post["team_abbrev"], player["game_score"], player["ixG"])

    copy = generate_copy(post)
    image_path = render_card(post, copy["hook"])
    caption = build_caption(copy, post)
    image_path.with_suffix(".txt").write_text(caption)

    if not publish:
        log.info("Dry run — card and caption written to %s", image_path.parent)
        return {"image": str(image_path), "caption": caption}

    from publisher import publish as ig_publish
    result = ig_publish(image_path, caption, post)
    state["posted_game_ids"].append(post["game_id"])
    state["history"].append({
        "game_id": post["game_id"], "player": post["player_name"], "date": date,
        "media_id": result["media_id"], "permalink": result["permalink"],
        "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    save_state(state)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=default_target_date(), help="YYYY-MM-DD (default: yesterday ET)")
    ap.add_argument("--publish", action="store_true", help="actually post to Instagram")
    ap.add_argument("--fixtures", help="directory of saved API JSON for offline runs")
    ap.add_argument("--make-sample", action="store_true",
                    help="send a sample payload to the Make webhook (scenario setup only)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.make_sample:
        from publisher import send_make_sample
        try:
            send_make_sample()
        except Exception:
            log.exception("Sending the Make sample failed")
            return 1
        return 0
    source = FixtureSource(args.fixtures) if args.fixtures else LiveSource()
    try:
        run(args.date, source, publish=args.publish)
    except Exception:
        log.exception("Pipeline failed")
        return 1  # non-zero so cron / GitHub Actions flags the failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
