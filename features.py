"""Recurring feature posts built from the season store:

  awards   monthly (1st)       the 'deserved' race: Hart, Norris, Vezina, Calder, Selke, Lady Byng
  rookies  every other Wed     Calder-eligible skaters by Game Score, last two weeks, goalies
  fantasy  Sunday evening      under-the-radar pickups for categories leagues (G A PPP SOG HIT BLK)
"""
import logging
from datetime import date as Date, timedelta

import logos
from cards import (BAD, GOOD, H, M, W, C, F, _canvas, _ellipsize, _fit, _footer, _header,
                   _num, _panel, _short_name, _signed)
from metrics import team_color
import season as S

log = logging.getLogger("features")
GOLD, ROOKIE, FANTASY = "#E3B341", "#58A6FF", "#B392F0"


# ------------------------------------------------------------------ helpers ---
def _mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _pos(p):
    return {"L": "LW", "R": "RW"}.get(p, p)


def _label(day):
    return Date.fromisoformat(day).strftime("%b %-d").upper()


def _table(kicker, right, title, subtitle, cols, rows, accent, row_h=92, note=None):
    """Ranked table. cols: [label, label, label(value)]. rows: dicts with rank, logo, name, tag,
    tag_color, c1, c2, value, value_color, move (+n / -n / None)."""
    img, d = _canvas(accent=accent)
    _header(d, kicker, right, color=accent)
    d.text((M, 96), title, fill=C["text"], font=_fit(d, title, "bold", 68, W - 2 * M, 40))
    d.text((M, 180), subtitle, fill=C["muted"], font=_fit(d, subtitle, "regular", 26, W - 2 * M, 18))
    x1, x2 = W - M - 370, W - M - 205
    y = 238
    hf = F("semibold", 19)
    d.text((M + 66, y), cols[0], fill=C["faint"], font=hf)
    d.text((x1, y), cols[1], fill=C["faint"], font=hf, anchor="ma")
    d.text((x2, y), cols[2], fill=C["faint"], font=hf, anchor="ma")
    d.text((W - M, y), cols[3], fill=C["faint"], font=hf, anchor="ra")
    y += 36
    for i, r in enumerate(rows):
        if i % 2 == 0:
            d.rounded_rectangle([M - 20, y - 6, W - M + 20, y + row_h - 12], radius=12, fill="#161A21")
        mid = y + (row_h - 18) / 2
        d.text((M + 14, mid), str(r["rank"]), fill=accent, font=F("bold", 34), anchor="mm")
        if r.get("move"):
            up = r["move"] > 0
            col = GOOD if up else BAD
            ax, ay = M + 14, mid + 26
            if up:
                d.polygon([(ax - 7, ay + 7), (ax + 7, ay + 7), (ax, ay - 2)], fill=col)
            else:
                d.polygon([(ax - 7, ay - 2), (ax + 7, ay - 2), (ax, ay + 7)], fill=col)
        nx = M + 52
        lh = min(56, row_h - 34)
        if r.get("logo") and logos.paste(img, r["logo"], (nx + 30, mid), height=lh, max_w=62, anchor="mm"):
            nx += 72
        else:
            nx += 14
        name_f = F("bold", 32)
        d.text((nx, mid - 20), _short_name(d, r["name"], name_f, x1 - nx - 70), fill=C["text"],
               font=name_f, anchor="lm")
        d.text((nx, mid + 22), _ellipsize(d, r["tag"], F("semibold", 21), x1 - nx - 60),
               fill=r.get("tag_color", C["muted"]), font=F("semibold", 21), anchor="lm")
        d.text((x1, mid), r["c1"], fill=C["body"], font=F("regular", 28), anchor="mm")
        d.text((x2, mid), r["c2"], fill=C["body"], font=F("regular", 28), anchor="mm")
        d.text((W - M, mid), r["value"], fill=r.get("value_color", C["text"]),
               font=_fit(d, r["value"], "bold", 42, 120, 26), anchor="rm")
        y += row_h
    if note:
        nf = F("regular", 20)
        ny = H - 112
        for line in reversed(_wrap(d, note, nf, W - 2 * M)):
            d.text((M, ny), line, fill=C["muted"], font=nf)
            ny -= 28
    _footer(d)
    return img


