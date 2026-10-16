"""Season-so-far intro posts (one-off): the real standings, hot hands vs. snakebitten, goalies.

All numbers come from a season_report.py snapshot (data/season_*.json), so the slides and
captions always match the data that was approved.
"""
import json
from datetime import date as Date
from pathlib import Path

from cards import (BAD, GOOD, M, W, H, C, F, _canvas, _ellipsize, _fit, _footer, _header,
                   _panel, _save, _signed, _num)
from metrics import team_color

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "data" / "season_2026-10-15.json"
SKATER_MIN_GP = 4
GOALIE_MIN_GP = 3
POSTS = {1: "standings", 2: "finishing", 3: "goalies"}


# --------------------------------------------------------------------- data ---
def load_season(path=DEFAULT_DATA):
    d = json.loads(Path(path).read_text())
    last = max(g["date"] for g in d["notable"])
    d["through"] = last
    d["through_label"] = Date.fromisoformat(last).strftime("%b %-d").upper()
    for t in d["teams"]:
        t["color"] = team_color(None, t["abbrev"])
        t["record"] = f"{int(t['w'])}-{int(t['l'])}-{int(t['otl'])}"
        t["pts_pct"] = 100 * (2 * t["w"] + t["otl"]) / (2 * t["gp"])
    for p in d["players"] + d["goalies"]:
        p["color"] = team_color(None, p["team"])
    return d


def _team(d, abbrev):
    return next(t for t in d["teams"] if t["abbrev"] == abbrev)


def _player(d, name, kind="players"):
    return next(p for p in d[kind] if p["name"] == name)


def standings(d):
    return sorted(d["teams"], key=lambda t: -t["xg5_pct"])


def finishers(d, n=10):
    pool = [p for p in d["players"] if p["gp"] >= SKATER_MIN_GP]
    hot = sorted(pool, key=lambda p: -p["gax"])[:n]
    cold = sorted(pool, key=lambda p: p["gax"])[:n]
    return hot, cold


def goalie_lists(d, n=10):
    pool = [g for g in d["goalies"] if g["gp"] >= GOALIE_MIN_GP]
    return (sorted(pool, key=lambda g: -g["gsax"])[:n], sorted(pool, key=lambda g: g["gsax"])[:n])


