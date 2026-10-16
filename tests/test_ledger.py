import json

from git_store import LocalStore
from ledger import Ledger, SK_FIELDS, skater_rows


def _team(ab, side, won):
    return {"abbrev": ab, "score": 3 if won else 2, "opp_score": 2 if won else 3, "won": won,
            "xg": 2.5, "xgf5": 1.5, "xga5": 1.2, "cf5": 40, "ca5": 35, "toi5_s": 2900}


def _game(gid, day, scores, goalies=()):
    players = [{"player_id": pid, "name": f"P{pid}", "team_abbrev": "MIN", "position": "C",
                "game_score": gs, "G": 1, "A": 0, "SOG": 3, "ixG": 0.4, "xGF": 0.8, "xGA": 0.5,
                "CF": 12, "CA": 9, "team_side": "home"} for pid, gs in scores.items()]
    return {"game_id": gid, "date": day, "outcome": "REG", "players": players,
            "goalies": list(goalies),
            "teams": {"away": _team("STL", "away", False), "home": _team("MIN", "home", True)}}


def test_context_uses_only_earlier_games(tmp_path):
    led = Ledger(LocalStore(tmp_path))
    for i, gs in enumerate([0.2, 0.4, 0.6]):
        led.add(_game(2026020001 + i, f"2026-10-0{i + 1}", {7: gs}))
    led.save()
    tonight = _game(2026020002, "2026-10-02", {7: 0.4})
    assert Ledger(LocalStore(tmp_path)).context(tonight)[7] == {"gp": 1, "avg": 0.2, "trend": None}


def test_hot_and_cold_runs(tmp_path):
    led = Ledger(LocalStore(tmp_path))
    hist = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.2, 1.1]
    for i, gs in enumerate(hist):
        led.add(_game(2026020010 + i, f"2026-10-{i + 1:02d}", {7: gs, 8: -gs}))
    ctx = led.context(_game(2026020099, "2026-10-20", {7: 1.0, 8: -1.0}))
    assert ctx[7]["trend"] == "hot" and ctx[8]["trend"] == "cold"
    # one big night after a flat run is not a streak
    led2 = Ledger(LocalStore(tmp_path / "b"))
    for i in range(6):
        led2.add(_game(2026020010 + i, f"2026-10-{i + 1:02d}", {7: 0.0}))
    assert led2.context(_game(2026020099, "2026-10-20", {7: 3.0}))[7]["trend"] is None


def test_one_file_per_game_and_decoding(tmp_path):
    store = LocalStore(tmp_path)
    led = Ledger(store)
    led.add(_game(2026020001, "2026-10-01", {7: 1.0}))
    led.add(_game(2026020002, "2026-10-02", {7: 2.0}))
    led.save()
    files = store.read_dir("games/20262027")
    assert len(files) == 2
    rec = json.loads(files["games/20262027/2026020001.json"])
    row = skater_rows(rec)["7"]
    assert row["gs"] == 1.0 and row["team"] == "MIN" and len(rec["sk"]["7"]) == len(SK_FIELDS)
    assert [r["id"] for r in Ledger(store).season_games("20262027", start="2026-10-02")] == [2026020002]
