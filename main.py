"""Chirp Analytics command line.

  python main.py live                          # game night: post each game 5-10 min after it ends
  python main.py games --date 2026-10-15       # every finished game on a date (skips posted ones)
  python main.py games --date 2026-10-15 --game-id 2026020116 --force
  python main.py weekly                        # last Monday-Sunday week
  python main.py weekly --end 2026-10-18
  python main.py make-sample                   # Make.com setup: send a sample payload

Add --fixtures DIR to run offline on saved API JSON. Where posts go is POST_MODE
(preview by default — nothing is posted), or override with --mode preview|make|graph.
"""
import argparse
import logging
import sys

from nhl_fetcher import FixtureSource, LiveSource, default_target_date

log = logging.getLogger("main")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", choices=["live", "games", "weekly", "make-sample"])
    ap.add_argument("--date", default=None, help="game night YYYY-MM-DD (games; default yesterday ET)")
    ap.add_argument("--game-id", default=None)
    ap.add_argument("--end", default=None, help="week ending YYYY-MM-DD (weekly; a Sunday)")
    ap.add_argument("--mode", choices=["preview", "make", "graph"], default=None)
    ap.add_argument("--force", action="store_true", help="re-post even if already posted")
    ap.add_argument("--fixtures", help="directory of saved API JSON for offline runs")
    ap.add_argument("--max-runtime", type=float, default=5.6, help="live: hours before exiting")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "make-sample":
        from publisher import send_make_sample
        try:
            send_make_sample()
            return 0
        except Exception:
            log.exception("Sending the Make sample failed")
            return 1

    import pipeline
    source = FixtureSource(args.fixtures) if args.fixtures else LiveSource()
    state = pipeline.State()
    try:
        if args.command == "live":
            gave_up = pipeline.run_live(source, state, mode=args.mode,
                                        max_runtime=args.max_runtime * 3600)
            if gave_up:
                log.error("Gave up on games after repeated failures: %s", gave_up)
                return 1
        elif args.command == "games":
            failed = pipeline.run_games(source, args.date or default_target_date(), state,
                                        mode=args.mode, game_id=args.game_id, force=args.force)
            if failed:
                log.error("These games failed: %s", failed)
                return 1
        elif args.command == "weekly":
            pipeline.run_weekly(source, state, end=args.end, mode=args.mode, force=args.force)
    except Exception:
        log.exception("%s failed", args.command)
        return 1  # non-zero so GitHub Actions flags the failure (and emails you)
    return 0


if __name__ == "__main__":
    sys.exit(main())