# ------------------------------------------------------------------ helpers ---
def _wrap(d, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _paragraph(d, xy, text, font, max_w, fill, spacing=1.38):
    x, y = xy
    size = font.size
    for line in _wrap(d, text, font, max_w):
        d.text((x, y), line, fill=fill, font=font)
        y += size * spacing
    return y


def _sub_header(d, data, accent):
    _header(d, "THE SEASON SO FAR", f"THROUGH {data['through_label']}  ·  {data['games']} GAMES",
            color=accent)


def _cover(data, accent, kicker, title, tagline, cards):
    img, d = _canvas(accent=accent)
    _sub_header(d, data, accent)
    d.text((M, 136), kicker, fill=C["muted"], font=F("bold", 56))
    d.text((M, 200), title, fill=C["text"], font=_fit(d, title, "bold", 116, W - 2 * M, 70))
    d.text((M, 340), tagline, fill=accent, font=_fit(d, tagline, "bold", 50, W - 2 * M, 30))
    y = 448
    h = 198 if len(cards) <= 3 else 170
    for label, name, sub, color in cards:
        _panel(d, [M - 24, y, W - M + 24, y + h])
        d.rectangle([M - 24, y + 24, M - 16, y + h - 24], fill=color)
        d.text((M + 8, y + 26), label, fill=C["muted"], font=F("semibold", 24))
        d.text((M + 8, y + 62), _ellipsize(d, name, F("bold", 52), W - 2 * M - 20), fill=C["text"],
               font=F("bold", 52))
        d.text((M + 8, y + 132), _ellipsize(d, sub, F("regular", 30), W - 2 * M - 20),
               fill=C["body"], font=F("regular", 30))
        y += h + 24
    d.text((W - M, H - 120), "SWIPE  →", fill=accent, font=F("bold", 30), anchor="ra")
    _footer(d)
    return img


def _explainer(data, accent, title, blocks):
    """blocks: list of (heading, text, heading_color)."""
    img, d = _canvas(accent=accent)
    _sub_header(d, data, accent)
    d.text((M, 104), title, fill=C["text"], font=_fit(d, title, "bold", 68, W - 2 * M, 44))
    y = 212
    for heading, text, color in blocks:
        d.text((M, y), heading, fill=color, font=F("bold", 32))
        y = _paragraph(d, (M, y + 46), text, F("regular", 29), W - 2 * M, C["body"]) + 30
    _footer(d)
    return img


# ------------------------------------------------------- post 1: standings ---
def _scatter(data):
    teams = data["teams"]
    img, d = _canvas()
    _sub_header(d, data, C["accent"])
    d.text((M, 100), "RECORD vs. PROCESS", fill=C["text"], font=F("bold", 68))
    d.text((M, 184), "Points % vs. share of 5v5 expected goals, every team", fill=C["muted"],
           font=F("regular", 26))
    x0, y0, x1, y1 = M + 46, 262, W - M - 4, 1150
    xmin, xmax, ymin, ymax = 30, 66, 0, 100

    def X(v):
        return x0 + (x1 - x0) * (v - xmin) / (xmax - xmin)

    def Y(v):
        return y1 - (y1 - y0) * (v - ymin) / (ymax - ymin)

    small = F("regular", 20)
    for v in range(0, 101, 25):
        d.line([(x0, Y(v)), (x1, Y(v))], fill="#20252E", width=1)
        d.text((x0 - 12, Y(v)), f"{v}%", fill=C["faint"], font=small, anchor="rm")
    for v in range(30, 67, 6):
        d.line([(X(v), y0), (X(v), y1)], fill="#20252E", width=1)
        d.text((X(v), y1 + 14), f"{v}%", fill=C["faint"], font=small, anchor="mt")
    d.line([(X(50), y0), (X(50), y1)], fill="#3A414C", width=2)
    d.line([(x0, Y(50)), (x1, Y(50))], fill="#3A414C", width=2)
    d.text(((x0 + x1) / 2, y1 + 46), "5V5 EXPECTED GOALS SHARE  →  controlling play",
           fill=C["muted"], font=F("semibold", 22), anchor="mt")
    q = F("bold", 24)
    d.text((x1 - 12, y0 + 12), "WINNING + DRIVING PLAY", fill=GOOD, font=q, anchor="ra")
    d.text((x0 + 12, y0 + 12), "WINNING ANYWAY", fill="#E3B341", font=q)
    d.text((x1 - 12, y1 - 12), "DESERVE BETTER", fill=C["stat"], font=q, anchor="rb")
    d.text((x0 + 12, y1 - 12), "IN TROUBLE", fill=BAD, font=q, anchor="lb")

    lf = F("bold", 22)
    dots = [(t, X(t["xg5_pct"]), Y(t["pts_pct"])) for t in teams]
    obstacles = [(cx - 11, cy - 11, cx + 11, cy + 11) for _, cx, cy in dots]
    # crowded points first, so they get the closest label spots
    crowd = lambda item: -sum(1 for _, x, y in dots if abs(x - item[1]) < 90 and abs(y - item[2]) < 40)
    labels = []
    for t, cx, cy in sorted(dots, key=crowd):
        tw = d.textlength(t["abbrev"], font=lf)
        best = None
        for r in (0, 1, 2, 3):
            dx, dy = 14 + 34 * r, 14 + 26 * r
            cands = [(cx + dx, cy - 13), (cx - dx - tw, cy - 13), (cx - tw / 2, cy - dy - 26),
                     (cx - tw / 2, cy + dy), (cx + dx * .7, cy - dy * .9 - 20),
                     (cx + dx * .7, cy + dy * .9 - 6), (cx - dx * .7 - tw, cy - dy * .9 - 20),
                     (cx - dx * .7 - tw, cy + dy * .9 - 6)]
            for lx, ly in cands:
                box = (lx - 3, ly - 1, lx + tw + 3, ly + 27)
                if box[0] < x0 + 4 or box[2] > x1 - 4 or box[1] < y0 + 44 or box[3] > y1 - 44:
                    continue
                if not any(_overlap(box, b) for b in obstacles):
                    best = (box, r)
                    break
            if best:
                break
        if best is None:
            best = ((cx + 14, cy - 13, cx + 14 + tw, cy + 13), 0)
        box, r = best
        obstacles.append(box)
        labels.append((t, cx, cy, box, r))
    for t, cx, cy, box, r in labels:
        if r:  # leader line from dot to the label
            lx = min(max(cx, box[0]), box[2])
            ly = min(max(cy, box[1]), box[3])
            d.line([(cx, cy), (lx, ly)], fill="#4A525E", width=2)
    for t, cx, cy in dots:
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=t["color"], outline=C["bg"], width=2)
    for t, cx, cy, box, r in labels:
        d.text((box[0] + 3, box[1] + 1), t["abbrev"], fill=t["color"], font=lf)
    _footer(d)
    return img


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _share_color(v):
    return GOOD if v >= 55 else BAD if v <= 45 else C["text"]


