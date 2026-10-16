"""Save raw NHL API JSON for one night's games (for building and testing offline).

  python tools/dump_games.py 2026-10-15 out_dir [max_games]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nhl_fetcher import LiveSource  # noqa: E402


def main():
    date, out = sys.argv[1], Path(sys.argv[2])
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    out.mkdir(parents=True, exist_ok=True)
    src = LiveSource()
    score = src.score(date)
    (out / "score.json").write_text(json.dumps(score))
    for g in score.get("games", [])[:limit]:
        gid = g["id"]
        (out / f"{gid}_boxscore.json").write_text(json.dumps(src.boxscore(gid)))
        (out / f"{gid}_play-by-play.json").write_text(json.dumps(src.play_by_play(gid)))
        (out / f"{gid}_shifts.json").write_text(json.dumps({"data": src.shifts(gid)}))
        print("saved", gid, g.get("gameState"))


if __name__ == "__main__":
    main()
