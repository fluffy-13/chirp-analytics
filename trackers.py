"""Player tracker slides added to a team's game posts.

  WSH games: Ovechkin's farewell tour — career goals, milestones, record of the night, goals vs.
             tonight's opponent, goalies he's scored on, final visits and games left.
  PIT games: Crosby's all-time points chase — the ladder of names around him and his pace.

Each tracked player has a career log on the `state` branch (trackers/{player_id}.json): every
regular-season game with opponent, goals, assists, PP/GW/OT goals and (Ovechkin) the goalies he
scored on. Each post tops it up from the NHL game log (self-healing for any missed night) and adds
tonight's game from the play-by-play. Nothing here may break a game post: any failure means the
tracker slide is skipped.
"""
import json
import logging
from datetime import date as Date

import logos
from cards import (BAD, GOOD, H, M, W, C, F, _canvas, _ellipsize, _fit, _footer, _header,
                   _panel, _pretty_date)
from config import NHL_STATS_API, NHL_WEB_API, OUTPUT_DIR
from git_store import default_store
from metrics import strength

log = logging.getLogger("trackers")

OVI, CROSBY = 8471214, 8471675
TRACKED = {OVI: "WSH", CROSBY: "PIT"}
FRANCHISE = {"ATL": "WPG", "PHX": "ARI"}   # relocated franchises count as one opponent
CITY = {"ANA": "Anaheim", "BOS": "Boston", "BUF": "Buffalo", "CAR": "Raleigh", "CBJ": "Columbus",
        "CGY": "Calgary", "CHI": "Chicago", "COL": "Denver", "DAL": "Dallas", "DET": "Detroit",
        "EDM": "Edmonton", "FLA": "Sunrise", "LAK": "Los Angeles", "MIN": "St. Paul",
        "MTL": "Montréal", "NJD": "Newark", "NSH": "Nashville", "NYI": "Long Island",
        "NYR": "New York", "OTT": "Ottawa", "PHI": "Philadelphia", "PIT": "Pittsburgh",
        "SEA": "Seattle", "SJS": "San Jose", "STL": "St. Louis", "TBL": "Tampa",
        "TOR": "Toronto", "UTA": "Salt Lake City", "VAN": "Vancouver", "VGK": "Las Vegas",
        "WPG": "Winnipeg", "WSH": "Washington"}


def season_of(game_id):
    s = str(game_id)[:4]
    return f"{s}{int(s) + 1}"


def _store():
    return default_store("state", OUTPUT_DIR.parent / "state")


# ------------------------------------------------------------- career logs ---
class CareerLog:
    def __init__(self, pid, store=None):
        self.pid = pid
        self.store = store or _store()
        self.path = f"trackers/{pid}.json"
        raw = self.store.read(self.path)
        self.data = json.loads(raw) if raw else {"games": {}, "goalies": {}}

    @property
    def games(self):
        return self.data["games"]

    def add_from_gamelog(self, entry, goalies=None):
        gid = str(entry["gameId"])
        row = {"d": entry["gameDate"], "opp": entry["opponentAbbrev"],
               "home": entry.get("homeRoadFlag") == "H",
               "g": entry.get("goals", 0), "a": entry.get("assists", 0),
               "ppg": entry.get("powerPlayGoals", 0), "gwg": entry.get("gameWinningGoals", 0),
               "otg": entry.get("otGoals", 0), "s": entry.get("shots", 0)}
        if goalies is not None:
            row["gk"] = goalies
        elif gid in self.games and "gk" in self.games[gid]:
            row["gk"] = self.games[gid]["gk"]
        self.games[gid] = row

    def save(self, message):
        raw = self.store.read(self.path)
        if raw:  # keep anything another run added
            fresh = json.loads(raw)
            self.data["games"] = {**fresh.get("games", {}), **self.data["games"]}
            self.data["goalies"] = {**fresh.get("goalies", {}), **self.data["goalies"]}
        self.store.write({self.path: json.dumps(self.data, separators=(",", ":")).encode()}, message)

    def totals(self, before=None):
        rows = [r for gid, r in self.games.items() if not before or (r["d"], gid) < before]
        t = {k: sum(r.get(k, 0) for r in rows) for k in ("g", "a", "ppg", "gwg", "otg", "s")}
        t["gp"] = len(rows)
        t["p"] = t["g"] + t["a"]
        return t


