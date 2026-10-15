"""Fit the xG model on real NHL shots and write xg_model.json.

Data: season play-by-play parquet files from the public sportsdataverse/fastRhockey-nhl-data
repo, nhl/pbp/parquet/play_by_play_<END_YEAR>.parquet (2026 = the 2025-26 season).

  # honest test: train on one season, score the next
  python tools/fit_xg.py --train play_by_play_2025.parquet --test play_by_play_2026.parquet
  # ship: refit on both seasons, keep the holdout report from a previous run in the JSON
  python tools/fit_xg.py --train play_by_play_2025.parquet play_by_play_2026.parquet --write

Requires: pandas, pyarrow, scikit-learn (training only — the bot itself doesn't need them).
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import log_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import xg_model  # noqa: E402

ATTEMPTS = ["GOAL", "SHOT", "MISSED_SHOT", "BLOCKED_SHOT"]
UNBLOCKED = ["GOAL", "SHOT", "MISSED_SHOT"]
COLS = ["game_id", "event_idx", "event_type", "secondary_type", "event_team_type", "period",
        "period_type", "period_seconds", "strength_state", "empty_net", "x_fixed", "y_fixed",
        "season", "xg", "x", "y"]
GBM_PARAMS = dict(n_estimators=300, max_depth=3, learning_rate=0.1, subsample=0.8,
                  min_samples_leaf=200, random_state=0)


def _strength(state):
    try:
        own, opp = (int(n) for n in str(state).split("v"))
    except ValueError:
        return "EV"
    return "PP" if own > opp else "SH" if own < opp else "EV"


def load_shots(path):
    """Unblocked, non-empty-net attempts with the raw inputs xg_model.features() needs.

    Mirrors metrics.analyze_game: previous-event context is per period, ignores line changes,
    and rebounds count the team's previous attempt of any kind (blocked included).
    """
    df = pd.read_parquet(path, columns=COLS)
    df = df[(df.period_type != "SHOOTOUT") & (df.event_type != "CHANGE")]
    df = df.sort_values(["game_id", "period", "period_seconds", "event_idx"]).reset_index(drop=True)

    # The feed credits a blocked shot to the blocking team; credit it to the shooting team
    flip = {"home": "away", "away": "home"}
    df["team"] = np.where(df.event_type == "BLOCKED_SHOT",
                          df.event_team_type.map(flip), df.event_team_type)

    g = df.groupby(["game_id", "period"])
    df["prev_type"] = g.event_type.shift()
    df["prev_sec"] = g.period_seconds.shift()
    # Relational features use RAW x/y: one consistent frame per period, like the live feed.
    # (x_fixed/y_fixed are flipped per event, so cross-event distances in them are wrong.)
    df["prev_x"] = g.x.shift()
    df["prev_y"] = g.y.shift()
    df["prev_team"] = g.team.shift()

    att = df[df.event_type.isin(ATTEMPTS) & df.team.isin(["home", "away"])].copy()
    ag = att.groupby(["game_id", "period", "team"])
    att["dt_att"] = att.period_seconds - ag.period_seconds.shift()
    att["prev_att_y"] = ag.y.shift()

    s = att[att.event_type.isin(UNBLOCKED) & ~att.empty_net.fillna(False).astype(bool)]
    s = s.dropna(subset=["x_fixed", "y_fixed", "x", "y"]).copy()
    toward = np.where(s.event_team_type == "home", 1.0, -1.0)  # x_fixed: home shots attack +x
    dx = np.abs(toward * 89.0 - s.x_fixed)
    # attacking direction in the raw frame: undo this shot's own raw→fixed flip
    flip = np.where((s.x != 0) & (s.x_fixed != 0), np.sign(s.x) * np.sign(s.x_fixed), np.nan)
    raw_dir = np.where(np.isnan(flip), np.sign(s.x).replace(0, 1), toward * flip)
    s["distance"] = np.hypot(dx, s.y_fixed)
    s["angle"] = np.degrees(np.arctan2(np.abs(s.y_fixed), dx))
    s["dt"] = s.period_seconds - s.prev_sec
    s["prev_dist"] = np.hypot(s.x - s.prev_x, s.y - s.prev_y)
    s["rebound"] = s.dt_att.between(0, 3)
    s["rebound_dy"] = np.abs(s.y - s.prev_att_y).fillna(0.0)
    s["rush"] = s.dt.between(0, 4) & (s.prev_x * raw_dir < 25)
    s["same_team_prev"] = s.prev_team == s.team
    s["strength"] = s.strength_state.map(_strength).fillna("EV")
    s["goal"] = (s.event_type == "GOAL").astype(int)
    return s


def design(shots):
    rows = [xg_model.features(
        r.distance, r.angle, r.secondary_type, r.rebound, r.rush, r.strength,
        dt=None if pd.isna(r.dt) else r.dt,
        prev_type=r.prev_type if isinstance(r.prev_type, str) else None,
        prev_dist=None if pd.isna(r.prev_dist) else r.prev_dist,
        same_team_prev=bool(r.same_team_prev), rebound_dy=r.rebound_dy,
    ) for r in shots.itertuples()]
    return pd.DataFrame(rows, columns=xg_model.FEATURE_NAMES)


def export(clf):
    prior = float(clf.init_.class_prior_[1])
    trees = []
    for est in clf.estimators_[:, 0]:
        t = est.tree_
        trees.append({"feature": t.feature.tolist(), "threshold": t.threshold.tolist(),
                      "left": t.children_left.tolist(), "right": t.children_right.tolist(),
                      "value": t.value[:, 0, 0].tolist()})
    return {"type": "gbm", "features": xg_model.FEATURE_NAMES,
            "init": float(np.log(prior / (1 - prior))),
            "learning_rate": clf.learning_rate, "trees": trees}


def report(name, y, p):
    bins = np.array_split(np.argsort(p), 10)
    return {"model": name, "shots": int(len(y)), "goals": int(y.sum()),
            "log_loss": round(float(log_loss(y, p)), 4),
            "auc": round(float(roc_auc_score(y, p)), 4),
            "xg_per_goal": round(float(p.sum() / y.sum()), 3),
            "calibration_deciles_pred_vs_actual": [
                [round(float(p[b].mean()), 4), round(float(y[b].mean()), 4)] for b in bins]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", nargs="+", required=True)
    ap.add_argument("--test")
    ap.add_argument("--write", action="store_true", help="write xg_model.json")
    args = ap.parse_args()

    train = pd.concat([load_shots(p) for p in args.train], ignore_index=True)
    Xtr, ytr = design(train), train.goal.values
    print(f"train: {len(train):,} unblocked shots, {int(ytr.sum()):,} goals ({ytr.mean():.2%})")
    t0 = time.time()
    clf = GradientBoostingClassifier(**GBM_PARAMS).fit(Xtr, ytr)
    model = export(clf)
    print(f"fit {len(model['trees'])} trees in {time.time() - t0:.0f}s")

    # parity: the pure-Python evaluator must reproduce sklearn exactly
    sample = Xtr.sample(2000, random_state=1)
    ours = np.array([xg_model.predict(dict(zip(xg_model.FEATURE_NAMES, row)), model)
                     for row in sample.values])
    gap = float(np.max(np.abs(ours - clf.predict_proba(sample)[:, 1])))
    print(f"exported-model parity: max |diff| = {gap:.2e}")
    assert gap < 1e-9, "exported model disagrees with sklearn"

    holdout = None
    if args.test:
        test = load_shots(args.test)
        Xte, yte = design(test), test.goal.values
        holdout = [report("gbm xG (this fit)", yte, clf.predict_proba(Xte)[:, 1]),
                   report("old starter model", yte,
                          np.array([xg_model.predict(dict(zip(xg_model.FEATURE_NAMES, r)),
                                                     xg_model.STARTER) for r in Xte.values]))]
        bench = test.xg.notna().values
        if bench.mean() > 0.95:
            holdout.append(report("dataset's published xG (benchmark)", yte[bench],
                                  test.xg.values[bench].clip(1e-4, 1 - 1e-4)))
        print(json.dumps(holdout, indent=1))
        (ROOT / "tools" / "holdout_report.json").write_text(json.dumps(
            {"train": [Path(p).name for p in args.train], "test": Path(args.test).name,
             "results": holdout}, indent=1))

    if args.write:
        prior_report = ROOT / "tools" / "holdout_report.json"
        model["meta"] = {
            "name": "gradient-boosted xG v1",
            "fitted": date.today().isoformat(),
            "train_files": [Path(p).name for p in args.train],
            "train_shots": int(len(train)), "train_goals": int(ytr.sum()),
            "params": GBM_PARAMS,
            "holdout": holdout or (json.loads(prior_report.read_text()) if prior_report.exists() else None),
        }
        xg_model.MODEL_PATH.write_text(json.dumps(model, separators=(",", ":")))
        print(f"wrote {xg_model.MODEL_PATH} ({xg_model.MODEL_PATH.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
