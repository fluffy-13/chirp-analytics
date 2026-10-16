"""Season-to-date research: aggregate every regular-season game between two dates.

  python tools/season_report.py 2026-09-25 2026-10-16 out.json
Writes players, goalies, teams and notable single games for storyline hunting.
"""
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrics import analyze_game  # noqa: E402
from nhl_fetcher import FINAL_STATES, LiveSource, load_game  # noqa: E402


def main():
    start, end, out = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]), sys.argv[3]
    src = LiveSource()
    games, d = [], start
    while d <= end:
        for g in src.score(d.isoformat()).get("games", []):
            if g.get("gameType") == 2 and g.get("gameState") in FINAL_STATES:
                try:
                    games.append(analyze_game(load_game(src, g)))
                except Exception as exc:
                    print("skip", g["id"], exc)
        d += timedelta(days=1)
    print("games", len(games))

    P = defaultdict(lambda: defaultdict(float))
    G = defaultdict(lambda: defaultdict(float))
    T = defaultdict(lambda: defaultdict(float))
    notable = []
    for g in games:
        for p in g["players"]:
            r = P[p["player_id"]]
            r.update(name=p["name"], team=p["team_abbrev"], pos=p["position"])
            r["gp"] += 1
            for k in ("G", "A", "SOG", "iCF", "iHD", "ixG", "CF", "CA", "xGF", "xGA", "game_score"):
                r[k] += p[k]
        for gl in g["goalies"]:
            r = G[gl["player_id"]]
            r.update(name=gl["name"], team=gl["team_abbrev"])
            r["gp"] += 1
            for k in ("saves", "shots_against", "goals_against", "xga", "gsax"):
                r[k] += gl[k]
        for side in ("away", "home"):
            t, o = g["teams"][side], g["teams"]["home" if side == "away" else "away"]
            r = T[t["abbrev"]]
            r.update(name=t["name"])
            r["gp"] += 1
            r["w"] += t["won"]
            r["otl"] += (not t["won"]) and g["outcome"] in ("OT", "SO")
            r["gf"] += t["goals"]
            r["ga"] += o["goals"]
            r["xgf"] += t["xg"]
            r["xga"] += o["xg"]
            for k in ("xgf5", "xga5", "cf5", "ca5", "sog", "hd", "pp_goals", "pp_opps"):
                r[k] += t[k]
            r["sog_against"] += o["sog"]
            r["hd_against"] += o["hd"]
            r["pk_ga"] += o["pp_goals"]
            r["pk_opps"] += o["pp_opps"]
        a, h = g["teams"]["away"], g["teams"]["home"]
        winner, loser = (a, h) if a["won"] else (h, a)
        notable.append({"game_id": g["game_id"], "date": g["date"], "matchup": g["matchup"],
                        "winner": winner["abbrev"], "winner_xg": winner["xg"], "loser_xg": loser["xg"],
                        "xg_gap": round(loser["xg"] - winner["xg"], 2),
                        "total_xg": round(a["xg"] + h["xg"], 2),
                        "stars": [(s["name"], s["team_abbrev"], s["game_score"]) for s in g["stars"]]})

    def fin(d_):
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d_.items()}

    players = [fin({**r, "gax": r["G"] - r["ixG"]}) for r in P.values()]
    goalies = [fin({**r, "sv_pct": r["saves"] / r["shots_against"] if r["shots_against"] else None})
               for r in G.values()]
    teams = []
    for ab, r in T.items():
        sh = r["gf"] / r["sog"] if r["sog"] else 0
        sv = 1 - r["ga"] / r["sog_against"] if r["sog_against"] else 0
        teams.append(fin({**r, "abbrev": ab, "l": r["gp"] - r["w"] - r["otl"],
                          "xg5_pct": 100 * r["xgf5"] / (r["xgf5"] + r["xga5"]) if r["xgf5"] + r["xga5"] else None,
                          "cf5_pct": 100 * r["cf5"] / (r["cf5"] + r["ca5"]) if r["cf5"] + r["ca5"] else None,
                          "goal_diff": r["gf"] - r["ga"], "xg_diff": r["xgf"] - r["xga"],
                          "luck": (r["gf"] - r["ga"]) - (r["xgf"] - r["xga"]),
                          "sh_pct": 100 * sh, "sv_pct": 100 * sv, "pdo": 100 * (sh + sv)}))
    Path(out).write_text(json.dumps({"start": str(start), "end": str(end), "games": len(games),
                                     "players": players, "goalies": goalies, "teams": teams,
                                     "notable": notable}, indent=0))


if __name__ == "__main__":
    main()
