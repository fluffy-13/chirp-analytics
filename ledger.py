"""Season ledger: every player's Game Score in every game, so a card can show tonight vs. his
season so far. Lives next to posted.json (the `state` branch in GitHub Actions).

Format: {"season": "20262027", "players": {player_id: {"n": name, "t": team, "pos": pos,
                                                        "g": {game_id: [date, game_score]}}}}
"""
import json
import logging

from config import OUTPUT_DIR
from git_store import default_store

log = logging.getLogger("ledger")

RECENT_N = 5          # "recent form" window, tonight included
TREND_MIN_PRIOR = 5   # games before tonight needed before a hot/cold arrow is shown
TREND_DELTA = 0.4     # recent average this far from the season average = hot / cold


def season_of(game_id):
    s = str(game_id)[:4]
    return f"{s}{int(s) + 1}"


class Ledger:
    FILE = "ledger.json"

    def __init__(self, store=None):
        self.store = store or default_store("state", OUTPUT_DIR.parent / "state")
        raw = self.store.read(self.FILE)
        self.data = json.loads(raw) if raw else {}
        self.data.setdefault("players", {})

    # ---------------------------------------------------------------- writing ---
    def add(self, game):
        """Record one analysed game (idempotent)."""
        season = season_of(game["game_id"])
        if self.data.get("season") not in (None, season):  # new season: start over
            self.data = {"season": season, "players": {}}
        self.data["season"] = season
        gid, day = str(game["game_id"]), game["date"][:10]
        for p in game["players"] + game["goalies"]:
            row = self.data["players"].setdefault(str(p["player_id"]), {"g": {}})
            row.update(n=p["name"], t=p["team_abbrev"], pos=p["position"])
            row["g"][gid] = [day, p["game_score"]]

    def refresh(self):
        """Merge in games another run recorded since we loaded."""
        raw = self.store.read(self.FILE)
        if not raw:
            return
        fresh = json.loads(raw)
        if fresh.get("season") != self.data.get("season") and self.data.get("season"):
            return
        for pid, row in fresh.get("players", {}).items():
            mine = self.data["players"].setdefault(pid, {**row, "g": {}})
            mine["g"] = {**row.get("g", {}), **mine["g"]}

    def save(self, message="Update ledger"):
        self.refresh()
        self.store.write({self.FILE: json.dumps(self.data, separators=(",", ":")).encode()},
                         message)

    # ---------------------------------------------------------------- reading ---
    def context(self, game):
        """player_id -> {gp, avg, trend} using only games before this one."""
        out = {}
        season = season_of(game["game_id"])
        if self.data.get("season") not in (None, season):
            return out
        gid, day = str(game["game_id"]), game["date"][:10]
        for p in game["players"] + game["goalies"]:
            row = self.data["players"].get(str(p["player_id"]))
            if not row:
                continue
            prior = sorted((d, g, k) for k, (d, g) in row["g"].items()
                           if k != gid and (d, k) < (day, gid))
            if not prior:
                continue
            scores = [g for _, g, _ in prior]
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
