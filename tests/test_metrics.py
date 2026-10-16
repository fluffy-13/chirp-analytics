import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content_generator import _numbers, _valid  # noqa: E402
import xg_model  # noqa: E402
from metrics import goalie_pulled, shot_geometry, strength  # noqa: E402


def test_geometry_uses_offensive_zone():
    dist, ang = shot_geometry(79, 0, "O", True, "right")  # zone code wins over side
    assert round(dist) == 10 and ang == 0


def test_geometry_uses_defending_side():
    # home defends left → attacks the right net (x=+89)
    dist, _ = shot_geometry(69, 0, None, True, "left")
    assert round(dist) == 20
    dist, _ = shot_geometry(-69, 0, None, False, "left")  # away attacks left
    assert round(dist) == 20


def xg(*a, **k):
    return xg_model.predict(xg_model.features(*a, **k))


def test_trained_model_is_loaded():
    assert xg_model.load_model().get("type") == "gbm"


def test_xg_sane():
    assert xg(10, 0) > xg(30, 0) > xg(60, 0)
    reb = dict(rebound=True, dt=1, prev_type="SHOT", same_team_prev=True)
    # a rebound is dangerous when the puck moves across the crease, not when it sits still
    assert xg(8, 5, rebound_dy=10, **reb) > xg(8, 5, rebound_dy=0, **reb)
    assert 0.08 < xg(10, 0) < 0.4      # point-blank wrister
    assert xg(60, 30) < 0.03           # long-range, sharp angle


def test_strength_from_situation_code():
    assert strength("1451", shooter_is_home=True) == "PP"   # home 5 vs away 4
    assert strength("1451", shooter_is_home=False) == "SH"
    assert strength("1551", shooter_is_home=True) == "EV"


def test_empty_net_detection():
    assert goalie_pulled("0651", shooter_is_home=True)
    assert not goalie_pulled("1551", shooter_is_home=True)


def test_rejects_invented_numbers():
    allowed = _numbers("ixG 1.42, 9 shot attempts")
    assert _valid({"hook": "1.42 xG", "caption": "9 attempts #Top10"}, allowed) is None
    assert "numbers" in _valid({"hook": "1.42 xG", "caption": "best in 12 games"}, allowed)
    assert "claim" in _valid({"hook": "1.42 xG", "caption": "Top 9 game of the season"}, allowed)


def test_gemini_skips_retired_models(monkeypatch):
    import content_generator as cg
    from google import genai
    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model != "gemini-3.6-flash":
                raise RuntimeError("404 NOT_FOUND" if model != "gemini-flash-latest"
                                   else "503 UNAVAILABLE high demand")
            return type("R", (), {"text": '{"hook": "h", "caption": "c", "hashtags": []}'})()

    monkeypatch.setattr(genai, "Client", lambda api_key: type("C", (), {"models": FakeModels()})())
    monkeypatch.setattr(cg, "GEMINI_MODEL", None)
    monkeypatch.setattr(cg, "_working_model", None)
    assert cg._call_gemini("p")["hook"] == "h"
    assert calls == ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.6-flash"]
    calls.clear()
    cg._call_gemini("p")
    assert calls[0] == "gemini-3.6-flash"  # tries the last working model first