def _standings_list(data, teams, first_rank, title):
    img, d = _canvas()
    _sub_header(d, data, C["accent"])
    d.text((M, 100), title, fill=C["text"], font=F("bold", 64))
    d.text((M, 178), "Ranked by share of 5v5 expected goals (all games so far)", fill=C["muted"],
           font=F("regular", 26))
    cols = [W - M - 390, W - M - 240]
    hf = F("semibold", 20)
    y = 240
    d.text((M + 66, y), "TEAM", fill=C["faint"], font=hf)
    d.text((cols[0], y), "RECORD", fill=C["faint"], font=hf, anchor="ma")
    d.text((cols[1], y), "GOAL DIFF", fill=C["faint"], font=hf, anchor="ma")
    d.text((W - M, y), "5V5 xG%", fill=C["faint"], font=hf, anchor="ra")
    y += 38
    row_h = 60
    for i, t in enumerate(teams):
        rank = first_rank + i
        if rank % 2 == 1:
            d.rounded_rectangle([M - 20, y - 6, W - M + 20, y + row_h - 8], radius=10, fill="#161A21")
        d.text((M, y + 6), str(rank), fill=C["muted"], font=F("bold", 30))
        d.rectangle([M + 50, y + 8, M + 56, y + 40], fill=t["color"])
        name_f = F("bold", 30)
        d.text((M + 66, y + 6), _ellipsize(d, t["name"], name_f, cols[0] - M - 150), fill=C["text"],
               font=name_f)
        d.text((cols[0], y + 8), t["record"], fill=C["body"], font=F("regular", 28), anchor="ma")
        gd = int(t["goal_diff"])
        gd_s = f"+{gd}" if gd > 0 else str(gd).replace("-", "−")
        d.text((cols[1], y + 8), gd_s, fill=C["body"], font=F("regular", 28), anchor="ma")
        d.text((W - M, y + 2), f"{t['xg5_pct']:.1f}%", fill=_share_color(t["xg5_pct"]),
               font=F("bold", 38), anchor="ra")
        y += row_h
    _footer(d)
    return img


