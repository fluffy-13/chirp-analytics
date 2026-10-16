"""Seed the tracker career logs from tools/tracker_data.py output.

    python tools/backfill_trackers.py DATA_DIR [--push]

Without --push it writes to the local state folder; with it, to the `state` branch.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_store import GitBranchStore, LocalStore  # noqa: E402
from trackers import CROSBY, OVI, CareerLog  # noqa: E402


def main(data_dir, push=False):
    data = Path(data_dir)
    store = GitBranchStore("state") if push else LocalStore(Path(__file__).resolve().parents[1] / "state")
    goals = json.loads((data / "ovi_goals.json").read_text())
    by_game = {}
    for g in goals:
        by_game.setdefault(str(g["game_id"]), []).append(g)
    for pid in (OVI, CROSBY):
        clog = CareerLog(pid, store)
        for e in json.loads((data / f"gamelog_{pid}.json").read_text()):
            gk = None
            if pid == OVI:
                evs = by_game.get(str(e["gameId"]), [])
                gk = [x["goalie_id"] for x in evs]
                for x in evs:
                    if x.get("goalie_id"):
                        clog.data["goalies"][str(x["goalie_id"])] = x["goalie"]
            clog.add_from_gamelog(e, gk)
        t = clog.totals()
        print(pid, t, "goalies:", len(clog.data["goalies"]))
        clog.save(f"Seed tracker {pid}")


if __name__ == "__main__":
    main(sys.argv[1], "--push" in sys.argv)
