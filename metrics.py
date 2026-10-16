"""Turns raw NHL play-by-play + shift charts into real per-player analytics.

Everything posted comes from here — nothing is hardcoded.

Metrics
  iCF / iFF      individual shot attempts (all / unblocked)
  ixG            individual expected goals from the trained model in xg_model.py
  iHD            unblocked attempts from the home-plate area (see HD_* constants)
  CF/CA, xGF/xGA on-ice 5v5 shot attempts / xG for and against (needs shift data)
  Game Score     Dom Luszczyszyn's single-game value formula
"""
import math
from collections import defaultdict

import xg_model

SHOT_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
UNBLOCKED = {"goal", "shot-on-goal", "missed-shot"}
NET_X = 89.0          # goal lines sit at x = ±89 ft in NHL coordinates
REBOUND_WINDOW = 3    # seconds since the team's previous attempt (matches training)
RUSH_WINDOW = 4
HD_MAX_DIST = 22.0    # "home-plate area" approximation
HD_MAX_ANGLE = 45.0


# ---------------------------------------------------------------- helpers ----
def clock_to_sec(clock):
    try:
        mins, secs = str(clock).split(":")
        return int(mins) * 60 + int(secs)
    except (ValueError, AttributeError):
        return 0


def is_5v5(situation_code):
    return situation_code == "1551"


def goalie_pulled(situation_code, shooter_is_home):
    """situationCode digits: [away goalie][away skaters][home skaters][home goalie]."""
    if not situation_code or len(situation_code) != 4:
        return False
    defending_goalie = situation_code[0] if shooter_is_home else situation_code[3]
    return defending_goalie == "0"


def strength(situation_code, shooter_is_home):
    """'PP', 'SH' or 'EV' from the shooting team's point of view."""
    if not situation_code or len(situation_code) != 4:
        return "EV"
    away, home = int(situation_code[1]), int(situation_code[2])
    own, opp = (home, away) if shooter_is_home else (away, home)
    return "PP" if own > opp else "SH" if own < opp else "EV"


def attacked_net_x(x, zone_code, shooter_is_home, home_defending_side):
    if zone_code == "O":
        return NET_X if x >= 0 else -NET_X
    if home_defending_side in ("left", "right"):
        home_attacks_right = home_defending_side == "left"
        attacks_right = home_attacks_right if shooter_is_home else not home_attacks_right
        return NET_X if attacks_right else -NET_X
    return NET_X if x >= 0 else -NET_X


def shot_geometry(x, y, zone_code, shooter_is_home, home_defending_side):
    """Distance (ft) and angle (deg off the net's centre line) to the attacked net."""
    net_x = attacked_net_x(x, zone_code, shooter_is_home, home_defending_side)
    dx, dy = abs(net_x - x), abs(y)
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))


def _on_ice_index(shifts):
    index = defaultdict(list)
    for s in shifts:
        if s.get("typeCode", 517) != 517 or not s.get("playerId"):
            continue  # 505 rows are goal markers, not shifts
        start, end = clock_to_sec(s.get("startTime")), clock_to_sec(s.get("endTime"))
        if end > start:
            index[s.get("period")].append((start, end, s["playerId"], s.get("teamId")))
    return index


def _players_on_ice(index, period, sec):
    return [(pid, tid) for start, end, pid, tid in index.get(period, ()) if start < sec <= end]


def _full_name(spot):
    first = (spot.get("firstName") or {}).get("default", "")
    last = (spot.get("lastName") or {}).get("default", "")
    return f"{first} {last}".strip()


def _team_name(team):
    place = (team.get("placeName") or {}).get("default", "")
    common = (team.get("commonName") or {}).get("default", "")
    return f"{place} {common}".strip() or team.get("abbrev", "")


