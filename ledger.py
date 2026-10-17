"""Season store: one compact file per analysed game on the `state` branch
(games/{season}/{game_id}.json), written once. Everything season-long reads from it: the impact
slide's season averages and hot/cold runs, and the rookie, awards and fantasy posts.
"""
import json
import logging

from config import OUTPUT_DIR
from git_store import default_store

log = logging.getLogger("ledger")

RECENT_N = 5          # "recent form" window, tonight included
TREND_MIN_PRIOR = 5   # games before tonight needed before a hot/cold arrow is shown
TREND_DELTA = 0.4     # recent average this far from the season average = hot / cold

SK_FIELDS = ["team", "name", "pos", "gs", "G", "A", "A1", "PPP", "SOG", "HIT", "BLK", "PIM", "ixG",
             "iHD", "xGF5", "xGA5", "GF5", "GA5", "CF5", "CA5", "toi", "toi5", "toipp", "toish",
             "GV", "TK"]
GK_FIELDS = ["team", "name", "gs", "sa", "sv", "ga", "xga", "toi", "dec"]


def season_of(game_id):
    s = str(game_id)[:4]
    return f"{s}{int(s) + 1}"


def encode_game(game):
    teams = {}
    for side in ("away", "home"):
        t = game["teams"][side]
        teams[t["abbrev"]] = {"side": side, "gf": t["score"], "ga": t["opp_score"], "won": t["won"],
                              "otl": (not t["won"]) and game["outcome"] in ("OT", "SO"),
                              "xgf": t["xg"], "xgf5": t["xgf5"], "xga5": t["xga5"],
                              "cf5": t["cf5"], "ca5": t["ca5"], "toi5": t.get("toi5_s", 0)}
    for ab, t in teams.items():
        other = next(o for k, o in teams.items() if k != ab)
        t["xga"] = other["xgf"]
    sk = {}
    for p in game["players"]:
        vals = {"team": p["team_abbrev"], "name": p["name"], "pos": p["position"],
                "gs": p["game_score"], "G": p["G"], "A": p["A"], "A1": p.get("A1", 0),
                "PPP": p.get("PPP", 0), "SOG": p["SOG"], "HIT": p.get("hits", 0),
                "BLK": p.get("BLK", 0), "PIM": p.get("pim", 0), "ixG": p["ixG"],
                "iHD": p.get("iHD", 0), "xGF5": p["xGF"], "xGA5": p["xGA"],
                "GF5": p.get("GF5", 0), "GA5": p.get("GA5", 0), "CF5": p["CF"], "CA5": p["CA"],
                "toi": p.get("toi_s", 0), "toi5": p.get("toi5_s", 0), "toipp": p.get("toipp_s", 0),
                "toish": p.get("toish_s", 0), "GV": p.get("GV", 0), "TK": p.get("TK", 0)}
        sk[str(p["player_id"])] = [vals[f] for f in SK_FIELDS]
    gk = {}
    for g in game["goalies"]:
        vals = {"team": g["team_abbrev"], "name": g["name"], "gs": g["game_score"],
                "sa": g["shots_against"], "sv": g["saves"], "ga": g["goals_against"],
                "xga": g["xga"], "toi": _sec(g.get("toi")), "dec": g.get("decision")}
        gk[str(g["player_id"])] = [vals[f] for f in GK_FIELDS]
    ln = [[u["team"], u["kind"], u["players"], u.get("last") or u["names"], u["toi"], u["cf"], u["ca"],
           u["xgf"], u["xga"], u["gf"], u["ga"]] for u in game.get("lines", [])]
    return {"id": game["game_id"], "date": game["date"][:10], "outcome": game["outcome"],
            "teams": teams, "sk": sk, "gk": gk, "ln": ln}


def _sec(clock):
    try:
        m, s = str(clock).split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return 0


def skater_rows(rec):
    """Decoded skater lines of one stored game: {player_id: {field: value}}."""
    return {pid: dict(zip(SK_FIELDS, v)) for pid, v in rec["sk"].items()}


def goalie_rows(rec):
    return {pid: dict(zip(GK_FIELDS, v)) for pid, v in rec["gk"].items()}


class Ledger:
    def __init__(self, store=None):
        self.store = store or default_store("state", OUTPUT_DIR.parent / "state")
        self._games = {}       # season -> {game_id: record}
        self._pending = {}

    def games(self, season):
        if season not in self._games:
            files = self.store.read_dir(f"games/{season}")
            self._games[season] = {}
            for path, raw in files.items():
                try:
                    rec = json.loads(raw)
                    self._games[season][str(rec["id"])] = rec
                except (ValueError, KeyError):
                    log.warning("Unreadable %s", path)
        return self._games[season]

    def season_games(self, season, start=None, end=None):
        recs = self.games(season).values()
        return sorted((r for r in recs if (not start or r["date"] >= start) and (not end or r["date"] <= end)),
                      key=lambda r: (r["date"], r["id"]))

    # ---------------------------------------------------------------- writing ---
    def add(self, game):
        rec = encode_game(game)
        season = season_of(game["game_id"])
        self.games(season)[str(rec["id"])] = rec
        self._pending[f"games/{season}/{rec['id']}.json"] = json.dumps(rec, separators=(",", ":")).encode()

    def save(self, message="Update season store"):
        if self._pending:
            self.store.write(self._pending, message)
            self._pending = {}

    # ---------------------------------------------------------------- reading ---
    def history(self, season):
        """player_id -> [(date, game_id, game_score)] over the stored season."""
        out = {}
        for gid, rec in self.games(season).items():
            for pid, v in rec["sk"].items():
                out.setdefault(pid, []).append((rec["date"], gid, v[SK_FIELDS.index("gs")]))
            for pid, v in rec["gk"].items():
                out.setdefault(pid, []).append((rec["date"], gid, v[GK_FIELDS.index("gs")]))
        return out

    def context(self, game):
        """player_id -> {gp, avg, trend} using only games before this one."""
        out = {}
        hist = self.history(season_of(game["game_id"]))
        gid, day = str(game["game_id"]), game["date"][:10]
        for p in game["players"] + game["goalies"]:
            rows = hist.get(str(p["player_id"]))
            if not rows:
                continue
            prior = sorted(r for r in rows if r[1] != gid and (r[0], r[1]) < (day, gid))
            if not prior:
                continue
            scores = [g for _, _, g in prior]
            avg = sum(scores) / len(scores)
            trend = None
            if len(scores) >= TREND_MIN_PRIOR:
                recent = (scores + [p["game_score"]])[-RECENT_N:]
                delta = sum(recent) / len(recent) - avg
                above = sum(1 for g in recent if g > avg)
                # a streak, not one big night: most of the recent games on the same side
                if delta >= TREND_DELTA and above >= 3:
                    trend = "hot"
                elif delta <= -TREND_DELTA and len(recent) - above >= 3:
                    trend = "cold"
            out[p["player_id"]] = {"gp": len(scores), "avg": round(avg, 2), "trend": trend}
        return out
