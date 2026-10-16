"""Backfill the season ledger (each player's Game Score in every game) for a date range.

    python tools/build_ledger.py 2026-09-25 2026-10-16

In GitHub Actions it writes to the `state` branch (merging with what's there).
"""
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import Ledger  # noqa: E402
from metrics import analyze_game  # noqa: E402
from nhl_fetcher import FINAL_STATES, GAME_TYPES, LiveSource, load_game  # noqa: E402

log = logging.getLogger("build_ledger")


def main(start, end):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    source, led = LiveSource(), Ledger()
    d, end_d, n = date.fromisoformat(start), date.fromisoformat(end), 0
    while d <= end_d:
        for g in source.score(d.isoformat()).get("games", []):
            if g.get("gameType") not in GAME_TYPES or g.get("gameState") not in FINAL_STATES:
                continue
            try:
                led.add(analyze_game(load_game(source, g)))
                n += 1
            except Exception:
                log.exception("Skipping %s", g["id"])
        d += timedelta(days=1)
    led.save(f"Ledger backfill {start}..{end} ({n} games)")
    log.info("Ledger: %d games, %d players", n, len(led.data["players"]))


if __name__ == "__main__":
    main(*sys.argv[1:3])