def goal_events(pbp, pid):
    """This player's non-shootout goals in a play-by-play: goalie, PP, OT, game-winner."""
    home_id = pbp["homeTeam"]["id"]
    team_of = {r["playerId"]: r.get("teamId") for r in pbp.get("rosterSpots", [])}
    names = {r["playerId"]: f"{r['firstName']['default']} {r['lastName']['default']}"
             for r in pbp.get("rosterSpots", [])}
    team = team_of.get(pid)
    tally = {home_id: 0, pbp["awayTeam"]["id"]: 0}
    out = []
    for p in sorted(pbp.get("plays", []), key=lambda p: p.get("sortOrder", 0)):
        if p.get("typeDescKey") != "goal":
            continue
        pd = p.get("periodDescriptor") or {}
        if pd.get("periodType") == "SO":
            continue
        d = p.get("details") or {}
        scorer_team = d.get("eventOwnerTeamId") or team_of.get(d.get("scoringPlayerId"))
        if scorer_team in tally:
            tally[scorer_team] += 1
        if d.get("scoringPlayerId") != pid:
            continue
        gk = d.get("goalieInNetId")
        out.append({"goalie": gk, "goalie_name": names.get(gk),
                    "pp": strength(p.get("situationCode", ""), team == home_id) == "PP",
                    "ot": (pd.get("number") or 0) > 3, "team_goal_no": tally.get(scorer_team, 0)})
    return out


def tonight_row(game, bundle, pid):
    """Tonight's line for a tracked player from our own analysis, or None if he didn't play."""
    p = next((x for x in game["players"] if x["player_id"] == pid), None)
    if not p:
        return None
    side = p["team_side"]
    me, opp = game["teams"][side], game["teams"]["home" if side == "away" else "away"]
    ev = goal_events(bundle["pbp"], pid)
    gwg = 0
    if me["won"] and game["outcome"] != "SO":
        gwg = sum(1 for e in ev if e["team_goal_no"] == opp["score"] + 1)
    return {"d": game["date"][:10], "opp": opp["abbrev"], "home": me["is_home"],
            "g": p["G"], "a": p["A"], "ppg": sum(e["pp"] for e in ev), "gwg": gwg,
            "otg": sum(e["ot"] for e in ev), "s": p["SOG"],
            "gk": [e["goalie"] for e in ev], "_goalie_names": {e["goalie"]: e["goalie_name"] for e in ev
                                                                if e["goalie"]}}


MIN_HISTORY = 500  # games; below this the career log wasn't seeded, so don't show "career" numbers


def sync(source, clog, season, tonight_gid, fetch_goalies=False):
    """Top up the career log from this season's NHL game log (fixes any missed nights)."""
    if len(clog.games) < MIN_HISTORY:
        raise RuntimeError(f"career log for {clog.pid} not seeded (run tools/backfill_trackers.py)")
    entries = source._get(f"{NHL_WEB_API}/player/{clog.pid}/game-log/{season}/2").get("gameLog", [])
    for e in entries:
        gid = str(e["gameId"])
        if gid == str(tonight_gid):
            continue
        have = clog.games.get(gid)
        goalies = None
        if fetch_goalies and e.get("goals") and not (have and "gk" in have):
            try:
                pbp = source._get(f"{NHL_WEB_API}/gamecenter/{gid}/play-by-play")
                ev = goal_events(pbp, clog.pid)
                goalies = [x["goalie"] for x in ev]
                for x in ev:
                    if x["goalie"]:
                        clog.data["goalies"][str(x["goalie"])] = x["goalie_name"]
            except Exception as exc:
                log.warning("Goalies for %s: %s", gid, exc)
        clog.add_from_gamelog(e, goalies)


def _leaders(source, prop, limit=60):
    params = {"isAggregate": "true", "isGame": "false", "start": 0, "limit": limit,
              "sort": json.dumps([{"property": prop, "direction": "DESC"}]),
              "cayenneExp": "gameTypeId=2 and seasonId>=19171918 and seasonId<=20302031"}
    return source._get(f"{NHL_STATS_API}/skater/summary", params=params).get("data", [])