def _score_shot(s, team_xg, last_attempt, prev, play, kind, d, shooter, team, is_home,
                period, sec, sit, x, y):
    """Counts the attempt for the shooter and returns its xG (0 for blocked/empty-net)."""
    p = s[shooter]
    p["iCF"] += 1
    if kind not in UNBLOCKED:
        return 0.0
    p["iFF"] += 1
    if kind != "missed-shot":
        p["SOG"] += 1
    if x is None or y is None or goalie_pulled(sit, is_home):
        return 0.0

    net_x = attacked_net_x(x, d.get("zoneCode"), is_home, play.get("homeTeamDefendingSide"))
    dx, dy = abs(net_x - x), abs(y)
    dist, ang = math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))

    last = last_attempt.get(team)
    rebound = bool(last and last[0] == period and 0 <= sec - last[1] <= REBOUND_WINDOW)
    rebound_dy = abs(y - last[2]) if rebound and last[2] is not None else 0.0
    dt = prev_type = prev_dist = None
    rush = same_team = False
    if prev:
        _, psec, prev_type, px, py, pteam = prev
        dt = sec - psec
        same_team = pteam == team
        if px is not None and py is not None:
            prev_dist = math.hypot(x - px, y - py)
            rush = 0 <= dt <= RUSH_WINDOW and px * (1 if net_x > 0 else -1) < 25

    xg = xg_model.predict(xg_model.features(
        dist, ang, d.get("shotType"), rebound, rush, strength(sit, is_home),
        dt=dt, prev_type=prev_type, prev_dist=prev_dist, same_team_prev=same_team,
        rebound_dy=rebound_dy))
    p["ixG"] += xg
    team_xg[team] += xg
    if dist <= HD_MAX_DIST and ang <= HD_MAX_ANGLE:
        p["iHD"] += 1
    return xg


# ---------------------------------------------------------------- analysis ---
REG_PERIOD_SEC = 1200

# Fallback team colours (used only when the shift feed has none). Dark brand colours are
# lightened for the dark card background by readable_color().
TEAM_COLORS = {
    "ANA": "#F47A38", "BOS": "#FFB81C", "BUF": "#2E6BD9", "CGY": "#D2001C", "CAR": "#CE1126",
    "CHI": "#CF0A2C", "COL": "#A0274E", "CBJ": "#3363B0", "DAL": "#00A15E", "DET": "#CE1126",
    "EDM": "#FF4C00", "FLA": "#C8102E", "LAK": "#A2AAAD", "MIN": "#2E8B57", "MTL": "#AF1E2D",
    "NSH": "#FFB81C", "NJD": "#CE1126", "NYI": "#F47D30", "NYR": "#3C6FD8", "OTT": "#DA1A32",
    "PHI": "#F74902", "PIT": "#FCB514", "SJS": "#00A3AD", "SEA": "#99D9D9", "STL": "#4A7BDB",
    "TBL": "#3D73D6", "TOR": "#3A6FD8", "UTA": "#71AFE5", "VAN": "#00843D", "VGK": "#B4975A",
    "WSH": "#C8102E", "WPG": "#5B8FD8",
}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def readable_color(hex_color, min_lum=0.28):
    """Lighten a team colour until it reads on the near-black card background."""
    r, g, b = _hex_to_rgb(hex_color)
    for _ in range(12):
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        if lum >= min_lum:
            break
        r, g, b = (int(c + (255 - c) * 0.18) for c in (r, g, b))
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def _lum(hex_color):
    r, g, b = _hex_to_rgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def team_color(feed_hex, abbrev):
    """Curated brand colour (stable across games); the feed's colour only for unknown teams."""
    if abbrev in TEAM_COLORS:
        return readable_color(TEAM_COLORS[abbrev])
    if feed_hex and _lum(feed_hex) >= 0.12:
        return readable_color(feed_hex)
    return "#8B949E"


def elapsed_seconds(period, sec):
    return (max(int(period or 1), 1) - 1) * REG_PERIOD_SEC + sec


def _pp_side(code):
    """'home' / 'away' if that team has a man advantage with both goalies in, else None."""
    if not code or len(code) != 4 or code[0] != "1" or code[3] != "1":
        return None
    away, home = int(code[1]), int(code[2])
    return "home" if home > away else "away" if away > home else None


def _new_team():
    return defaultdict(float)


