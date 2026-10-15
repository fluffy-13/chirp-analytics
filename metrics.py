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
def analyze_game(bundle):
    box, pbp, shifts, score = bundle["boxscore"], bundle["pbp"], bundle["shifts"], bundle["score"]
    home_id = pbp["homeTeam"]["id"]
    roster = {r["playerId"]: r for r in pbp.get("rosterSpots", [])}
    team_of = {pid: r.get("teamId") for pid, r in roster.items()}
    on_ice = _on_ice_index(shifts)
    s = defaultdict(lambda: defaultdict(float))
    last_attempt = {}   # team -> (period, sec, y) of its previous attempt, blocked included
    prev_event = None   # (period, sec, canonical type, x, y, team) — previous play in the period
    team_xg = defaultdict(float)

    for play in sorted(pbp.get("plays", []), key=lambda p: p.get("sortOrder", 0)):
        kind = play.get("typeDescKey")
        d = play.get("details") or {}
        period_info = play.get("periodDescriptor") or {}
        if period_info.get("periodType") == "SO":
            continue
        period = period_info.get("number")
        sec = clock_to_sec(play.get("timeInPeriod"))
        sit = play.get("situationCode", "")
        x, y = d.get("xCoord"), d.get("yCoord")
        event_team = d.get("eventOwnerTeamId")
        prev = prev_event if prev_event and prev_event[0] == period else None

        if kind in SHOT_EVENTS:
            shooter = d.get("scoringPlayerId") if kind == "goal" else d.get("shootingPlayerId")
            # roster lookup first: the feed credits a blocked shot to the blocking team
            team = team_of.get(shooter) or event_team
            event_team = team
            if shooter and team is not None:
                xg = _score_shot(s, team_xg, last_attempt, prev, play, kind, d, shooter, team,
                                 team == home_id, period, sec, sit, x, y)
                last_attempt[team] = (period, sec, y)
                p = s[shooter]
                if kind == "goal":
                    p["G"] += 1
                    for key, label in (("assist1PlayerId", "A1"), ("assist2PlayerId", "A2")):
                        if d.get(key):
                            s[d[key]][label] += 1
                if kind == "blocked-shot" and d.get("blockingPlayerId"):
                    s[d["blockingPlayerId"]]["BLK"] += 1
                if is_5v5(sit) and on_ice:
                    for pid, tid in _players_on_ice(on_ice, period, sec):
                        side = "F" if tid == team else "A"
                        s[pid]["C" + side] += 1
                        s[pid]["xG" + side] += xg
                        if kind == "goal":
                            s[pid]["G" + side] += 1

        elif kind == "penalty":
            if d.get("committedByPlayerId"):
                s[d["committedByPlayerId"]]["PT"] += 1
            if d.get("drawnByPlayerId"):
                s[d["drawnByPlayerId"]]["PD"] += 1
        elif kind == "faceoff":
            if d.get("winningPlayerId"):
                s[d["winningPlayerId"]]["FOW"] += 1
            if d.get("losingPlayerId"):
                s[d["losingPlayerId"]]["FOL"] += 1

        prev_event = (period, sec, xg_model.API_EVENT_NAMES.get(kind, str(kind).upper()),
                      x, y, event_team)

    players = []
    for side in ("awayTeam", "homeTeam"):
        team = box[side]
        for group in ("forwards", "defense"):
            for bp in box.get("playerByGameStats", {}).get(side, {}).get(group, []):
                pid = bp["playerId"]
                m = s.get(pid, {})
                g = lambda k: m.get(k, 0)
                gs = (0.75 * g("G") + 0.7 * g("A1") + 0.55 * g("A2") + 0.075 * g("SOG")
                      + 0.05 * g("BLK") + 0.15 * g("PD") - 0.15 * g("PT")
                      + 0.01 * g("FOW") - 0.01 * g("FOL") + 0.05 * g("CF") - 0.05 * g("CA")
                      + 0.15 * g("GF") - 0.15 * g("GA"))
                players.append({
                    "player_id": pid,
                    "name": _full_name(roster.get(pid, {})) or (bp.get("name") or {}).get("default", ""),
                    "position": bp.get("position", ""),
                    "sweater": bp.get("sweaterNumber"),
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
                    "game_score": round(gs, 2),
                })

    away, home = score.get("awayTeam", {}), score.get("homeTeam", {})
    last = (score.get("gameOutcome") or {}).get("lastPeriodType", "REG")
    suffix = {"OT": " (OT)", "SO": " (SO)"}.get(last, "")
    return {
        "game_id": score["id"],
        "date": box.get("gameDate", ""),
        "matchup": f"{away.get('abbrev')} {away.get('score', 0)} @ {home.get('abbrev')} {home.get('score', 0)}{suffix}",
        "has_on_ice": bool(on_ice),
        "team_xg": {box["awayTeam"]["abbrev"]: round(team_xg[box["awayTeam"]["id"]], 2),
                    box["homeTeam"]["abbrev"]: round(team_xg[box["homeTeam"]["id"]], 2)},
        "players": players,
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