def _rank(rows, prop, pid, value):
    """All-time rank for `value`, using our own up-to-date total for this player."""
    others = [r for r in rows if r["playerId"] != pid]
    return 1 + sum(1 for r in others if r[prop] > value), others


def _schedule(source, team, season):
    games = source._get(f"{NHL_WEB_API}/club-schedule-season/{team}/{season}").get("games", [])
    return [g for g in games if g.get("gameType") == 2]


# ------------------------------------------------------------------ slides ---
def _hero(d, img, team, label, value, sub, color, y=118):
    logos.paste(img, team, (W - M, y + 10), height=150, max_w=200, anchor="rt")
    d.text((M, y), label, fill=C["muted"], font=F("semibold", 28))
    d.text((M, y + 36), value, fill=C["text"], font=F("bold", 150))
    d.text((M, y + 214), sub, fill=color, font=F("bold", 34))


def _tiles(d, tiles, top, color):
    tw, th, gap = (W - 2 * M - 40) / 3, 168, 20
    for i, (val, label, sub) in enumerate(tiles):
        x0 = M + i * (tw + gap)
        _panel(d, [x0, top, x0 + tw, top + th], radius=16)
        cx = x0 + tw / 2
        d.text((cx, top + 24), label, fill=C["muted"], font=F("semibold", 19), anchor="mt")
        d.text((cx, top + 58), val, fill=C["text"], font=_fit(d, val, "bold", 54, tw - 24, 30),
               anchor="mt")
        if sub:
            d.text((cx, top + 128), _ellipsize(d, sub, F("regular", 20), tw - 20), fill=C["body"],
                   font=F("regular", 20), anchor="mt")