def analyze_game(bundle):
    box, pbp, shifts, score = bundle["boxscore"], bundle["pbp"], bundle["shifts"], bundle["score"]
    home_id = pbp["homeTeam"]["id"]
    away_id = pbp["awayTeam"]["id"]
    roster = {r["playerId"]: r for r in pbp.get("rosterSpots", [])}
    team_of = {pid: r.get("teamId") for pid, r in roster.items()}
    on_ice = _on_ice_index(shifts)
    s = defaultdict(lambda: defaultdict(float))
    T = {home_id: _new_team(), away_id: _new_team()}
    goalie_xga = defaultdict(float)
    goalie_ga = defaultdict(int)
    timeline = []       # (elapsed sec, team id, xG, is goal, scorer id)
    last_attempt = {}   # team -> (period, sec, y) of its previous attempt, blocked included
    prev_event = None   # (period, sec, canonical type, x, y, team) — previous play in the period
    team_xg = defaultdict(float)
    pp_state = None
    game_len = 3 * REG_PERIOD_SEC

    for play in sorted(pbp.get("plays", []), key=lambda p: p.get("sortOrder", 0)):
        kind = play.get("typeDescKey")
        d = play.get("details") or {}
        period_info = play.get("periodDescriptor") or {}
        if period_info.get("periodType") == "SO":
            continue
        period = period_info.get("number")
        sec = clock_to_sec(play.get("timeInPeriod"))
        t = elapsed_seconds(period, sec)
        game_len = max(game_len, t)
        sit = play.get("situationCode", "")
        x, y = d.get("xCoord"), d.get("yCoord")
        event_team = d.get("eventOwnerTeamId")
        prev = prev_event if prev_event and prev_event[0] == period else None

        side = _pp_side(sit)
        if side and side != pp_state:
            T[home_id if side == "home" else away_id]["pp_opps"] += 1
        pp_state = side

        if kind in SHOT_EVENTS:
            shooter = d.get("scoringPlayerId") if kind == "goal" else d.get("shootingPlayerId")
            # roster lookup first: the feed's team owner for blocked shots isn't reliable
            team = team_of.get(shooter) or event_team
            event_team = team
            if shooter and team in T:
                is_home = team == home_id
                xg = _score_shot(s, team_xg, last_attempt, prev, play, kind, d, shooter, team,
                                 is_home, period, sec, sit, x, y)
                last_attempt[team] = (period, sec, y)
                tm = T[team]
                tm["attempts"] += 1
                if kind in UNBLOCKED:
                    tm["unblocked"] += 1
                    goalie = d.get("goalieInNetId")
                    if goalie:
                        goalie_xga[goalie] += xg
                    if xg or kind == "goal":
                        timeline.append((t, team, xg, kind == "goal", shooter))
                    if xg and x is not None and y is not None:
                        dist, ang = shot_geometry(x, y, d.get("zoneCode"), is_home,
                                                  play.get("homeTeamDefendingSide"))
                        if dist <= HD_MAX_DIST and ang <= HD_MAX_ANGLE:
                            tm["hd"] += 1
                if kind in ("goal", "shot-on-goal"):
                    tm["sog"] += 1
                tm["xg"] += xg
                if is_5v5(sit):
                    tm["att5"] += 1
                    tm["xg5"] += xg
                p = s[shooter]
                if kind == "goal":
                    p["G"] += 1
                    tm["goals"] += 1
                    if strength(sit, is_home) == "PP":
                        tm["pp_goals"] += 1
                    if d.get("goalieInNetId"):
                        goalie_ga[d["goalieInNetId"]] += 1
                    for key, label in (("assist1PlayerId", "A1"), ("assist2PlayerId", "A2")):
                        if d.get(key):
                            s[d[key]][label] += 1
                if kind == "blocked-shot" and d.get("blockingPlayerId"):
                    s[d["blockingPlayerId"]]["BLK"] += 1
                    bt = team_of.get(d["blockingPlayerId"])
                    if bt in T:
                        T[bt]["blocks"] += 1
                if is_5v5(sit) and on_ice:
                    for pid, tid in _players_on_ice(on_ice, period, sec):
                        side_ = "F" if tid == team else "A"
                        s[pid]["C" + side_] += 1
                        s[pid]["xG" + side_] += xg
                        if kind == "goal":
                            s[pid]["G" + side_] += 1

        elif kind == "penalty":
            if d.get("committedByPlayerId"):
                s[d["committedByPlayerId"]]["PT"] += 1
                pt = team_of.get(d["committedByPlayerId"])
                if pt in T:
                    T[pt]["pim"] += d.get("duration") or 0
            if d.get("drawnByPlayerId"):
                s[d["drawnByPlayerId"]]["PD"] += 1
        elif kind == "faceoff":
            if d.get("winningPlayerId"):
                s[d["winningPlayerId"]]["FOW"] += 1
                wt = team_of.get(d["winningPlayerId"])
                if wt in T:
                    T[wt]["fow"] += 1
            if d.get("losingPlayerId"):
                s[d["losingPlayerId"]]["FOL"] += 1
        elif kind == "hit":
            ht = team_of.get(d.get("hittingPlayerId")) or event_team
            if ht in T:
                T[ht]["hits"] += 1
        elif kind in ("giveaway", "takeaway"):
            gt = team_of.get(d.get("playerId")) or event_team
            if gt in T:
                T[gt][kind + "s"] += 1

        prev_event = (period, sec, xg_model.API_EVENT_NAMES.get(kind, str(kind).upper()),
                      x, y, event_team)

    # --- skaters --------------------------------------------------------------
    players = []
    for side in ("awayTeam", "homeTeam"):
        team = box[side]
        for group in ("forwards", "defense"):
            for bp in box.get("playerByGameStats", {}).get(side, {}).get(group, []):
                pid = bp["playerId"]
                m = s.get(pid, {})
                g = lambda k: m.get(k, 0)
                # Game Score, split into what drove it (the parts sum to the total)
                parts = {
                    "scoring": 0.75 * g("G") + 0.7 * g("A1") + 0.55 * g("A2"),
                    "shots": 0.075 * g("SOG"),
                    "play5": 0.05 * (g("CF") - g("CA")),     # 5v5 on-ice shot attempts
                    "goals5": 0.15 * (g("GF") - g("GA")),    # 5v5 on-ice goals
                    "other": (0.05 * g("BLK") + 0.15 * (g("PD") - g("PT"))
                              + 0.01 * (g("FOW") - g("FOL"))),
                }
                gs = sum(parts.values())
                players.append({
                    "player_id": pid,
                    "name": _full_name(roster.get(pid, {})) or (bp.get("name") or {}).get("default", ""),
                    "position": bp.get("position", ""),
                    "sweater": bp.get("sweaterNumber"),
                    "team_id": team.get("id"),
                    "team_name": _team_name(team),
                    "team_abbrev": team.get("abbrev", ""),
                    "toi": bp.get("toi", "0:00"),
                    "G": int(g("G")), "A": int(g("A1") + g("A2")),
                    "A1": int(g("A1")), "A2": int(g("A2")),
                    "SOG": int(g("SOG")), "iCF": int(g("iCF")), "iFF": int(g("iFF")),
                    "iHD": int(g("iHD")), "ixG": round(g("ixG"), 2),
                    "CF": int(g("CF")), "CA": int(g("CA")),
                    "xGF": round(g("xGF"), 2), "xGA": round(g("xGA"), 2),
                    "BLK": int(g("BLK")), "hits": bp.get("hits", 0),
                    "PD": int(g("PD")), "PT": int(g("PT")),
                    "FOW": int(g("FOW")), "FOL": int(g("FOL")),
                    "GF5": int(g("GF")), "GA5": int(g("GA")),
                    "xg_pm5": round(g("xGF") - g("xGA"), 2),
                    "game_score": round(gs, 2),
                    "gs_parts": {k: round(v, 3) for k, v in parts.items()},
                })

    # --- goalies --------------------------------------------------------------
    goalies = []
    for side in ("awayTeam", "homeTeam"):
        team = box[side]
        for bg in box.get("playerByGameStats", {}).get(side, {}).get("goalies", []):
            if clock_to_sec(bg.get("toi")) == 0:
                continue
            pid = bg["playerId"]
            saves, sa = bg.get("saves", 0) or 0, bg.get("shotsAgainst", 0) or 0
            ga = bg.get("goalsAgainst", 0) or 0
            xga = goalie_xga.get(pid, 0.0)
            goalies.append({
                "player_id": pid,
                "name": _full_name(roster.get(pid, {})) or (bg.get("name") or {}).get("default", ""),
                "position": "G",
                "team_id": team.get("id"),
                "team_abbrev": team.get("abbrev", ""),
                "toi": bg.get("toi", "0:00"),
                "saves": saves, "shots_against": sa, "goals_against": ga,
                "sv_pct": round(saves / sa, 3) if sa else None,
                "xga": round(xga, 2),
                "gsax": round(xga - goalie_ga.get(pid, 0), 2),
                "decision": bg.get("decision"),
                "game_score": round(0.1 * saves - 0.75 * ga, 2),
            })

    # --- teams ----------------------------------------------------------------
    colors = {}
    for sh in shifts:
        if sh.get("teamId") and sh.get("hexValue"):
            colors.setdefault(sh["teamId"], sh["hexValue"])

    last = (score.get("gameOutcome") or box.get("gameOutcome") or {}).get("lastPeriodType", "REG")
    final = {"away": score.get("awayTeam", {}).get("score", 0),
             "home": score.get("homeTeam", {}).get("score", 0)}

    teams = {}
    for side, tid, opp in (("away", away_id, home_id), ("home", home_id, away_id)):
        bt = box[side + "Team"]
        a, o = T[tid], T[opp]
        abbrev = bt.get("abbrev", "")
        cf5, ca5 = a["att5"], o["att5"]
        xgf5, xga5 = a["xg5"], o["xg5"]
        fo_total = a["fow"] + o["fow"]
        teams[side] = {
            "id": tid, "abbrev": abbrev, "name": _team_name(bt),
            "common_name": (bt.get("commonName") or {}).get("default", abbrev),
            "is_home": side == "home",
            "score": final[side], "opp_score": final["home" if side == "away" else "away"],
            "won": final[side] > final["home" if side == "away" else "away"],
            "color": team_color(colors.get(tid), abbrev),
            "goals": int(a["goals"]), "sog": int(bt.get("sog") or a["sog"]),
            "attempts": int(a["attempts"]),
            "xg": round(a["xg"], 2), "hd": int(a["hd"]),
            "cf5": int(cf5), "ca5": int(ca5),
            "cf5_pct": round(100 * cf5 / (cf5 + ca5), 1) if cf5 + ca5 else None,
            "xgf5": round(xgf5, 2), "xga5": round(xga5, 2),
            "xg5_pct": round(100 * xgf5 / (xgf5 + xga5), 1) if xgf5 + xga5 else None,
            "pp_goals": int(a["pp_goals"]), "pp_opps": int(a["pp_opps"]),
            "fow": int(a["fow"]),
            "fo_pct": round(100 * a["fow"] / fo_total, 1) if fo_total else None,
            "hits": int(a["hits"]), "blocks": int(a["blocks"]),
            "giveaways": int(a["giveaways"]), "takeaways": int(a["takeaways"]),
            "pim": int(a["pim"]),
        }

    for p in players + goalies:
        p["team_side"] = "home" if p["team_id"] == home_id else "away"

    names = {pid: (_full_name(r) or "") for pid, r in roster.items()}
    stars = sorted(players + goalies, key=lambda p: p["game_score"], reverse=True)[:3]
    away_t, home_t = teams["away"], teams["home"]
    suffix = {"OT": " (OT)", "SO": " (SO)"}.get(last, "")
    return {
        "game_id": score["id"],
        "date": box.get("gameDate", "") or score.get("gameDate", ""),
        "outcome": last,
        "matchup": f"{away_t['abbrev']} {away_t['score']} @ {home_t['abbrev']} {home_t['score']}{suffix}",
        "has_on_ice": bool(on_ice),
        "team_xg": {away_t["abbrev"]: away_t["xg"], home_t["abbrev"]: home_t["xg"]},
        "teams": teams,
        "players": players,
        "goalies": goalies,
        "stars": stars,
        "game_length": game_len,
        "timeline": [{"t": t, "side": "home" if tid == home_id else "away", "xg": round(xg, 3),
                      "goal": goal, "scorer": names.get(sc, "")}
                     for t, tid, xg, goal, sc in timeline],
    }


