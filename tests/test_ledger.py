import json

from git_store import LocalStore
from ledger import Ledger


def _game(gid, day, scores):
    return {"game_id": gid, "date": day, "goalies": [],
            "players": [{"player_id": pid, "name": f"P{pid}", "team_abbrev": "MIN", "position": "C",
                         "game_score": gs} for pid, gs in scores.items()]}


def test_context_uses_only_earlier_games(tmp_path):
    led = Ledger(LocalStore(tmp_path))
    for i, gs in enumerate([0.2, 0.4, 0.6]):
        led.add(_game(2026020001 + i, f"2026-10-0{i + 1}", {7: gs}))
    tonight = _game(2026020002, "2026-10-02", {7: 0.4})
    ctx = led.context(tonight)[7]
    assert ctx == {"gp": 1, "avg": 0.2, "trend": None}


def test_hot_and_cold_runs(tmp_path):
    led = Ledger(LocalStore(tmp_path))
    hist = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.2, 1.1]
    for i, gs in enumerate(hist):
        led.add(_game(2026020010 + i, f"2026-10-{i + 1:02d}", {7: gs, 8: -gs}))
    tonight = _game(2026020099, "2026-10-20", {7: 1.0, 8: -1.0})
    ctx = led.context(tonight)
    assert ctx[7]["trend"] == "hot" and ctx[8]["trend"] == "cold"
    # one big night after a flat run is not a streak
    led2 = Ledger(LocalStore(tmp_path / "b"))
    for i in range(6):
        led2.add(_game(2026020010 + i, f"2026-10-{i + 1:02d}", {7: 0.0}))
    assert led2.context(_game(2026020099, "2026-10-20", {7: 3.0}))[7]["trend"] is None


def test_save_merges_other_runs(tmp_path):
    store = LocalStore(tmp_path)
    a, b = Ledger(store), Ledger(store)
    a.add(_game(2026020001, "2026-10-01", {7: 1.0}))
    a.save()
    b.add(_game(2026020002, "2026-10-02", {7: 2.0}))
    b.save()
    saved = json.loads(store.read("ledger.json"))
    assert set(saved["players"]["7"]["g"]) == {"2026020001", "2026020002"}
