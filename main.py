"""Chirp Analytics command line.

  python main.py live                          # game night: post each game 5-10 min after it ends
  python main.py games --date 2026-10-15       # every finished game on a date (skips posted ones)
  python main.py games --date 2026-10-15 --game-id 2026020116 --force
  python main.py weekly                        # last Monday-Sunday week
  python main.py weekly --end 2026-10-18
  python main.py make-sample                   # Make.com setup: send a sample payload
  python main.py buffer-check                  # Buffer setup: list channels + schema (posts nothing)
  python main.py intro --post standings        # one-off season-so-far posts: standings|finishing|goalies

Add --fixtures DIR to run offline on saved API JSON. Where posts go is POST_MODE
(preview by default — nothing is posted), or override with --mode preview|buffer|make|graph.
"""
import argparse
import logging
import sys

from nhl_fetcher import FixtureSource, LiveSource, default_target_date

log = logging.getLogger("main")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", choices=["live", "games", "weekly", "make-sample", "buffer-check",
                                            "intro"])
    ap.add_argument("--date", default=None, help="game night YYYY-MM-DD (games; default yesterday ET)")
    ap.add_argument("--game-id", default=None)
    ap.add_argument("--end", default=None, help="week ending YYYY-MM-DD (weekly; a Sunday)")
    ap.add_argument("--mode", choices=["preview", "buffer", "make", "graph"], default=None)
    ap.add_argument("--force", action="store_true", help="re-post even if already posted")
    ap.add_argument("--fixtures", help="directory of saved API JSON for offline runs")
    ap.add_argument("--post", choices=["standings", "finishing", "goalies"],
                    help="intro: which season-so-far post")
    ap.add_argument("--max-runtime", type=float, default=5.6, help="live: hours before exiting")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    capture = _LogCapture()
    logging.getLogger().addHandler(capture)
    try:
        return _run(args)
    finally:
        capture.save(args.command)


class _LogCapture(logging.Handler):
    """Keeps this run's log so it can be saved next to the previews (handy for debugging)."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        self.lines.append(self.format(record))
        del self.lines[:-4000]

    def save(self, command):
        import os
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return
        try:
            from git_store import GitBranchStore
            GitBranchStore("previews").write(
                {f"logs/{command}-latest.log": "\n".join(self.lines).encode()}, f"Log: {command}")
        except Exception as exc:  # never fail a run over its log
            print(f"(could not save log: {exc})")


def _run(args):

    if args.command == "buffer-check":
        import buffer_client
        try:
            buffer_client.check()
            return 0
        except Exception:
            log.exception("Buffer check failed")
            return 1

    if args.command == "make-sample":
        from publisher import send_make_sample
        try:
            send_make_sample()
            return 0
        except Exception:
            log.exception("Sending the Make sample failed")
            return 1

    import pipeline
    if args.command == "intro":
        if not args.post:
            log.error("intro needs --post standings|finishing|goalies")
            return 1
        try:
            pipeline.run_intro(args.post, pipeline.State(), mode=args.mode, force=args.force)
            return 0
        except Exception:
            log.exception("intro failed")
            return 1

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