# ------------------------------------------------------------ storytelling ---
def pick_spotlight(analyses):
    """Best single-game performance across all analysed games, by Game Score."""
    best = None
    for game in analyses:
        for p in game["players"]:
            if best is None or p["game_score"] > best[1]["game_score"]:
                best = (game, p)
    return best


def build_post(game, p):
    """Everything the card and caption are allowed to say, all from real data."""
    if p["ixG"] >= 0.75:
        headline = (f"{p['ixG']:.2f}", "INDIVIDUAL xG")
    else:
        headline = (f"{p['game_score']:.2f}", "GAME SCORE")

    shots = f"{p['iCF']} shot attempts, {p['SOG']} on goal"
    bullets = [f"{shots}, {p['iHD']} from the home-plate area" if p["iHD"] else shots]
    on_ice_total = p["CF"] + p["CA"]
    if game["has_on_ice"] and on_ice_total >= 8:
        pct = 100 * p["CF"] / on_ice_total
        bullets.append(f"Shot attempts {p['CF']}-{p['CA']} with him on the ice at 5v5 ({pct:.0f}% CF)")
    pts = f"{p['G']}G, {p['A']}A in {p['toi']} TOI"
    if headline[1] == "GAME SCORE":
        bullets.append(f"{pts}, {p['ixG']:.2f} individual xG")
    else:
        bullets.append(f"{pts}, Game Score {p['game_score']:.2f}")

    return {
        "game_id": game["game_id"],
        "date": game["date"],
        "matchup": game["matchup"],
        "player_name": p["name"],
        "position": p["position"],
        "team": p["team_name"],
        "team_abbrev": p["team_abbrev"],
        "headline_value": headline[0],
        "headline_label": headline[1],
        "sub_bullets": bullets[:3],
        "player": p,
        "team_xg": game["team_xg"],
    }


