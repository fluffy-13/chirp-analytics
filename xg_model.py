"""Expected-goals model shared by training (tools/fit_xg.py) and the live bot (metrics.py).

`features()` is the single definition of what the model sees; training and live scoring both
call it, so a shot is scored exactly the way the model was trained. The fitted model is a
gradient-boosted tree ensemble exported to plain JSON (xg_model.json) and evaluated here in
pure Python, so the bot needs no ML library at runtime.
"""
import json
import logging
import math
from pathlib import Path

log = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parent / "xg_model.json"

SHOT_TYPES = ["snap", "slap", "backhand", "tip-in", "deflected", "wrap-around"]  # wrist = baseline
OTHER_SHOT_TYPES = {"bat", "poke", "between-legs", "cradle"}
PREV_TYPES = ["FACEOFF", "HIT", "GIVEAWAY", "TAKEAWAY", "BLOCKED_SHOT", "MISSED_SHOT", "SHOT"]
# NHL API typeDescKey → canonical event names used in training data
API_EVENT_NAMES = {"faceoff": "FACEOFF", "hit": "HIT", "giveaway": "GIVEAWAY",
                   "takeaway": "TAKEAWAY", "blocked-shot": "BLOCKED_SHOT",
                   "missed-shot": "MISSED_SHOT", "shot-on-goal": "SHOT", "goal": "GOAL"}
NO_PREV_DT = 60.0


def features(distance, angle, shot_type=None, rebound=False, rush=False, strength="EV",
             dt=None, prev_type=None, prev_dist=None, same_team_prev=False, rebound_dy=0.0):
    """Feature vector for one unblocked, non-empty-net attempt.

    distance, angle  feet / degrees (0–90) to the attacked net
    rebound          team's previous attempt was ≤3 s earlier in the same period
    rebound_dy       lateral (y) puck movement since that attempt, ft (0 if not a rebound)
    rush             previous event ≤4 s earlier was outside the shooter's offensive zone
    strength         "EV", "PP" (shooting team has more skaters) or "SH"
    dt               seconds since the previous event in the period (None → none yet)
    prev_type        canonical name of that event (FACEOFF, HIT, SHOT, ...)
    prev_dist        feet the puck travelled from that event to this shot
    same_team_prev   the previous event belonged to the shooting team
    """
    d = max(float(distance), 1.0)
    a = min(max(float(angle), 0.0), 90.0)
    t = NO_PREV_DT if dt is None or dt != dt else min(max(float(dt), 0.0), NO_PREV_DT)
    pd_ = 0.0 if prev_dist is None or prev_dist != prev_dist else float(prev_dist)
    st = shot_type.lower() if isinstance(shot_type, str) and shot_type else "wrist"
    f = {
        "distance": d,
        "log_distance": math.log(d),
        "angle": a,
        "dist_x_angle": d * a / 100.0,
        "rebound": float(bool(rebound)),
        "rebound_dy": float(rebound_dy) if rebound else 0.0,
        "rush": float(bool(rush)),
        "pp": float(strength == "PP"),
        "sh": float(strength == "SH"),
        "log_dt": math.log1p(t),
        "log_prev_dist": math.log1p(pd_),
        "speed": pd_ / (t + 1.0),
        "same_team_prev": float(bool(same_team_prev)),
    }
    for name in SHOT_TYPES:
        f[f"type_{name}"] = float(st == name)
    f["type_other"] = float(st in OTHER_SHOT_TYPES)
    for name in PREV_TYPES:
        f[f"prev_{name.lower()}"] = float(prev_type == name)
    return f


FEATURE_NAMES = list(features(10, 0).keys())

# Fallback only if xg_model.json is missing: the original hand-set weights. Known to
# overstate xG by ~50% on 2025-26 shots — do not publish numbers from it.
STARTER = {"type": "logistic", "intercept": 0.0,
           "coef": {"distance": -0.085, "angle": -0.012, "rebound": 0.85},
           "meta": {"name": "starter (uncalibrated)"}}


def load_model(path=MODEL_PATH):
    try:
        model = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        log.warning("xg_model.json not found; using the UNCALIBRATED starter model")
        return STARTER
    if model.get("type") == "gbm" and model.get("features") != FEATURE_NAMES:
        raise RuntimeError("xg_model.json was trained on a different feature set; refit it")
    return model


def _tree_value(tree, x):
    node = 0
    left, right = tree["left"], tree["right"]
    while left[node] != -1:
        node = left[node] if x[tree["feature"][node]] <= tree["threshold"][node] else right[node]
    return tree["value"][node]


def raw_score(feats, model):
    if model.get("type") == "gbm":
        x = [feats[name] for name in model["features"]]
        return model["init"] + model["learning_rate"] * sum(_tree_value(t, x) for t in model["trees"])
    return model["intercept"] + sum(model["coef"].get(k, 0.0) * v for k, v in feats.items())


_MODEL = None


def predict(feats, model=None):
    global _MODEL
    if model is None:
        if _MODEL is None:
            _MODEL = load_model()
        model = _MODEL
    return 1.0 / (1.0 + math.exp(-raw_score(feats, model)))
