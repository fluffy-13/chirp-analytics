import gzip
import json
from pathlib import Path

import trackers
from cards import game_number
from git_store import LocalStore

DATA = Path(__file__).parent / "data"


def _pbp(gid):
    with gzip.open(DATA / f"{gid}_play-by-play.json.gz", "rt") as f:
        return json.load(f)


def test_game_number():
    assert game_number(2026020116) == 116
    assert game_number(2026030121) is None  # playoffs


def test_goal_events_flags_game_winner():
    pbp = _pbp(2026020116)  # STL 4 @ MIN 5
    boldy = next(r["playerId"] for r in pbp["rosterSpots"] if r["lastName"]["default"] == "Boldy")
    ev = trackers.goal_events(pbp, boldy)
    assert len(ev) == 3 and all(e["goalie"] for e in ev)
    assert [e["team_goal_no"] for e in ev] == sorted(e["team_goal_no"] for e in ev)


def test_career_log_totals_and_merge(tmp_path):
    store = LocalStore(tmp_path)
    a = trackers.CareerLog(trackers.OVI, store)
    a.add_from_gamelog({"gameId": 1, "gameDate": "2026-10-01", "opponentAbbrev": "BOS", "goals": 2,
                        "assists": 1, "powerPlayGoals": 1}, [11, None])
    a.save("a")
    b = trackers.CareerLog(trackers.OVI, store)
    b.add_from_gamelog({"gameId": 2, "gameDate": "2026-10-03", "opponentAbbrev": "NYR", "goals": 1,
                        "assists": 0}, [12])
    b.save("b")
    t = trackers.CareerLog(trackers.OVI, store).totals()
    assert (t["g"], t["a"], t["p"], t["gp"], t["ppg"]) == (3, 1, 4, 2, 1)


def test_no_tracker_without_live_source():
    game = {"teams": {"away": {"abbrev": "WSH"}, "home": {"abbrev": "PIT"}}}
    assert trackers.tracker_slides(object(), game, {}) == ([], [])