# ------------------------------------------------------------------ weekly ---
def aggregate_week(analyses, start, end, min_gp=2, top_n=10):
    """Top/bottom skaters by total Game Score and teams by 5v5 xG share over a set of games."""
    players, teams = {}, {}
    for g in sorted(analyses, key=lambda a: a["date"]):
        for p in g["players"]:
            row = players.setdefault(p["player_id"], defaultdict(float))
            row.update(name=p["name"], position=p["position"], team_abbrev=p["team_abbrev"],
                       color=g["teams"][p["team_side"]]["color"])
            row["gp"] += 1
            for k in ("G", "A", "SOG", "ixG", "game_score"):
                row[k] += p[k]
        for side in ("away", "home"):
            t = g["teams"][side]
            row = teams.setdefault(t["abbrev"], defaultdict(float))
            row.update(name=t["name"], abbrev=t["abbrev"], color=t["color"])
            row["gp"] += 1
            if t["won"]:
                row["w"] += 1
            elif g["outcome"] in ("OT", "SO"):
                row["otl"] += 1
            else:
                row["l"] += 1
            for k in ("xgf5", "xga5", "cf5", "ca5"):
                row[k] += t[k]
            row["gf"] += t["score"]
            row["ga"] += t["opp_score"]

    def finish_player(r):
        return {**r, "gp": int(r["gp"]), "G": int(r["G"]), "A": int(r["A"]), "SOG": int(r["SOG"]),
                "ixG": round(r["ixG"], 2), "game_score": round(r["game_score"], 2)}

    def finish_team(r):
        xg_tot, cf_tot = r["xgf5"] + r["xga5"], r["cf5"] + r["ca5"]
        return {**r, "gp": int(r["gp"]),
                "record": f"{int(r['w'])}-{int(r['l'])}-{int(r['otl'])}",
                "xg5_pct": round(100 * r["xgf5"] / xg_tot, 1) if xg_tot else 0.0,
                "cf5_pct": round(100 * r["cf5"] / cf_tot, 1) if cf_tot else None,
                "xgf5": round(r["xgf5"], 2), "xga5": round(r["xga5"], 2)}

    eligible = [finish_player(r) for r in players.values() if r["gp"] >= min_gp]
    by_gs = sorted(eligible, key=lambda r: r["game_score"], reverse=True)
    t_rows = [finish_team(r) for r in teams.values() if r["gp"] >= min_gp]
    by_xg = sorted(t_rows, key=lambda r: r["xg5_pct"], reverse=True)
    return {
        "start": start, "end": end, "games": len(analyses),
        "players_top": by_gs[:top_n],
        "players_bottom": list(reversed(by_gs[-top_n:])) if len(by_gs) > top_n else [],
        "teams_top": by_xg[:top_n],
        "teams_bottom": list(reversed(by_xg[-top_n:])) if len(by_xg) > top_n else [],
    }
