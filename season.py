"""Season-long aggregates from the per-game store (ledger.py), for the rookie, awards and
fantasy posts.
"""
import json
import logging
import math
from collections import defaultdict

from config import NHL_STATS_API
from ledger import goalie_rows, skater_rows

log = logging.getLogger("season")

SUM_FIELDS = ["gs", "G", "A", "A1", "PPP", "SOG", "HIT", "BLK", "PIM", "ixG", "iHD", "xGF5", "xGA5",
              "GF5", "GA5", "CF5", "CA5", "toi", "toi5", "toipp", "toish", "GV", "TK"]


def skaters(records):
    """player_id -> season totals (+ team 5v5 context for the games he played)."""
    out = {}
    for rec in records:
        teams = rec["teams"]
        for pid, r in skater_rows(rec).items():
            a = out.setdefault(pid, defaultdict(float))
            a["id"] = pid
            a["name"], a["pos"], a["team"] = r["name"], r["pos"], r["team"]
            a["gp"] += 1
            for f in SUM_FIELDS:
                a[f] += r[f] or 0
            t = teams.get(r["team"], {})
            a["team_xga5"] += t.get("xga5", 0)
            a["team_xgf5"] += t.get("xgf5", 0)
            a["team_toi5"] += t.get("toi5", 0)
            a["last_date"] = rec["date"]
    for a in out.values():
        _derive(a)
    return out


def _derive(a):
    gp = max(a["gp"], 1)
    a["P"] = a["G"] + a["A"]
    a["xg_pm5"] = a["xGF5"] - a["xGA5"]
    a["toi_gp"] = a["toi"] / gp
    a["toipp_gp"] = a["toipp"] / gp
    tot = a["xGF5"] + a["xGA5"]
    a["xg5_pct"] = 100 * a["xGF5"] / tot if tot else None
    # 5v5 defence vs. the team without him: expected goals prevented while he was on the ice
    off_toi = a["team_toi5"] - a["toi5"]
    if a["toi5"] > 0 and off_toi > 0:
        on_rate = a["xGA5"] / a["toi5"]
        off_rate = (a["team_xga5"] - a["xGA5"]) / off_toi
        a["xga_prevented"] = (off_rate - on_rate) * a["toi5"]
        a["xga60_rel"] = (on_rate - off_rate) * 3600
    else:
        a["xga_prevented"], a["xga60_rel"] = 0.0, None
    a["is_d"] = a["pos"] == "D"


def goalies(records):
    out = {}
    for rec in records:
        for pid, r in goalie_rows(rec).items():
            a = out.setdefault(pid, defaultdict(float))
            a["id"], a["name"], a["team"] = pid, r["name"], r["team"]
            if r["toi"] <= 0:
                continue
            a["gp"] += 1
            for f in ("sa", "sv", "ga", "xga", "toi", "gs"):
                a[f] += r[f] or 0
            a["w"] += r["dec"] == "W"
    for a in out.values():
        a["gsax"] = a["xga"] - a["ga"]
        a["sv_pct"] = a["sv"] / a["sa"] if a["sa"] else None
    return {k: v for k, v in out.items() if v["gp"]}


def team_games(records):
    """team -> number of games played in these records."""
    n = defaultdict(int)
    for rec in records:
        for ab in rec["teams"]:
            n[ab] += 1
    return n


# --------------------------------------------------------------- rookies ---
def rookie_ids(source, season):
    """Calder-eligible player ids this season, from the NHL stats API (None if unavailable)."""
    ids = set()
    for kind in ("skater", "goalie"):
        start = 0
        while True:
            params = {"isAggregate": "false", "isGame": "false", "start": start, "limit": 100,
                      "sort": json.dumps([{"property": "playerId", "direction": "ASC"}]),
                      "cayenneExp": f"seasonId={season} and gameTypeId=2 and isRookie=1"}
            data = source._get(f"{NHL_STATS_API}/{kind}/summary", params=params)
            rows = data.get("data", [])
            ids.update(str(r["playerId"]) for r in rows)
            start += len(rows)
            if not rows or start >= data.get("total", 0):
                break
    return ids


# --------------------------------------------------------------- fantasy ---
CATS = ["G", "A", "PPP", "SOG", "HIT", "BLK"]


def category_values(players, min_gp=3):
    """Adds per-game category rates and a z-score total ('value') for players with min_gp."""
    pool = [p for p in players.values() if p["gp"] >= min_gp and p["pos"] != "G"]
    if len(pool) < 10:
        return pool
    stats = {}
    for c in CATS:
        rates = [p[c] / p["gp"] for p in pool]
        mu = sum(rates) / len(rates)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rates) / len(rates)) or 1
        stats[c] = (mu, sd)
    for p in pool:
        p["rates"] = {c: p[c] / p["gp"] for c in CATS}
        p["z"] = {c: (p["rates"][c] - stats[c][0]) / stats[c][1] for c in CATS}
        p["value"] = sum(p["z"].values())
    return pool