def standings_post(data):
    s = standings(data)
    best, worst = s[0], s[-1]
    cover = _cover(data, C["accent"], "THE REAL", "STANDINGS", "Who's actually driving play?", [
        ("BEST AT 5-ON-5", best["name"], f"{best['xg5_pct']:.1f}% of 5v5 xG  ·  record {best['record']}",
         best["color"]),
        ("WORST AT 5-ON-5", worst["name"],
         f"{worst['xg5_pct']:.1f}% of 5v5 xG  ·  record {worst['record']}", worst["color"]),
        ("SAMPLE", f"{data['games']} games, {len(data['teams'])} teams",
         "Every shot run through our expected-goals model", C["muted"]),
    ])
    njd, car, uta, vgk = (_team(data, a) for a in ("NJD", "CAR", "UTA", "VGK"))
    sea, bos, phi = (_team(data, a) for a in ("SEA", "BOS", "PHI"))
    explainer = _explainer(data, C["accent"], "WHAT IT TELLS US", [
        ("5V5 xG SHARE", "Every unblocked shot gets a chance of going in, based on where it came "
         "from, the shot type, rebounds, rushes and more. A team's share of those expected goals at "
         "5-on-5 shows who's controlling play, and early in a season it says more about what's "
         "coming than the standings do.", C["stat"]),
        (f"NJD: {njd['xg5_pct']:.1f}%, ONLY {njd['record']}",
         f"The best process in the league. Goal differential {int(njd['goal_diff'])} on an expected "
         f"+{njd['xg_diff']:.2f}. The bounces are due.", GOOD),
        (f"CAR · UTA · VGK: THE REAL DEAL",
         f"Winning and driving play: {car['record']}, {uta['record']} and {vgk['record']}, all above "
         f"{int(min(car['xg5_pct'], uta['xg5_pct'], vgk['xg5_pct']))}% of 5v5 xG.", GOOD),
        ("SEA · BOS: WATCH THIS SPACE",
         f"Seattle is {sea['record']} on {sea['xg5_pct']:.1f}% of 5v5 xG. Boston is +{int(bos['goal_diff'])} "
         f"in goals but only +{bos['xg_diff']:.2f} in expected goals. Both are riding hot finishing "
         "and goaltending.", "#E3B341"),
        (f"PHI: {phi['record']}, MOSTLY EARNED", f"The league's lowest share ({phi['xg5_pct']:.1f}%) "
         f"and an expected goal differential of {_num(phi['xg_diff'])}. Bad bounces have made it "
         "worse, but the process is the problem.", BAD),
    ])
    slides = [cover, _scatter(data), _standings_list(data, s[:16], 1, "RANKINGS: 1–16"),
              _standings_list(data, s[16:], 17, "RANKINGS: 17–32"), explainer]
    caption = (
        "Welcome to Chirp Analytics. 🏒📊\n\n"
        f"We're joining {data['games']} games into the season, so let's start with the standings "
        "that matter most this early: who's actually controlling play.\n\n"
        f"🟢 {best['name']}: {best['xg5_pct']:.1f}% of 5v5 expected goals, the league's best, "
        f"yet just {best['record']}.\n"
        f"🟢 {car['name']} ({car['record']}), {uta['name']} ({uta['record']}) and "
        f"{vgk['name']} ({vgk['record']}) are winning and driving play.\n"
        f"🟡 {sea['name']}: {sea['record']} on {sea['xg5_pct']:.1f}% of 5v5 xG.\n"
        f"🔴 {phi['name']}: {phi['record']} at {phi['xg5_pct']:.1f}%, last in the league.\n\n"
        "Every game from here on gets a full breakdown within minutes of the final horn. "
        "Follow along.\n\n"
        "Swipe for all 32 teams ➡️\n\n"
        f"Data: NHL play-by-play through {_long_date(data['through'])}. xG = expected goals, from our "
        "model trained on 237k NHL shots.\n\n"
        "#NHL #HockeyAnalytics #HockeyTwitter #AdvancedStats #NHLStats #ExpectedGoals")
    alts = ["The real standings: 5v5 expected goals share leaders and laggards",
            "Scatter plot of every team's points percentage against 5v5 expected goals share",
            "Teams ranked 1 to 16 by 5v5 expected goals share",
            "Teams ranked 17 to 32 by 5v5 expected goals share",
            "What 5v5 expected goals share tells us about the early season"]
    return slides, caption, alts


def _long_date(iso):
    return Date.fromisoformat(iso).strftime("%B %-d")


