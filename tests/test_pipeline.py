"""End-to-end tests on two real games (Oct 15, 2026: STL @ MIN and NYI @ OTT, shootout)."""
import copy
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cards  # noqa: E402
import content_generator  # noqa: E402
import pipeline  # noqa: E402
import publisher  # noqa: E402
from git_store import LocalStore  # noqa: E402
from metrics import aggregate_week, analyze_game  # noqa: E402
from nhl_fetcher import load_game  # noqa: E402

DATA = Path(__file__).parent / "data"
MIN_GAME, SO_GAME = 2026020116, 2026020109


def _load(gid, kind):
    with gzip.open(DATA / f"{gid}_{kind}.json.gz", "rt") as f:
        return json.load(f)


class FakeSource:
    """Serves the real games; their state and shift availability can be changed mid-test."""

    def __init__(self):
        self.score_data = json.loads((DATA / "score.json").read_text())
        self.states = {g["id"]: g["gameState"] for g in self.score_data["games"]}
        self.shifts_ready = {g["id"]: True for g in self.score_data["games"]}
        self.fail = set()

    def score(self, day):
        if day != "2026-10-15":
            return {"games": []}
        games = copy.deepcopy(self.score_data["games"])
        for g in games:
            g["gameState"] = self.states[g["id"]]
        return {"games": games}

    def boxscore(self, gid):
        if gid in self.fail:
            raise RuntimeError("boom")
        return _load(gid, "boxscore")

    def play_by_play(self, gid):
        return _load(gid, "play-by-play")

    def shifts(self, gid):
        return _load(gid, "shifts")["data"] if self.shifts_ready[gid] else []


class Clock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cards, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(publisher, "_preview_store", LocalStore(tmp_path / "previews"))
    monkeypatch.setattr(pipeline, "generate_game_copy", content_generator.fallback_game_copy)
    # animations are tested in test_animations.py; here a placeholder file keeps tests fast
    import reels

    def fake_video(*a, **k):
        p = tmp_path / "out" / f"stub_{len(list((tmp_path / 'out').glob('stub_*')))}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"mp4")
        return p
    for name in ("render_game_replay", "render_ovi_goal", "render_crosby_climb", "render_spotlight"):
        monkeypatch.setattr(reels.A, name, fake_video)
    state = pipeline.State(LocalStore(tmp_path / "state"))
    # 11:30pm ET on Oct 15 -> slate is Oct 15
    clock = Clock(datetime(2026, 10, 16, 3, 30, tzinfo=timezone.utc))
    return FakeSource(), state, clock, tmp_path


def test_analysis_matches_official_box_score():
    src = FakeSource()
    g = next(x for x in src.score("2026-10-15")["games"] if x["id"] == MIN_GAME)
    game = analyze_game(load_game(src, g))
    box = _load(MIN_GAME, "boxscore")
    assert game["teams"]["away"]["goals"] == 4 and game["teams"]["home"]["goals"] == 5
    assert game["teams"]["home"]["sog"] == box["homeTeam"]["sog"]
    saves = {gl["name"]: gl["saves"] for gl in game["goalies"]}
    for side in ("awayTeam", "homeTeam"):
        for bg in box["playerByGameStats"][side]["goalies"]:
            if bg["toi"] != "00:00":
                assert bg["saves"] in saves.values()
    assert len(game["stars"]) == 3
    assert game["timeline"] and all(e["xg"] >= 0 for e in game["timeline"])


def test_live_posts_when_final_and_stops(env):
    src, state, clock, tmp = env
    src.states = {MIN_GAME: "LIVE", SO_GAME: "OFF"}
    calls = {"n": 0}

    def sleep(sec):
        clock.sleep(sec)
        calls["n"] += 1
        if calls["n"] == 3:
            src.states[MIN_GAME] = "FINAL"  # horn sounds during the 3rd wait

    pipeline.run_live(src, state, now=clock.now, sleep=sleep, poll=120)
    assert state.done("games", SO_GAME) and state.done("games", MIN_GAME)
    assert calls["n"] == 3  # posted on the very next poll after going final, then exited
    index = json.loads((tmp / "previews" / "index.json").read_text())
    # both games, then the night's Reels once everything on the slate is final
    assert {e["key"] for e in index} == {f"game-{MIN_GAME}", f"game-{SO_GAME}",
                                         "gotn-2026-10-15", "spot-2026-10-15"}
    games = [e for e in index if e["key"].startswith("game-")]
    assert all(len(e["files"]) == 7 for e in games)  # cover, replay video, game, 2x team, 2x impact
    assert state.data["reels"]["gotn-2026-10-15"]["mode"] == "preview"


def test_live_waits_for_shift_data_then_gives_up_waiting(env):
    src, state, clock, _ = env
    src.states = {MIN_GAME: "FINAL", SO_GAME: "OFF"}
    state.record("games", SO_GAME, {"title": "done"})
    src.shifts_ready[MIN_GAME] = False
    pipeline.run_live(src, state, now=clock.now, sleep=clock.sleep, poll=120, shift_wait=360)
    assert state.done("games", MIN_GAME)
    # waited for shift data (3 polls) before posting without it
    assert clock.now() - datetime(2026, 10, 16, 3, 30, tzinfo=timezone.utc) == timedelta(seconds=360)


def test_live_never_reposts_and_exits_when_idle(env):
    src, state, clock, _ = env
    src.states = {MIN_GAME: "OFF", SO_GAME: "OFF"}
    pipeline.run_live(src, state, now=clock.now, sleep=clock.sleep)
    first = dict(state.data["games"])
    pipeline.run_live(src, state, now=clock.now, sleep=clock.sleep)
    assert state.data["games"] == first


def test_live_gives_up_after_repeated_failures(env):
    src, state, clock, _ = env
    src.states = {MIN_GAME: "OFF", SO_GAME: "OFF"}
    state.record("games", SO_GAME, {"title": "done"})
    src.fail.add(MIN_GAME)
    gave_up = pipeline.run_live(src, state, now=clock.now, sleep=clock.sleep, poll=60)
    assert gave_up == [MIN_GAME] and not state.done("games", MIN_GAME)


def test_slate_includes_last_night_after_midnight():
    et = pipeline.ET
    late = datetime(2026, 10, 16, 0, 45, tzinfo=et)
    assert [d.isoformat() for d in pipeline.slate_dates(late)] == ["2026-10-15", "2026-10-16"]
    evening = datetime(2026, 10, 16, 19, 0, tzinfo=et)
    assert [d.isoformat() for d in pipeline.slate_dates(evening)] == ["2026-10-16"]


def test_last_completed_week():
    from datetime import date
    start, end = pipeline.last_completed_week(date(2026, 10, 19))  # a Monday
    assert (start.isoformat(), end.isoformat()) == ("2026-10-12", "2026-10-18")


def test_weekly_aggregation_and_render(env):
    src, state, clock, tmp = env
    games = [analyze_game(load_game(src, g)) for g in src.score("2026-10-15")["games"]]
    week = aggregate_week(games, "2026-10-12", "2026-10-18", min_gp=1, top_n=3)
    top = week["players_top"]
    assert top == sorted(top, key=lambda p: p["game_score"], reverse=True)
    assert week["teams_top"][0]["xg5_pct"] >= week["teams_bottom"][0]["xg5_pct"]
    assert all(t["record"].count("-") == 2 for t in week["teams_top"])
    paths = cards.render_weekly_carousel(week)
    assert len(paths) == 5 and all(p.exists() for p in paths)
