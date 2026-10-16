"""Gather tracker + logo source data.

    python tools/tracker_data.py OUT_DIR [--goals]

Writes into OUT_DIR:
  logos/{ABBR}.svg                 dark-background team logos (all 32 teams)
  landing_{id}.json                NHL player landing (career totals) for Ovechkin and Crosby
  gamelog_{id}.json                every regular-season game of their careers
  leaders_points.json / leaders_goals.json   all-time regular-season leaders (top 60)
  ovi_goals.json  (--goals)        every Ovechkin regular-season goal: game, date, opponent,
                                   goalie scored on (None = empty net), strength, period
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import NHL_STATS_API, NHL_WEB_API  # noqa: E402
from metrics import TEAM_COLORS  # noqa: E402
from nhl_fetcher import LiveSource  # noqa: E402

OVI, CROSBY = 8471214, 8471675
FIRST_SEASON, LAST_SEASON = 2005, 2026
log = logging.getLogger("tracker_data")


def seasons():
    return [f"{y}{y + 1}" for y in range(FIRST_SEASON, LAST_SEASON + 1)]


def leaders(src, prop, limit=60):
    params = {"isAggregate": "true", "isGame": "false", "start": 0, "limit": limit,
              "sort": json.dumps([{"property": prop, "direction": "DESC"}]),
              "cayenneExp": f"gameTypeId=2 and seasonId>=19171918 and seasonId<={LAST_SEASON}{LAST_SEASON + 1}"}
    return src._get(f"{NHL_STATS_API}/skater/summary", params=params)


def gamelog(src, pid):
    games = []
    for s in seasons():
        try:
            games += src._get(f"{NHL_WEB_API}/player/{pid}/game-log/{s}/2").get("gameLog", [])
        except Exception as exc:
            log.warning("No game log for %s %s: %s", pid, s, exc)
    return games


def ovi_goals(src, games):
    out = []
    for g in games:
        if not g.get("goals"):
            continue
        gid = g["gameId"]
        try:
            pbp = src._get(f"{NHL_WEB_API}/gamecenter/{gid}/play-by-play")
        except Exception as exc:
            log.warning("No play-by-play for %s: %s", gid, exc)
            out += [{"game_id": gid, "date": g.get("gameDate"), "opp": g.get("opponentAbbrev"),
                     "goalie_id": "?", "missing": True}] * g["goals"]
            continue
        names = {r["playerId"]: f"{r['firstName']['default']} {r['lastName']['default']}"
                 for r in pbp.get("rosterSpots", [])}
        found = 0
        for p in pbp.get("plays", []):
            d = p.get("details") or {}
            if p.get("typeDescKey") != "goal" or d.get("scoringPlayerId") != OVI:
                continue
            if (p.get("periodDescriptor") or {}).get("periodType") == "SO":
                continue
            gk = d.get("goalieInNetId")
            out.append({"game_id": gid, "date": g.get("gameDate"), "opp": g.get("opponentAbbrev"),
                        "goalie_id": gk, "goalie": names.get(gk), "situation": p.get("situationCode"),
                        "period": (p.get("periodDescriptor") or {}).get("number"),
                        "home": g.get("homeRoadFlag") == "H"})
            found += 1
        for _ in range(g["goals"] - found):  # feed missing the goal events
            out.append({"game_id": gid, "date": g.get("gameDate"), "opp": g.get("opponentAbbrev"),
                        "goalie_id": "?", "missing": True})
        time.sleep(0.05)
    return out


def main(out, with_goals=False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = Path(out)
    (out / "logos").mkdir(parents=True, exist_ok=True)
    src = LiveSource()
    for ab in TEAM_COLORS:
        try:
            r = src.session.get(f"https://assets.nhle.com/logos/nhl/svg/{ab}_dark.svg", timeout=15)
            r.raise_for_status()
            (out / "logos" / f"{ab}.svg").write_bytes(r.content)
        except Exception as exc:
            log.warning("Logo %s: %s", ab, exc)
    logs = {}
    for pid in (OVI, CROSBY):
        (out / f"landing_{pid}.json").write_text(json.dumps(src._get(f"{NHL_WEB_API}/player/{pid}/landing")))
        logs[pid] = gamelog(src, pid)
        (out / f"gamelog_{pid}.json").write_text(json.dumps(logs[pid]))
    for prop in ("points", "goals"):
        (out / f"leaders_{prop}.json").write_text(json.dumps(leaders(src, prop)))
    if with_goals:
        goals = ovi_goals(src, logs[OVI])
        (out / "ovi_goals.json").write_text(json.dumps(goals))
        log.info("Ovechkin goals found: %d (%d missing a goalie record)", len(goals),
                 sum(1 for g in goals if g.get("missing")))


if __name__ == "__main__":
    main(sys.argv[1], "--goals" in sys.argv)