# --------------------------------------------- shared: actual vs expected bars ---
def _bars_slide(data, accent, title, subtitle, rows, scale, legend, header_cols):
    """rows: dicts name, tag, tag_color, actual, expected, value, value_color, extra."""
    img, d = _canvas(accent=accent)
    _sub_header(d, data, accent)
    d.text((M, 100), title, fill=C["text"], font=_fit(d, title, "bold", 68, W - 2 * M, 44))
    d.text((M, 182), subtitle, fill=C["muted"], font=F("regular", 26))
    bx0, bx1 = M + 410, W - M - 200
    hf = F("semibold", 20)
    y = 240
    d.text((M + 54, y), header_cols[0], fill=C["faint"], font=hf)
    # legend
    lx = bx0
    d.rectangle([lx, y + 4, lx + 26, y + 18], fill=accent)
    d.text((lx + 34, y), legend[0], fill=C["muted"], font=hf)
    lx += 34 + d.textlength(legend[0], font=hf) + 26
    d.rectangle([lx, y + 4, lx + 26, y + 18], outline=C["muted"], width=2)
    d.text((lx + 34, y), legend[1], fill=C["muted"], font=hf)
    d.text((W - M, y), header_cols[1], fill=C["faint"], font=hf, anchor="ra")
    y += 40
    row_h = 92

    def BX(v):
        return bx0 + (bx1 - bx0) * min(v, scale) / scale

    for i, r in enumerate(rows, 1):
        if i % 2 == 1:
            d.rounded_rectangle([M - 20, y - 8, W - M + 20, y + row_h - 12], radius=12, fill="#161A21")
        d.text((M, y + 16), str(i), fill=accent, font=F("bold", 34))
        name_f = F("bold", 30)
        d.text((M + 54, y + 2), _ellipsize(d, r["name"], name_f, bx0 - M - 80), fill=C["text"],
               font=name_f)
        d.text((M + 54, y + 42), r["tag"], fill=r["tag_color"], font=F("semibold", 22))
        # actual (filled) on top, expected (outline) below
        num_f = F("semibold", 22)
        ya, ye = y + 10, y + 44
        d.rounded_rectangle([bx0, ya, max(BX(r["actual"]), bx0 + 4), ya + 24], radius=5, fill=accent)
        d.text((max(BX(r["actual"]), bx0 + 4) + 10, ya + 12), r["actual_label"], fill=C["text"],
               font=num_f, anchor="lm")
        d.rounded_rectangle([bx0, ye, max(BX(r["expected"]), bx0 + 4), ye + 24], radius=5,
                            outline=C["muted"], width=2)
        d.text((max(BX(r["expected"]), bx0 + 4) + 10, ye + 12), r["expected_label"], fill=C["muted"],
               font=num_f, anchor="lm")
        d.text((W - M, y + 14), r["value"], fill=r["value_color"], font=F("bold", 42), anchor="ra")
        y += row_h
    _footer(d)
    return img


def _skater_rows(players, color):
    return [{"name": p["name"], "tag": f"{p['team']}  ·  {_pos(p['pos'])}  ·  {int(p['gp'])} GP",
             "tag_color": p["color"], "actual": p["G"], "actual_label": f"{int(p['G'])} G",
             "expected": p["ixG"], "expected_label": f"{p['ixG']:.2f} xG",
             "value": _signed(p["gax"]), "value_color": color} for p in players]


def _pos(p):
    return {"L": "LW", "R": "RW"}.get(p, p)


