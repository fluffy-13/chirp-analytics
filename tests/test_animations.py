import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import animations as A  # noqa: E402
import cards  # noqa: E402
from metrics import analyze_game  # noqa: E402
from nhl_fetcher import load_game  # noqa: E402
from test_pipeline import MIN_GAME, FakeSource  # noqa: E402


def _game():
    src = FakeSource()
    g = next(x for x in src.score("2026-10-15")["games"] if x["id"] == MIN_GAME)
    return analyze_game(load_game(src, g))


def _probe(path):
    out = subprocess.run([A._ffmpeg(), "-i", str(path)], capture_output=True, text=True).stderr
    return out


def test_replay_reel_and_slide_encode(tmp_path, monkeypatch):
    monkeypatch.setattr(cards, "OUTPUT_DIR", tmp_path)
    game = _game()
    slide = A.render_game_replay(game, "slide", seconds=1.0)
    reel = A.render_game_replay(game, "reel", seconds=1.0, headline="test")
    for path, size in ((slide, "1080x1350"), (reel, "1080x1920")):
        info = _probe(path)
        assert "h264" in info and size in info and "aac" in info


def test_spotlight_and_picker(tmp_path, monkeypatch):
    monkeypatch.setattr(cards, "OUTPUT_DIR", tmp_path)
    game = _game()
    g, p, why = A.spotlight_candidate([game])
    assert p["name"] == "Matt Boldy" and why == "hat trick"
    assert A.render_spotlight(game, p, why, seconds=1.0).exists()
    score, reason = A.drama(game)
    assert score > 0 and reason


def test_nightly_reels_wait_for_the_morning():
    from datetime import datetime, timezone
    import reels
    late_night = datetime(2026, 10, 17, 5, 30, tzinfo=timezone.utc)   # 1:30 AM ET
    assert reels.morning_after("2026-10-16", late_night) == "2026-10-17T15:30:00Z"  # 11:30 AM EDT
    after_noon = datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc)
    assert reels.morning_after("2026-10-16", after_noon) is None  # too late: post now