def _wrap(d, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _cover(kicker, right, top, big, tagline, accent, cards, h=150):
    """cards: [(label, name, sub, logo_abbrev, color)]"""
    img, d = _canvas(accent=accent)
    _header(d, kicker, right, color=accent)
    d.text((M, 120), top, fill=C["muted"], font=F("bold", 52))
    d.text((M, 180), big, fill=C["text"], font=_fit(d, big, "bold", 110, W - 2 * M, 60))
    d.text((M, 316), tagline, fill=accent, font=_fit(d, tagline, "bold", 38, W - 2 * M, 22))
    y = 400
    for label, name, sub, ab, color in cards:
        _panel(d, [M - 24, y, W - M + 24, y + h - 14])
        d.rectangle([M - 24, y + 18, M - 16, y + h - 32], fill=color)
        lw = logos.paste(img, ab, (W - M, y + (h - 14) / 2), height=h - 50, max_w=130, anchor="rm") if ab else 0
        maxw = W - 2 * M - 20 - (lw + 20 if lw else 0)
        inner = h - 14
        d.text((M + 8, y + inner * 0.13), label, fill=C["muted"], font=F("semibold", 21))
        nf = F("bold", 42 if h < 150 else 44)
        d.text((M + 8, y + inner * 0.33), _short_name(d, name, nf, maxw), fill=C["text"], font=nf)
        if sub:
            d.text((M + 8, y + inner * 0.70), _ellipsize(d, sub, F("regular", 24), maxw), fill=C["body"],
                   font=F("regular", 24))
        y += h
    d.text((W - M, H - 120), "SWIPE  →", fill=accent, font=F("bold", 30), anchor="ra")
    _footer(d)
    return img


def _team_col(ab):
    return team_color(None, ab)


def _gap(a, b):
    return a


# ------------------------------------------------------------------- awards ---
AWARDS = [
    ("hart", "HART TROPHY", "Most valuable skater: total Game Score this season", "GAME SCORE"),
    ("norris", "NORRIS TROPHY", "Best defenceman: total Game Score among D", "GAME SCORE"),
    ("vezina", "VEZINA TROPHY", "Best goaltender: goals saved above expected (GSAx)", "GSAx"),
    ("calder", "CALDER TROPHY", "Best rookie: total Game Score among Calder-eligible skaters",
     "GAME SCORE"),
    ("selke", "SELKE TROPHY", "Best defensive forward: 5v5 expected goals prevented vs. his team",
     "xGA SAVED"),
    ("byng", "LADY BYNG TROPHY", "Most gentlemanly: top Game Score with the fewest penalty minutes",
     "GAME SCORE"),
]
AWARD_NOTES = {
    "hart": "Game Score adds up goals, assists, shots, blocks, faceoffs, penalties and 5v5 on-ice "
            "shot and goal share, weighted by how much each wins games.",
    "norris": "5v5 xG± = expected goals for minus against with him on the ice at 5-on-5.",
    "vezina": "GSAx = expected goals faced minus goals allowed: it credits stopping the hard shots.",
    "calder": "Rookie = Calder-eligible per the NHL.",
    "selke": "xGA saved = how many fewer 5v5 expected goals his team allowed with him on the ice "
             "than without him, scaled to his minutes. Forwards with 60+ 5v5 minutes.",
    "byng": "Skaters with at most 2 penalty minutes, or 1 per 5 games once the season is longer.",
}


def award_races(records, rookies=None, top=5):
    sk = S.skaters(records)
    gk = S.goalies(records)
    tg = S.team_games(records)
    min_gp = max(2, int(0.4 * max(tg.values() or [1])))
    pool = [p for p in sk.values() if p["gp"] >= min_gp]
    races = {
        "hart": sorted(pool, key=lambda p: -p["gs"]),
        "norris": sorted((p for p in pool if p["is_d"]), key=lambda p: -p["gs"]),
        "vezina": sorted((g for g in gk.values() if g["gp"] >= max(2, min_gp // 2)),
                         key=lambda g: -g["gsax"]),
        "selke": sorted((p for p in pool if not p["is_d"] and p["toi5"] >= 3600),
                        key=lambda p: -p["xga_prevented"]),
        "byng": sorted((p for p in pool if p["PIM"] <= max(2, p["gp"] / 5)), key=lambda p: -p["gs"]),
    }
    if rookies:
        races["calder"] = sorted((p for p in sk.values() if p["id"] in rookies and p["gp"] >= 2),
                                 key=lambda p: -p["gs"])
    return {k: v[:top] for k, v in races.items()}, min_gp


def _award_rows(key, players, prev):
    rows = []
    for i, p in enumerate(players, 1):
        move = None
        if prev and p["id"] in prev:
            move = prev[p["id"]] - i
        elif prev:
            move = 99  # new to the top 5
        if key == "vezina":
            sv = f"{p['sv_pct']:.3f}".lstrip("0") if p["sv_pct"] is not None else "–"
            rows.append({"rank": i, "logo": p["team"], "name": p["name"],
                         "tag": f"{p['team']}  ·  {int(p['gp'])} GP  ·  {int(p['w'])} W",
                         "tag_color": _team_col(p["team"]), "c1": sv, "c2": f"{p['xga']:.1f}",
                         "value": _signed(p["gsax"]), "value_color": GOOD if p["gsax"] > 0 else BAD,
                         "move": move})
            continue
        tag = f"{p['team']}  ·  {_pos(p['pos'])}  ·  {int(p['gp'])} GP"
        if key == "selke":
            c1 = _signed(p["xg_pm5"])
            c2 = (_num(p["xga60_rel"]) if p["xga60_rel"] is not None else "–")
            val = _signed(p["xga_prevented"])
        elif key == "norris":
            c1, c2, val = f"{int(p['P'])}", _signed(p["xg_pm5"]), _num(p["gs"])
            tag += f"  ·  {_mmss(p['toi_gp'])} TOI"
        elif key == "byng":
            c1, c2, val = f"{int(p['G'])}-{int(p['A'])}-{int(p['P'])}", f"{int(p['PIM'])}", _num(p["gs"])
        else:
            c1, c2, val = f"{int(p['G'])}-{int(p['A'])}-{int(p['P'])}", _signed(p["xg_pm5"]), _num(p["gs"])
        rows.append({"rank": i, "logo": p["team"], "name": p["name"], "tag": tag,
                     "tag_color": _team_col(p["team"]), "c1": c1, "c2": c2, "value": val,
                     "value_color": GOLD, "move": move if move != 99 else None,
                     "new": move == 99})
    return rows


AWARD_COLS = {"hart": ["SKATER", "G-A-P", "5V5 xG±", "GAME SCORE"],
              "norris": ["DEFENCEMAN", "POINTS", "5V5 xG±", "GAME SCORE"],
              "vezina": ["GOALIE", "SV%", "xGA FACED", "GSAx"],
              "calder": ["ROOKIE", "G-A-P", "5V5 xG±", "GAME SCORE"],
              "selke": ["FORWARD", "5V5 xG±", "xGA/60 REL", "xGA SAVED"],
              "byng": ["SKATER", "G-A-P", "PIM", "GAME SCORE"]}


def awards_post(records, as_of, rookies=None, previous=None):
    """previous: {award: {player_id: rank}} from last month's post (for movement arrows)."""
    races, min_gp = award_races(records, rookies)
    label = _label(as_of)
    n_games = len(records)
    cards, slides, alts = [], [], []
    for key, name, sub, _ in AWARDS:
        players = races.get(key) or []
        if not players:
            continue
        p = players[0]
        val = (_signed(p["gsax"]) + " GSAx") if key == "vezina" else \
              (_signed(p["xga_prevented"]) + " xGA saved") if key == "selke" else \
              f"{_num(p['gs'])} Game Score"
        cards.append((name.replace(" TROPHY", ""), p["name"], val, p["team"], _team_col(p["team"])))
        rows = _award_rows(key, players, (previous or {}).get(key))
        slides.append(_table(f"AWARDS RACE  //  {label}", f"{n_games} GAMES", name, sub,
                             AWARD_COLS[key], rows, GOLD, row_h=150, note=AWARD_NOTES[key]))
        alts.append(f"{name} race, top 5 by our numbers")
    cover = _cover(f"AWARDS RACE  //  {label}", f"{n_games} GAMES", "IF THE SEASON ENDED TODAY",
                   "AWARDS RACE", "Who deserves it, by the numbers", GOLD, cards, h=136)
    snapshot = {k: {p["id"]: i for i, p in enumerate(v, 1)} for k, v in races.items()}
    leaders = {k: v[0] for k, v in races.items() if v}
    lines = [f"The awards race, by the numbers (through {Date.fromisoformat(as_of).strftime('%B %-d')}):"]
    for key, name, _, _ in AWARDS:
        if key in leaders:
            p = leaders[key]
            v = (_signed(p["gsax"]) + " GSAx") if key == "vezina" else \
                (_signed(p["xga_prevented"]) + " xGA saved") if key == "selke" else f"{_num(p['gs'])} Game Score"
            lines.append(f"🏆 {name.title().replace('Trophy', '').strip()}: {p['name']} ({p['team']}), {v}")
    lines.append("\nNot a prediction of the vote: this is who the stats say deserves it. "
                 "Who's missing? 👇")
    return [cover] + slides, "\n".join(lines), ["Awards race cover: leaders in each race"] + alts, snapshot


# ------------------------------------------------------------------ rookies ---
def rookies_post(records, as_of, rookies):
    sk = S.skaters(records)
    gk = S.goalies(records)
    pool = [p for p in sk.values() if p["id"] in rookies and p["gp"] >= 2]
    if not pool:
        return None
    top = sorted(pool, key=lambda p: -p["gs"])[:10]
    since = (Date.fromisoformat(as_of) - timedelta(days=13)).isoformat()
    recent = S.skaters([r for r in records if r["date"] >= since])
    hot = sorted((p for p in recent.values() if p["id"] in rookies and p["gp"] >= 2),
                 key=lambda p: -p["gs"])[:5]
    goalies = sorted((g for g in gk.values() if g["id"] in rookies and g["gp"] >= 2),
                     key=lambda g: -g["gsax"])[:5]
    label = _label(as_of)
    best_d = next((p for p in sorted(pool, key=lambda p: -p["gs"]) if p["is_d"]), None)
    cards = [("TOP ROOKIE", top[0]["name"], f"{int(top[0]['G'])}-{int(top[0]['A'])}-{int(top[0]['P'])}"
              f"  ·  {_num(top[0]['gs'])} Game Score", top[0]["team"], _team_col(top[0]["team"]))]
    if best_d and best_d is not top[0]:
        cards.append(("TOP ROOKIE D", best_d["name"], f"{int(best_d['P'])} points  ·  "
                      f"{_mmss(best_d['toi_gp'])} a night", best_d["team"], _team_col(best_d["team"])))
    if hot and hot[0]["id"] != top[0]["id"]:
        cards.append(("HOTTEST: LAST 2 WEEKS", hot[0]["name"], f"{_num(hot[0]['gs'])} Game Score in "
                      f"{int(hot[0]['gp'])} games", hot[0]["team"], _team_col(hot[0]["team"])))
    if goalies:
        g = goalies[0]
        cards.append(("TOP ROOKIE GOALIE", g["name"], f"{_signed(g['gsax'])} GSAx", g["team"],
                      _team_col(g["team"])))
    cover = _cover(f"ROOKIE WATCH  //  {label}", f"{len(records)} GAMES", "THE CALDER CLASS",
                   "ROOKIE WATCH", "Who's arriving, by the numbers", ROOKIE, cards[:4], h=136)

    def rows(players):
        return [{"rank": i, "logo": p["team"], "name": p["name"],
                 "tag": f"{p['team']}  ·  {_pos(p['pos'])}  ·  {int(p['gp'])} GP  ·  {_mmss(p['toi_gp'])}",
                 "tag_color": _team_col(p["team"]), "c1": f"{int(p['G'])}-{int(p['A'])}-{int(p['P'])}",
                 "c2": _signed(p["xg_pm5"]), "value": _num(p["gs"]), "value_color": ROOKIE}
                for i, p in enumerate(players, 1)]

    slides = [cover,
              _table(f"ROOKIE WATCH  //  {label}", "", "TOP 10 ROOKIES", "Total Game Score this season "
                     "(Calder-eligible skaters)", ["ROOKIE", "G-A-P", "5V5 xG±", "GAME SCORE"], rows(top),
                     ROOKIE)]
    alts = ["Rookie watch cover", "Top 10 rookies by total Game Score"]
    if hot:
        slides.append(_table(f"ROOKIE WATCH  //  {label}", "", "LAST TWO WEEKS",
                             "Rookies with the most Game Score over the last 14 days",
                             ["ROOKIE", "G-A-P", "5V5 xG±", "GAME SCORE"], rows(hot), ROOKIE, row_h=150))
        alts.append("Top rookies over the last two weeks")
    if goalies:
        grow = [{"rank": i, "logo": g["team"], "name": g["name"],
                 "tag": f"{g['team']}  ·  {int(g['gp'])} GP  ·  {int(g['w'])} W",
                 "tag_color": _team_col(g["team"]),
                 "c1": f"{g['sv_pct']:.3f}".lstrip("0") if g["sv_pct"] else "–",
                 "c2": f"{g['xga']:.1f}", "value": _signed(g["gsax"]),
                 "value_color": GOOD if g["gsax"] > 0 else BAD} for i, g in enumerate(goalies, 1)]
        slides.append(_table(f"ROOKIE WATCH  //  {label}", "", "ROOKIE GOALIES",
                             "Goals saved above expected (min. 2 games)", ["GOALIE", "SV%", "xGA FACED", "GSAx"],
                             grow, ROOKIE, row_h=150))
        alts.append("Rookie goalies by goals saved above expected")
    t = top[0]
    caption = (f"Rookie watch 🆕 through {Date.fromisoformat(as_of).strftime('%B %-d')}\n\n"
               f"🥇 {t['name']} ({t['team']}): {int(t['G'])}-{int(t['A'])}-{int(t['P'])}, "
               f"{_num(t['gs'])} Game Score\n")
    if len(top) > 2:
        caption += "".join(f"{m} {p['name']} ({p['team']}): {_num(p['gs'])}\n"
                           for m, p in zip(("🥈", "🥉"), top[1:3]))
    if hot:
        caption += f"\n🔥 Hottest over the last two weeks: {hot[0]['name']} ({_num(hot[0]['gs'])})\n"
    caption += "\nWho's your Calder pick? 👇"
    return slides, caption, alts


# ------------------------------------------------------------------ fantasy ---
LAST_SEASON_POINTS = 45   # anyone this productive last season is surely rostered


def established_ids(source, season):
    """Players with LAST_SEASON_POINTS+ points last season (stats API); empty set if unavailable."""
    import json as _json
    from config import NHL_STATS_API
    prev = f"{int(season[:4]) - 1}{season[:4]}"
    ids, start = set(), 0
    try:
        while start < 1000:
            params = {"isAggregate": "true", "isGame": "false", "start": start, "limit": 100,
                      "sort": _json.dumps([{"property": "points", "direction": "DESC"}]),
                      "cayenneExp": f"seasonId={prev} and gameTypeId=2"}
            rows = source._get(f"{NHL_STATS_API}/skater/summary", params=params).get("data", [])
            ids |= {str(r["playerId"]) for r in rows if r.get("points", 0) >= LAST_SEASON_POINTS}
            if not rows or rows[-1].get("points", 0) < LAST_SEASON_POINTS:
                break
            start += len(rows)
    except Exception as exc:
        log.warning("Last season's scorers unavailable: %s", exc)
    log.info("Excluding %d established scorers from last season", len(ids))
    return ids


def fantasy_pickups(records, as_of, window=14, n=10, exclude_top=150, established=None):
    """Under-the-radar categories pickups: strong recent category value, growing role, and not
    already one of the obvious fantasy names (this season's top values or last season's scorers)."""
    since = (Date.fromisoformat(as_of) - timedelta(days=window - 1)).isoformat()
    before = [r for r in records if r["date"] < since]
    recent = [r for r in records if r["date"] >= since]
    season_all = S.skaters(records)
    S.category_values(season_all, min_gp=3)
    obvious = {p["id"] for p in sorted((p for p in season_all.values() if "value" in p),
                                       key=lambda p: -p["value"])[:exclude_top]}
    obvious |= set(established or ())
    rec = S.skaters(recent)
    pool = S.category_values(rec, min_gp=3)
    base = S.skaters(before)
    picks = []
    for p in pool:
        if p["id"] in obvious:
            continue
        b = base.get(p["id"])
        toi_up = (p["toi_gp"] - b["toi_gp"]) if b and b["gp"] >= 2 else 0.0
        pp_up = (p["toipp_gp"] - b["toipp_gp"]) if b and b["gp"] >= 2 else 0.0
        score = p["value"] + 0.5 * max(0, toi_up / 120) + 0.8 * max(0, pp_up / 60)
        picks.append((score, p, toi_up, pp_up))
    picks.sort(key=lambda x: -x[0])
    out = []
    for score, p, toi_up, pp_up in picks[:n]:
        out.append({**p, "why": _why(p, toi_up, pp_up), "score": score})
    return out, since


def _why(p, toi_up, pp_up):
    r = p["rates"]
    if pp_up >= 60:
        return f"PP time +{_mmss(pp_up)} (now {_mmss(p['toipp_gp'])})"
    if toi_up >= 120:
        return f"Ice time +{_mmss(toi_up)} (now {_mmss(p['toi_gp'])})"
    best = max(S.CATS, key=lambda c: p["z"][c])
    if best in ("HIT", "BLK"):
        return f"{r['HIT']:.1f} hits + {r['BLK']:.1f} blocks a game"
    if best == "SOG":
        return f"{r['SOG']:.1f} shots a game, {p['ixG'] / p['gp']:.2f} xG"
    words = {"G": "goals", "A": "assists", "PPP": "PP points"}
    return f"{r[best]:.2f} {words[best]} a game"


def fantasy_post(records, as_of, established=None):
    picks, since = fantasy_pickups(records, as_of, established=established)
    if not picks:
        return None
    label = _label(as_of)
    rows = []
    for i, p in enumerate(picks, 1):
        r = p["rates"]
        rows.append({"rank": i, "logo": p["team"], "name": p["name"],
                     "tag": f"{_pos(p['pos'])}  ·  {p['why']}", "tag_color": C["body"],
                     "c1": f"{int(p['G'])}-{int(p['A'])}-{int(p['PPP'])}",
                     "c2": f"{r['SOG']:.1f}/{r['HIT']:.1f}/{r['BLK']:.1f}",
                     "value": f"{p['score']:+.1f}", "value_color": FANTASY})
    top3 = picks[:3]
    cards = [(f"PICKUP #{i}", p["name"], p["why"], p["team"], _team_col(p["team"]))
             for i, p in enumerate(top3, 1)]
    cover = _cover(f"FANTASY  //  {label}", "CATEGORIES LEAGUES", "WAIVER WIRE", "PICKUPS",
                   "Under-the-radar adds: G · A · PPP · SOG · HIT · BLK", FANTASY, cards, h=150)
    table = _table(f"FANTASY  //  {label}", "LAST 14 DAYS", "TOP 10 PICKUPS",
                   "Category value over the last two weeks, growing roles first",
                   ["PLAYER  ·  WHY", "G-A-PPP", "SOG/HIT/BLK", "SCORE"], rows, FANTASY, row_h=88,
                   note="Score = per-game category value over the last 14 days, plus a bonus for a "
                        "growing role. Excludes obvious names. Check your league.")
    caption = ("Waiver wire 🧲 under-the-radar adds for categories leagues (G, A, PPP, SOG, HIT, BLK), "
               f"based on the last two weeks:\n\n" +
               "".join(f"{i}. {p['name']} ({p['team']}, {_pos(p['pos'])}): {p['why']}\n"
                       for i, p in enumerate(picks[:5], 1)) +
               "\nSwipe for all 10. Check availability in your league first. Who are you adding? 👇")
    return [cover, table], caption, ["Fantasy pickups cover: top 3 adds", "Top 10 fantasy pickups"]
