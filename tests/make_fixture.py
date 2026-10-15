"""Builds a SYNTHETIC game in the NHL API's JSON shapes for offline testing.

Players are fictional; numbers are random. Never publish output made from this.
  python tests/make_fixture.py && python main.py --fixtures tests/fixtures --date 2026-10-14
"""
import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
GID = 2026029999
rng = random.Random(7)

TEAMS = {
    "away": {"id": 25, "abbrev": "DAL", "place": "Dallas", "common": "Stars"},
    "home": {"id": 21, "abbrev": "COL", "place": "Colorado", "common": "Avalanche"},
}
FIRST = ["Mika", "Jonas", "Theo", "Casey", "Rory", "Elias", "Nolan", "Anton", "Ville",
         "Owen", "Felix", "Luca", "Brody", "Kasper", "Reid", "Sami", "Tate", "Wes"]
LAST = ["Lindqvist", "Harrow", "Delacroix", "Brennan", "Kowal", "Mercer", "Sato", "Varga",
        "Holm", "Pryor", "Castell", "Durand", "Ekblad", "Fenwick", "Gallant", "Hale", "Ivers", "Juneau"]


def roster(team, base):
    players = []
    for i in range(12):
        players.append({"playerId": base + i, "pos": "CLR"[i % 3], "line": i // 3})
    for i in range(6):
        players.append({"playerId": base + 12 + i, "pos": "D", "line": i // 2})
    players.append({"playerId": base + 18, "pos": "G", "line": 0})
    for n, p in enumerate(players):
        p.update(teamId=team["id"], first=rng.choice(FIRST), last=rng.choice(LAST), num=n + 2)
    return players


rosters = {"away": roster(TEAMS["away"], 8_900_000), "home": roster(TEAMS["home"], 8_900_100)}
# make one home centre the star of the night
star = rosters["home"][0]
star.update(first="Mika", last="Lindqvist", num=29)

# shifts: forwards rotate every 45s, D every 50s
shifts = []
for side, players in rosters.items():
    for period in (1, 2, 3):
        for group, step, size in (("F", 45, 4), ("D", 50, 3)):
            pool = [p for p in players if (p["pos"] == "D") == (group == "D") and p["pos"] != "G"]
            t, line = 0, 0
            while t < 1200:
                end = min(t + step, 1200)
                for p in pool:
                    if p["line"] == line:
                        shifts.append({"playerId": p["playerId"], "teamId": p["teamId"], "period": period,
                                       "startTime": f"{t // 60:02d}:{t % 60:02d}",
                                       "endTime": f"{end // 60:02d}:{end % 60:02d}", "typeCode": 517})
                t, line = end, (line + 1) % size


def on_ice(side, period, sec):
    ids = {s["playerId"] for s in shifts
           if s["period"] == period and s["teamId"] == TEAMS[side]["id"]
           and int(s["startTime"][:2]) * 60 + int(s["startTime"][3:]) < sec
           <= int(s["endTime"][:2]) * 60 + int(s["endTime"][3:])}
    return [p for p in rosters[side] if p["playerId"] in ids]


plays, order = [], 0
score = {"away": 0, "home": 0}
for period in (1, 2, 3):
    side_def = "left" if period != 2 else "right"
    for _ in range(rng.randint(55, 75)):
        sec = rng.randint(5, 1195)
        side = "home" if rng.random() < 0.56 else "away"
        skaters = on_ice(side, period, sec)
        if not skaters:
            continue
        # the star shoots a lot when he is out there
        shooter = star if star in skaters and rng.random() < 0.45 else rng.choice(skaters)
        home_attacks_right = side_def == "left"
        attacks_right = home_attacks_right if side == "home" else not home_attacks_right
        net = 89 if attacks_right else -89
        dx = rng.choice([rng.uniform(6, 22), rng.uniform(20, 60)])
        x, y = round(net - dx if net > 0 else net + dx), round(rng.uniform(-30, 30))
        roll = rng.random()
        kind = ("blocked-shot" if roll < 0.25 else "missed-shot" if roll < 0.5
                else "goal" if roll < 0.5 + (0.09 if dx < 22 else 0.02) else "shot-on-goal")
        details = {"xCoord": x, "yCoord": y, "zoneCode": "O",
                   "shotType": rng.choice(["wrist", "snap", "slap", "backhand", "tip-in"]),
                   "eventOwnerTeamId": shooter["teamId"]}
        if kind == "goal":
            mates = [p for p in skaters if p is not shooter]
            details.update(scoringPlayerId=shooter["playerId"],
                           assist1PlayerId=mates[0]["playerId"] if mates else None,
                           assist2PlayerId=mates[1]["playerId"] if len(mates) > 1 else None)
            score[side] += 1
        else:
            details["shootingPlayerId"] = shooter["playerId"]
        if kind == "blocked-shot":
            other = "away" if side == "home" else "home"
            blockers = on_ice(other, period, sec)
            if blockers:
                details["blockingPlayerId"] = rng.choice(blockers)["playerId"]
        plays.append({"eventId": len(plays) + 1, "sortOrder": period * 10_000 + sec,
                      "periodDescriptor": {"number": period, "periodType": "REG"},
                      "timeInPeriod": f"{sec // 60:02d}:{sec % 60:02d}",
                      "situationCode": "1551" if rng.random() < 0.85 else "1451",
                      "homeTeamDefendingSide": side_def, "typeDescKey": kind, "details": details})


outcome = "REG"
if score["away"] == score["home"]:  # no ties in the NHL: settle it in a shootout
    score["home"] += 1
    outcome = "SO"


def team_obj(side):
    t = TEAMS[side]
    return {"id": t["id"], "abbrev": t["abbrev"], "commonName": {"default": t["common"]},
            "placeName": {"default": t["place"]}, "score": score[side]}


def box_players(side):
    out = {"forwards": [], "defense": [], "goalies": []}
    for p in rosters[side]:
        entry = {"playerId": p["playerId"], "sweaterNumber": p["num"],
                 "name": {"default": f"{p['first'][0]}. {p['last']}"}, "position": p["pos"],
                 "toi": f"{rng.randint(12, 23)}:{rng.randint(0, 59):02d}", "hits": rng.randint(0, 4)}
        out["goalies" if p["pos"] == "G" else "defense" if p["pos"] == "D" else "forwards"].append(entry)
    return out


OUT.mkdir(parents=True, exist_ok=True)
roster_spots = [{"playerId": p["playerId"], "teamId": p["teamId"], "firstName": {"default": p["first"]},
                 "lastName": {"default": p["last"]}, "sweaterNumber": p["num"], "positionCode": p["pos"]}
                for side in rosters for p in rosters[side]]
files = {
    "score.json": {"games": [{"id": GID, "gameType": 2, "gameState": "OFF",
                              "awayTeam": team_obj("away"), "homeTeam": team_obj("home"),
                              "gameOutcome": {"lastPeriodType": outcome}}]},
    f"{GID}_boxscore.json": {"id": GID, "gameDate": "2026-10-14", "awayTeam": team_obj("away"),
                             "homeTeam": team_obj("home"),
                             "playerByGameStats": {"awayTeam": box_players("away"),
                                                   "homeTeam": box_players("home")}},
    f"{GID}_play-by-play.json": {"id": GID, "awayTeam": team_obj("away"), "homeTeam": team_obj("home"),
                                 "rosterSpots": roster_spots, "plays": plays},
    f"{GID}_shifts.json": {"data": shifts},
}
for name, data in files.items():
    (OUT / name).write_text(json.dumps(data))
print(f"Wrote {len(files)} fixture files to {OUT} ({len(plays)} plays, final {score['away']}-{score['home']})")