def _tonight_text(row, opp):
    if row is None:
        return "Did not play tonight"
    bits = []
    if row["g"]:
        bits.append(f"{row['g']} goal{'s' * (row['g'] > 1)}")
    if row["a"]:
        bits.append(f"{row['a']} assist{'s' * (row['a'] > 1)}")
    where = "vs" if row["home"] else "@"
    return f"Tonight {where} {opp}: " + (", ".join(bits) if bits else f"no points, {row['s']} shots")


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def render_ovi(game, clog, row, schedule, ranks):
    red = "#E03A3E"
    img, d = _canvas(accent=red)
    _header(d, "OVI'S FAREWELL TOUR", _pretty_date(game["date"]), color=red)
    t = clog.totals()
    _hero(d, img, "WSH", "CAREER GOALS", f"{t['g']:,}",
          "NHL RECORD" if ranks["goals"] == 1 else f"#{ranks['goals']} ALL-TIME", red)
    d.text((M, 410), _tonight_text(row, row["opp"] if row else ""), fill=C["text"],
           font=F("semibold", 34))

    season = [r for gid, r in clog.games.items() if season_of(gid) == season_of(game["game_id"])]
    sg, sa = sum(r["g"] for r in season), sum(r["a"] for r in season)
    nxt = (t["g"] // 50 + 1) * 50
    tiles = [(f"{sg}-{sa}-{sg + sa}", "FINAL SEASON G-A-P", f"in {len(season)} games"),
             (f"{nxt - t['g']}", f"GOALS TO {nxt:,}", f"{t['g']:,} and counting"),
             (f"#{ranks['points']}", "ALL-TIME POINTS", ranks["points_next"])]
    _tiles(d, tiles, 470, red)

    # vs tonight's opponent + goalies
    y = 670
    opp = row["opp"] if row else None
    if opp:
        vs = [r for r in clog.games.values() if FRANCHISE.get(r["opp"], r["opp"]) == opp]
        vs_g = sum(r["g"] for r in vs)
        by_opp = {}
        for r in clog.games.values():
            k = FRANCHISE.get(r["opp"], r["opp"])
            by_opp[k] = by_opp.get(k, 0) + r["g"]
        most = max(by_opp.items(), key=lambda kv: kv[1])
        _panel(d, [M - 24, y, W - M + 24, y + 150])
        logos.paste(img, opp, (M + 40, y + 75), height=96, max_w=110, anchor="mm")
        d.text((M + 110, y + 26), f"CAREER VS {opp}", fill=C["muted"], font=F("semibold", 22))
        d.text((M + 110, y + 60), f"{vs_g} goals in {len(vs)} games", fill=C["text"], font=F("bold", 40))
        tag = "his most vs any franchise" if most[0] == opp else f"most vs any franchise: {most[1]} vs {most[0]}"
        d.text((W - M, y + 112), tag, fill=C["body"], font=F("regular", 22), anchor="ra")
        y += 172

    tonight_gid = str(game["game_id"])
    before, victims = {}, {}
    for gid, r in clog.games.items():
        for g in r.get("gk", []):
            if g:
                victims[g] = victims.get(g, 0) + 1
                if gid != tonight_gid:
                    before[g] = before.get(g, 0) + 1
    names = clog.data["goalies"]
    _panel(d, [M - 24, y, W - M + 24, y + 196])
    d.text((M, y + 24), "GOALIES SCORED ON", fill=C["muted"], font=F("semibold", 22))
    d.text((M, y + 60), f"{len(victims)}", fill=C["text"], font=F("bold", 80))
    lines = []
    tonight = {}
    for g in (row or {}).get("gk", []):
        tonight[g] = tonight.get(g, 0) + 1
    for g, n in tonight.items():
        if not g:
            lines.append("Tonight: " + ("an empty-netter" if n == 1 else f"{n} empty-netters"))
            continue
        who = names.get(str(g)) or "?"
        extra = f" ({n} goals)" if n > 1 else ""
        if not before.get(g):
            lines.append(f"New tonight: {who}{extra}, victim #{len(victims)}")
        else:
            lines.append(f"Tonight: {who}{extra}, now {victims[g]} career")
    if victims:
        fav = max(victims.items(), key=lambda kv: kv[1])
        lines.append(f"Most: {names.get(str(fav[0]), '?')}, {fav[1]} goals")
    lx = M + 250
    ly = y + 98 - 22 * (min(len(lines), 3) - 1)
    for line in lines[:3]:
        d.text((lx, ly), _ellipsize(d, line, F("regular", 28), W - M - lx), fill=C["body"],
               font=F("regular", 28), anchor="lm")
        ly += 44
    y += 226

    # farewell: final visit / games left, and the fun numbers
    day, gid = game["date"][:10], game["game_id"]
    left = [g for g in schedule if (g["gameDate"], g["id"]) > (day, gid)]
    home_left = sum(1 for g in left if g["homeTeam"]["abbrev"] == "WSH")
    line = f"{len(left)} regular-season games left  ·  {home_left} more in D.C."
    if row and not row["home"]:
        host = row["opp"]
        again = any(g["homeTeam"]["abbrev"] == host for g in left)
        if not again:
            d.text((M, y), f"FINAL REGULAR-SEASON VISIT TO {CITY.get(host, host).upper()}", fill=red,
                   font=_fit(d, f"FINAL REGULAR-SEASON VISIT TO {CITY.get(host, host).upper()}", "bold",
                             34, W - 2 * M, 24))
            y += 50
    d.text((M, y), line, fill=C["text"], font=F("semibold", 30))
    y += 56
    fun = [f"PP goals {t['ppg']}" + (" (#1 all-time)" if ranks.get("ppGoals") == 1 else ""),
           f"Game-winners {t['gwg']}" + (" (#1)" if ranks.get("gameWinningGoals") == 1 else ""),
           f"OT goals {t['otg']}" + (" (#1)" if ranks.get("otGoals") == 1 else "")]
    d.text((M, y), "  ·  ".join(fun), fill=C["body"], font=_fit(d, "  ·  ".join(fun), "regular", 28,
                                                                W - 2 * M, 20))
    _footer(d)
    return img


def render_crosby(game, clog, row, ladder, rank, pace, assists_rank):
    gold = "#FCB514"
    img, d = _canvas(accent=gold)
    _header(d, "CROSBY: CHASING HISTORY", _pretty_date(game["date"]), color=gold)
    t = clog.totals()
    _hero(d, img, "PIT", "CAREER POINTS", f"{t['p']:,}", f"#{rank} ALL-TIME", gold)
    d.text((M, 410), _tonight_text(row, row["opp"] if row else ""), fill=C["text"],
           font=F("semibold", 34))

    y = 476
    d.text((M, y), "THE ALL-TIME POINTS LADDER", fill=C["muted"], font=F("semibold", 24))
    y += 44
    for r in ladder:
        me = r["playerId"] == CROSBY
        if me:
            d.rounded_rectangle([M - 20, y - 8, W - M + 20, y + 62], radius=12, fill="#2A2410",
                                outline=gold, width=2)
        d.text((M, y + 6), f"{r['rank']}", fill=gold if me else C["muted"], font=F("bold", 34))
        d.text((M + 70, y + 6), r["skaterFullName"], fill=C["text"], font=F("bold", 34))
        d.text((W - M - 190, y + 6), f"{r['points']:,}", fill=C["text"], font=F("bold", 34), anchor="ra")
        gap = r["points"] - t["p"]
        if not me:
            txt = f"{gap:,} ahead" if gap > 0 else ("tied" if gap == 0 else f"{-gap:,} behind")
            d.text((W - M, y + 12), txt, fill=C["body"], font=F("regular", 26), anchor="ra")
        y += 76
    y += 10
    season = [r for gid, r in clog.games.items() if season_of(gid) == season_of(game["game_id"])]
    sp = sum(r["g"] + r["a"] for r in season)
    tiles = [(f"{sp}", "POINTS THIS SEASON", f"in {len(season)} games"),
             (f"{pace['total']:,}", "ON PACE TO FINISH AT", pace["passes"]),
             (f"#{assists_rank}", "ALL-TIME ASSISTS", f"{t['a']:,} assists")]
    _tiles(d, tiles, max(y, 1000), gold)
    _footer(d)
    return img


# ------------------------------------------------------------------- entry ---
def _ovi_slide(source, game, bundle):
    season = season_of(game["game_id"])
    clog = CareerLog(OVI)
    sync(source, clog, season, game["game_id"], fetch_goalies=True)
    row = tonight_row(game, bundle, OVI)
    if row:
        for g, n in row.pop("_goalie_names").items():
            clog.data["goalies"][str(g)] = n
        clog.games[str(game["game_id"])] = row
    t = clog.totals()
    ranks = {}
    pts = _leaders(source, "points")
    ranks["goals"], _ = _rank(_leaders(source, "goals"), "goals", OVI, t["g"])
    ranks["points"], others = _rank(pts, "points", OVI, t["p"])
    above = sorted((r for r in others if r["points"] > t["p"]), key=lambda r: r["points"])
    ranks["points_next"] = (f"{above[0]['points'] - t['p']} to pass {above[0]['lastName']}"
                            if above else "")
    for prop, key in (("ppGoals", "ppg"), ("gameWinningGoals", "gwg"), ("otGoals", "otg")):
        ranks[prop], _ = _rank(_leaders(source, prop, 10), prop, OVI, t[key])
    sched = _schedule(source, "WSH", season)
    img = render_ovi(game, clog, row, sched, ranks)
    clog.save(f"Tracker: Ovechkin {game['game_id']}")
    event = _ovi_event(game, clog, row, ranks, sched) if row and row["g"] else None
    return ("ovi", img), (f"Ovechkin farewell tour tracker: {t['g']} career goals"), event


def _ovi_event(game, clog, row, ranks, sched):
    """Data for the Ovechkin goal Reel."""
    t = clog.totals()
    gid = str(game["game_id"])
    before_counts = {}
    for k, r in clog.games.items():
        if k != gid:
            for g in r.get("gk", []):
                if g:
                    before_counts[g] = before_counts.get(g, 0) + 1
    victims_before = len(before_counts)
    shots = sorted((e for e in game["timeline"] if e.get("shooter_id") == OVI and e["goal"]),
                   key=lambda e: e["t"])
    names = clog.data["goalies"]
    goals, seen = [], dict(before_counts)
    for i, g in enumerate(row.get("gk", [])):
        e = shots[i] if i < len(shots) else {}
        if not g:
            line = "Empty-netter"
        else:
            who = names.get(str(g)) or "?"
            seen[g] = seen.get(g, 0) + 1
            if seen[g] == 1:
                victims_before += 1
                line = f"New victim #{victims_before}: {who}"
            else:
                line = f"{who}: goal #{seen[g]} against him"
        goals.append({"x": e.get("x"), "y": e.get("y"), "xg": e.get("xg", 0.1), "line": line})
    nxt = (t["g"] // 50 + 1) * 50
    day = game["date"][:10]
    left = [g for g in sched if (g["gameDate"], g["id"]) > (day, game["game_id"])]
    extra = f"{len(left)} REGULAR-SEASON GAMES LEFT"
    if not row["home"] and not any(g["homeTeam"]["abbrev"] == row["opp"] for g in left):
        extra = f"FINAL REGULAR-SEASON VISIT TO {CITY.get(row['opp'], row['opp']).upper()}"
    return {"kind": "ovi", "date": day, "game_id": game["game_id"], "before": t["g"] - row["g"],
            "after": t["g"], "opp": row["opp"], "home": row["home"], "goals": goals,
            "record": ranks.get("goals") == 1, "next_milestone": nxt, "to_next": nxt - t["g"],
            "extra": extra}


def _crosby_slide(source, game, bundle):
    season = season_of(game["game_id"])
    clog = CareerLog(CROSBY)
    sync(source, clog, season, game["game_id"])
    row = tonight_row(game, bundle, CROSBY)
    if row:
        row.pop("_goalie_names")
        clog.games[str(game["game_id"])] = row
    t = clog.totals()
    rows = _leaders(source, "points")
    rank, others = _rank(rows, "points", CROSBY, t["p"])
    board = sorted(others + [{"playerId": CROSBY, "skaterFullName": "Sidney Crosby", "lastName": "Crosby",
                              "points": t["p"]}], key=lambda r: -r["points"])
    for i, r in enumerate(board, 1):
        r["rank"] = i
    idx = next(i for i, r in enumerate(board) if r["playerId"] == CROSBY)
    ladder = board[max(0, idx - 3): idx + 3]
    # pace over the team's full schedule
    sched = _schedule(source, "PIT", season)
    season_rows = [r for gid, r in clog.games.items() if season_of(gid) == season]
    ppg = sum(r["g"] + r["a"] for r in season_rows) / max(1, len(season_rows))
    day = game["date"][:10]
    left = sum(1 for g in sched if (g["gameDate"], g["id"]) > (day, game["game_id"]))
    total = round(t["p"] + ppg * left)
    passed = [r["lastName"] for r in board[:idx] if r["points"] <= total]
    pace = {"total": total, "passes": ("passing " + " and ".join(reversed(passed[-2:]))) if passed else
            f"{ppg:.2f} points per game"}
    a_rank, _ = _rank(_leaders(source, "assists"), "assists", CROSBY, t["a"])
    img = render_crosby(game, clog, row, ladder, rank, pace, a_rank)
    clog.save(f"Tracker: Crosby {game['game_id']}")
    event = None
    if row and (row["g"] + row["a"]):
        before = t["p"] - row["g"] - row["a"]
        passed = [r for r in board if r["playerId"] != CROSBY and before <= r["points"] < t["p"]]
        if passed:
            lo = max(0, idx - 2)
            rows = board[lo: idx + 1 + len(passed) + 1][:7]
            above = [r for r in board[:idx]]
            event = {"kind": "crosby", "date": day, "game_id": game["game_id"], "before": before,
                     "after": t["p"], "rank_after": idx + 1,
                     "board": [{"name": r["skaterFullName"], "points": r["points"],
                                "me": r["playerId"] == CROSBY} for r in rows],
                     "passed": [r["skaterFullName"] for r in sorted(passed, key=lambda r: r["points"])],
                     "next_name": above[-1]["skaterFullName"] if above else None,
                     "to_next": (above[-1]["points"] - t["p"]) if above else None}
    return (("crosby", img), f"Sidney Crosby all-time points tracker: {t['p']:,} career points, #{rank}",
            event)


def tracker_slides(source, game, bundle, events=None):
    """[(name, image)], [alt text] for any tracker that applies to this game. Never raises.
    Milestone events (Ovechkin goal, Crosby passing someone) are appended to `events`."""
    slides, alts = [], []
    abbrevs = {game["teams"]["away"]["abbrev"], game["teams"]["home"]["abbrev"]}
    for pid, team, fn in ((OVI, "WSH", _ovi_slide), (CROSBY, "PIT", _crosby_slide)):
        if team not in abbrevs or not hasattr(source, "_get"):
            continue
        try:
            slide, alt, event = fn(source, game, bundle)
            slides.append(slide)
            alts.append(alt)
            if event and events is not None:
                events.append(event)
        except Exception:
            log.exception("Tracker for %s skipped", pid)
    return slides, alts