# -------------------------------------------------------- post 2: finishing ---
def finishing_post(data):
    hot, cold = finishers(data)
    kap = _player(data, "Kirill Kaprizov")
    bou = _player(data, "Evan Bouchard")
    jh = _player(data, "Jack Hughes")
    ixg_rank = 1 + sum(1 for p in data["players"] if p["ixG"] > jh["ixG"])
    scale = max(max(p["G"], p["ixG"]) for p in hot + cold) * 1.12
    cover = _cover(data, "#FF9F43", "HOT HANDS VS.", "SNAKEBITTEN", "Goals vs. expected goals", [
        ("RED HOT", kap["name"], f"{int(kap['G'])} goals on {kap['ixG']:.2f} expected  ·  "
         f"{_signed(kap['gax'])}", kap["color"]),
        ("BLUE-LINE SNIPER", bou["name"], f"{int(bou['G'])} goals on {bou['ixG']:.2f} expected, "
         "from the blue line", bou["color"]),
        ("DUE FOR GOALS", jh["name"], f"{int(jh['G'])} goals on {jh['ixG']:.2f} expected  ·  "
         f"#{ixg_rank} in xG", jh["color"]),
    ])
    s_hot = _bars_slide(data, GOOD, "RUNNING HOT", f"Most goals above expected (min. {SKATER_MIN_GP} games)",
                        _skater_rows(hot, GOOD), scale, ("GOALS", "EXPECTED"), ["PLAYER", "G − xG"])
    s_cold = _bars_slide(data, BAD, "SNAKEBITTEN", f"Furthest below expected (min. {SKATER_MIN_GP} games)",
                         _skater_rows(cold, BAD), scale, ("GOALS", "EXPECTED"), ["PLAYER", "G − xG"])
    explainer = _explainer(data, "#FF9F43", "SKILL OR LUCK?", [
        ("INDIVIDUAL xG", "Add up the chance of every unblocked shot a player takes going in and you "
         "get his expected goals: how many an average shooter would score from those exact looks.",
         C["stat"]),
        ("GOALS ABOVE EXPECTED", "Goals minus expected goals. Elite shooters beat their xG season "
         "after season, but over a handful of games most of the gap is hot and cold streaks.",
         C["stat"]),
        ("WHAT TO EXPECT", f"Usually the hot list cools and the cold list heats up. {jh['name']} has "
         f"the #{ixg_rank} expected-goals total in the league and just {int(jh['G'])} goals; players "
         "who keep getting those looks tend to start scoring.", GOOD),
        (f"THE EXCEPTION?", f"{kap['name']} is a career finisher, but {int(kap['G'])} goals on "
         f"{kap['ixG']:.2f} expected is a gap that rarely holds. {bou['name']} has scored on "
         f"{int(bou['G'])} of his {int(bou['SOG'])} shots on goal, from the blue line.", "#FF9F43"),
    ])
    caption = (
        "Who's finishing, and who's due? 🔥🥶\n\n"
        "Goals above expected = goals minus the expected goals from every shot a player took.\n\n"
        f"🔥 {kap['name']}: {int(kap['G'])} goals on {kap['ixG']:.2f} xG ({_signed(kap['gax'])}), "
        "the most above expected in the league.\n"
        f"🔥 {bou['name']}: {int(bou['G'])} goals on {bou['ixG']:.2f} xG, as a defenceman.\n"
        f"🥶 {cold[0]['name']}: {int(cold[0]['G'])} goals on {cold[0]['ixG']:.2f} xG.\n"
        f"🥶 {jh['name']}: {int(jh['G'])} goals on {jh['ixG']:.2f} xG, #{ixg_rank} in the league "
        "in expected goals.\n\n"
        "Over a few games most of these gaps are streaks, not skill. Our bet: the cold list starts "
        "scoring.\n\n"
        f"Data: NHL play-by-play through {_long_date(data['through'])}, min. {SKATER_MIN_GP} games.\n\n"
        "#NHL #HockeyAnalytics #ExpectedGoals #AdvancedStats #NHLStats #FantasyHockey")
    alts = ["Hot hands and snakebitten shooters: goals versus expected goals",
            "Top 10 skaters in goals above expected",
            "Bottom 10 skaters in goals above expected",
            "Explainer: individual expected goals and goals above expected"]
    return [cover, s_hot, s_cold, explainer], caption, alts


# ---------------------------------------------------------- post 3: goalies ---
def _goalie_rows(goalies, color):
    return [{"name": g["name"],
             "tag": f"{g['team']}  ·  {int(g['gp'])} GP  ·  {g['sv_pct']:.3f}".replace(" 0.", " ."),
             "tag_color": g["color"], "actual": g["goals_against"],
             "actual_label": f"{int(g['goals_against'])} GA",
             "expected": g["xga"], "expected_label": f"{g['xga']:.2f} xGA",
             "value": _signed(g["gsax"]), "value_color": color} for g in goalies]


def goalies_post(data):
    best, worst = goalie_lists(data)
    ull = _player(data, "Linus Ullmark", "goalies")
    ers = _player(data, "Samuel Ersson", "goalies")
    lan = _player(data, "Kevin Lankinen", "goalies")
    wolf = _player(data, "Dustin Wolf", "goalies")
    ott, cgy, van = _team(data, "OTT"), _team(data, "CGY"), _team(data, "VAN")
    scale = max(max(g["goals_against"], g["xga"]) for g in best + worst) * 1.12
    cover = _cover(data, C["stat"], "GOALIES", "STEALING GAMES", "Goals saved above expected", [
        ("THE BRICK WALL", ull["name"], f"{_signed(ull['gsax'])} GSAx  ·  {ull['sv_pct']:.3f} SV%"
         .replace(" 0.", " ."), ull["color"]),
        ("CARRYING OTTAWA", f"{ott['name']}: {ott['record']}",
         f"despite only {ott['xg5_pct']:.1f}% of 5v5 expected goals", ott["color"]),
        ("ROUGH START", lan["name"], f"{int(lan['goals_against'])} goals on {lan['xga']:.2f} expected  ·  "
         f"{lan['sv_pct']:.3f} SV%".replace(" 0.", " ."), lan["color"]),
    ])
    s_best = _bars_slide(data, GOOD, "STEALING GAMES",
                         f"Most goals saved above expected (min. {GOALIE_MIN_GP} games)",
                         _goalie_rows(best, GOOD), scale, ("ALLOWED", "EXPECTED"), ["GOALIE", "GSAx"])
    s_worst = _bars_slide(data, BAD, "LEAKING GOALS",
                          f"Fewest goals saved above expected (min. {GOALIE_MIN_GP} games)",
                          _goalie_rows(worst, BAD), scale, ("ALLOWED", "EXPECTED"), ["GOALIE", "GSAx"])
    explainer = _explainer(data, C["stat"], "WHY IT MATTERS", [
        ("GSAx", "Goals saved above expected: the expected goals a goalie faced minus the goals he "
         "allowed. Unlike save %, it accounts for how dangerous the shots were.", C["stat"]),
        ("ONE TEAM, TWO STORIES", f"Ottawa: {ull['name']} is {_signed(ull['gsax'])}, "
         f"{ers['name']} is {_signed(ers['gsax'])}. Same defence in front of them.", GOOD),
        (f"CALGARY: {cgy['record']}", f"The Flames are giving up about as much as they create "
         f"({cgy['xg5_pct']:.1f}% of 5v5 xG), but {wolf['name']} is {_signed(wolf['gsax'])}. "
         f"Their goal differential ({str(int(cgy['goal_diff'])).replace('-', '−')}) is "
         f"{abs(cgy['luck']):.2f} goals worse than their expected goals say. If the goaltending "
         "steadies, the results should follow.", BAD),
        (f"VANCOUVER: {van['record']}", f"{lan['name']} has allowed {int(lan['goals_against'])} goals "
         f"on {lan['xga']:.2f} expected, and the team in front of him has "
         f"{van['xg5_pct']:.1f}% of 5v5 xG. That's both ends.", BAD),
    ])
    caption = (
        "Goalies stealing games, and goalies giving them away. 🧱🥅\n\n"
        "GSAx = expected goals faced minus goals allowed. It rewards stopping the hard ones.\n\n"
        f"🧱 {ull['name']}: {_signed(ull['gsax'])} GSAx, {ull['sv_pct']:.3f}".replace(" 0.", " .") +
        f". The {ott['name']} are {ott['record']} with {ott['xg5_pct']:.1f}% of 5v5 xG.\n"
        f"🧱 {best[1]['name']}: {_signed(best[1]['gsax'])}.\n"
        f"🚨 {lan['name']}: {int(lan['goals_against'])} goals on {lan['xga']:.2f} expected "
        f"({_signed(lan['gsax'])}).\n"
        f"🚨 {wolf['name']}: {_signed(wolf['gsax'])}, and the {cgy['name']} are {cgy['record']}.\n\n"
        "Swipe for the top and bottom 10 ➡️\n\n"
        f"Data: NHL play-by-play through {_long_date(data['through'])}, min. {GOALIE_MIN_GP} games.\n\n"
        "#NHL #HockeyAnalytics #Goalies #GSAx #AdvancedStats #NHLStats")
    alts = ["Goalies stealing games: goals saved above expected leaders",
            "Top 10 goalies in goals saved above expected",
            "Bottom 10 goalies in goals saved above expected",
            "Explainer: goals saved above expected, with Ottawa, Calgary and Vancouver examples"]
    return [cover, s_best, s_worst, explainer], caption, alts


BUILDERS = {"standings": standings_post, "finishing": finishing_post, "goalies": goalies_post}


def render_intro(which, data=None):
    """Render one intro post. Returns (paths, caption, alt_texts)."""
    data = data or load_season()
    slides, caption, alts = BUILDERS[which](data)
    paths = [_save(img, f"intro_{which}_{i}.jpg") for i, img in enumerate(slides, 1)]
    return paths, caption, alts
