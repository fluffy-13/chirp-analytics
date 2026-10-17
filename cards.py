"""Carousel slides (1080x1350 JPEG): per-game breakdown, per-team breakdown, weekly rankings."""
import logging
from datetime import date as Date
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

import logos
from config import IG_HANDLE, OUTPUT_DIR, PALETTE as C
from renderer import _font as _raw_font

log = logging.getLogger(__name__)

W, H = 1080, 1350
M = 72
GOOD, BAD = "#00FF88", "#FF7B72"
FOOTER = f"{IG_HANDLE}  |  Data: NHL play-by-play  |  Unofficial · not affiliated with the NHL"


@lru_cache(maxsize=None)
def F(weight, size):
    return _raw_font(weight, size)


# ------------------------------------------------------------------ helpers ---
def _canvas(accent=C["accent"]):
    img = Image.new("RGB", (W, H), C["bg"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=accent)
    return img, d


def _footer(d):
    d.text((M, H - 62), FOOTER, fill=C["faint"], font=F("regular", 22))


def _header(d, left, right, color=C["accent"]):
    d.text((M, 50), left, fill=color, font=F("semibold", 28))
    d.text((W - M, 50), right, fill=C["muted"], font=F("semibold", 28), anchor="ra")


def _fit(d, text, weight, size, max_w, min_size=20):
    while size > min_size and d.textlength(text, font=F(weight, size)) > max_w:
        size -= 2
    return F(weight, size)


def _ellipsize(d, text, font, max_w):
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _pretty_date(iso):
    try:
        dt = Date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return dt.strftime("%a %b %-d, %Y").upper()


def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _distinct(c1, c2):
    """Keep the two teams visually distinct on charts and bars."""
    a, b = _hex_rgb(c1), _hex_rgb(c2)
    if sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 < 110:
        return c1, "#C9D1D9"
    return c1, c2


def _panel(d, box, radius=18):
    d.rounded_rectangle(box, radius=radius, fill=C["panel"], outline=C["panel_border"], width=2)


def _pct(v):
    return "–" if v is None else f"{v:.0f}%"


def _num(v):
    """2 decimals with a true minus sign."""
    return f"{v:.2f}".replace("-", "−")


def _signed(v):
    return f"+{v:.2f}" if v > 0 else f"{v:.2f}".replace("-", "−")


def _skater_line(p):
    return f"{p['G']}G  {p['A']}A  ·  {p['SOG']} SOG  ·  {p['ixG']:.2f} xG"


def _goalie_line(g):
    sv = f"{g['sv_pct']:.3f}".lstrip("0") if g["sv_pct"] is not None else "–"
    return f"{g['saves']}/{g['shots_against']} SV  ·  {sv}  ·  {_signed(g['gsax'])} GSAx"


def _out_path(name):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / name


def _save(img, name):
    path = _out_path(name)
    img.save(path, "JPEG", quality=92)
    return path


# ---------------------------------------------------------------- game slide ---
def _xg_chart(d, game, box, away_c, home_c):
    x0, y0, x1, y1 = box
    length = max(game["game_length"], 3600)
    regulation = 3600
    cum = {"away": [(0, 0.0)], "home": [(0, 0.0)]}
    for ev in sorted(game["timeline"], key=lambda e: e["t"]):
        pts = cum[ev["side"]]
        pts.append((ev["t"], pts[-1][1] + ev["xg"]))
    totals = {k: v[-1][1] for k, v in cum.items()}
    ymax = max(1.0, max(totals.values()) * 1.15)

    def X(t):
        return x0 + (x1 - x0) * t / length

    def Y(v):
        return y1 - (y1 - y0) * v / ymax

    small = F("regular", 20)
    # horizontal gridlines every 1.0 xG
    step = 1 if ymax <= 6 else 2
    v = 0
    while v <= ymax:
        d.line([(x0, Y(v)), (x1, Y(v))], fill="#262C36", width=1)
        d.text((x0 - 12, Y(v)), f"{v:g}", fill=C["faint"], font=small, anchor="rm")
        v += step
    # period dividers + labels
    marks = [0, 1200, 2400, 3600] + ([length] if length > regulation else [])
    labels = ["1ST", "2ND", "3RD", "OT"]
    for i in range(len(marks) - 1):
        if i > 0:
            d.line([(X(marks[i]), y0), (X(marks[i]), y1)], fill="#30363D", width=2)
        mid = (marks[i] + marks[i + 1]) / 2
        d.text((X(mid), y1 + 14), labels[min(i, 3)], fill=C["muted"], font=small, anchor="mt")

    for side, color in (("away", away_c), ("home", home_c)):
        pts = cum[side] + [(length, totals[side])]
        line = []
        for (t_a, v_a), (t_b, _) in zip(pts, pts[1:]):
            line += [(X(t_a), Y(v_a)), (X(t_b), Y(v_a))]
        for i in range(0, len(line) - 1):
            d.line([line[i], line[i + 1]], fill=color, width=5)
    # goal markers on top
    running = {"away": 0.0, "home": 0.0}
    for ev in sorted(game["timeline"], key=lambda e: e["t"]):
        running[ev["side"]] += ev["xg"]
        if ev["goal"]:
            cx, cy = X(ev["t"]), Y(running[ev["side"]])
            color = away_c if ev["side"] == "away" else home_c
            d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=color, outline="#FFFFFF", width=3)


def _stat_rows(d, rows, top, away_c, home_c):
    y = top
    label_f, val_f = F("semibold", 22), F("bold", 34)
    for label, a_val, h_val, a_num, h_num in rows:
        d.text((W / 2, y + 6), label, fill=C["muted"], font=label_f, anchor="mt")
        d.text((M, y), a_val, fill=C["text"], font=val_f)
        d.text((W - M, y), h_val, fill=C["text"], font=val_f, anchor="ra")
        bar_y = y + 48
        if a_num is None:  # no bar for rows where a split would mislead (e.g. 0 vs 1 PP goals)
            y += 74
            continue
        d.rounded_rectangle([M, bar_y, W - M, bar_y + 10], radius=5, fill="#262C36")
        total = (a_num or 0) + (h_num or 0)
        if total > 0:
            split = M + (W - 2 * M) * a_num / total
            d.rounded_rectangle([M, bar_y, max(split - 3, M + 1), bar_y + 10], radius=5, fill=away_c)
            d.rounded_rectangle([min(split + 3, W - M - 1), bar_y, W - M, bar_y + 10], radius=5,
                                fill=home_c)
        y += 74
    return y


def render_game_slide(game):
    a, h = game["teams"]["away"], game["teams"]["home"]
    away_c, home_c = _distinct(a["color"], h["color"])
    img, d = _canvas()
    status = {"OT": "FINAL · OT", "SO": "FINAL · SHOOTOUT"}.get(game["outcome"], "FINAL")
    _header(d, f"{_game_label(game)}  //  {status}", _pretty_date(game["date"]))

    # score block
    top = 118
    for t, color, align, x in ((a, away_c, "la", M), (h, home_c, "ra", W - M)):
        if not logos.paste(img, t["abbrev"], (x, top - 6), height=104, max_w=230,
                           anchor="lt" if align == "la" else "rt"):
            d.text((x, top), t["abbrev"], fill=color, font=F("bold", 96), anchor=align)
        d.text((x, top + 112), t["common_name"].upper(), fill=C["muted"], font=F("semibold", 26),
               anchor=align)
    score_f = F("bold", 140)
    a_col = C["text"] if a["won"] else C["muted"]
    h_col = C["text"] if h["won"] else C["muted"]
    d.text((W / 2 - 46, top - 18), str(a["score"]), fill=a_col, font=score_f, anchor="ra")
    d.text((W / 2, top + 66), "–", fill=C["faint"], font=F("bold", 64), anchor="mm")
    d.text((W / 2 + 46, top - 18), str(h["score"]), fill=h_col, font=score_f, anchor="la")

    # xG panel
    p_top, p_bot = 290, 652
    _panel(d, [M - 24, p_top, W - M + 24, p_bot])
    d.text((M, p_top + 26), "EXPECTED GOALS (ALL SITUATIONS)", fill=C["text"], font=F("semibold", 24))
    d.text((W - M, p_top + 16), f"{h['xg']:.2f}", fill=home_c, font=F("bold", 44), anchor="ra")
    hx = d.textlength(f"{h['xg']:.2f}", font=F("bold", 44))
    d.text((W - M - hx - 18, p_top + 22), "–", fill=C["muted"], font=F("bold", 34), anchor="ra")
    d.text((W - M - hx - 54, p_top + 16), f"{a['xg']:.2f}", fill=away_c, font=F("bold", 44),
           anchor="ra")
    _xg_chart(d, game, (M + 30, p_top + 92, W - M - 6, p_bot - 58), away_c, home_c)
    d.text((M, p_bot - 34), "● = goal", fill=C["faint"], font=F("regular", 20))

    # stat comparison rows
    pp = lambda t: f"{t['pp_goals']}/{t['pp_opps']}"
    rows = [
        ("SHOTS ON GOAL", str(a["sog"]), str(h["sog"]), a["sog"], h["sog"]),
        ("5V5 SHOT ATTEMPTS", str(a["cf5"]), str(h["cf5"]), a["cf5"], h["cf5"]),
        ("HIGH-DANGER CHANCES", str(a["hd"]), str(h["hd"]), a["hd"], h["hd"]),
        ("POWER PLAY", pp(a), pp(h), None, None),
        ("FACEOFFS WON", _pct(a["fo_pct"]), _pct(h["fo_pct"]), a["fow"], h["fow"]),
    ]
    y = _stat_rows(d, rows, 680, away_c, home_c)

    # three stars
    y += 4
    d.text((M, y), "THREE STARS", fill=C["text"], font=F("semibold", 24))
    y += 44
    for i, p in enumerate(game["stars"], 1):
        color = away_c if p["team_side"] == "away" else home_c
        d.text((M, y), f"{i}", fill=C["accent"], font=F("bold", 32))
        name_f = F("bold", 32)
        name = _ellipsize(d, p["name"], name_f, 380)
        d.text((M + 40, y), name, fill=C["text"], font=name_f)
        nx = M + 40 + d.textlength(name, font=name_f) + 14
        d.text((nx, y + 6), p["team_abbrev"], fill=color, font=F("semibold", 24))
        line = _goalie_line(p) if p["position"] == "G" else _skater_line(p)
        d.text((W - M, y + 6), line, fill=C["body"], font=F("regular", 24), anchor="ra")
        y += 48
    _footer(d)
    return img


# ---------------------------------------------------------------- team slide ---
def _tile(d, box, value, label, value_color=C["text"]):
    _panel(d, box, radius=16)
    x0, y0, x1, y1 = box
    d.text(((x0 + x1) / 2, y0 + 30), value, fill=value_color, font=F("bold", 58), anchor="mt")
    d.text(((x0 + x1) / 2, y1 - 26), label, fill=C["muted"], font=F("semibold", 20), anchor="mb")


def _share_color(v):
    if v is None:
        return C["text"]
    return GOOD if v >= 55 else BAD if v <= 45 else C["text"]


def render_team_slide(game, side):
    t = game["teams"][side]
    opp = game["teams"]["home" if side == "away" else "away"]
    color = t["color"]
    img, d = _canvas(accent=color)
    _header(d, "TEAM BREAKDOWN", _pretty_date(game["date"]), color=color)

    lw = logos.paste(img, t["abbrev"], (W - M, 96), height=170, max_w=230, anchor="rt")
    d.text((M, 104), t["common_name"].upper(), fill=color,
           font=_fit(d, t["common_name"].upper(), "bold", 104, W - 2 * M - (lw + 30 if lw else 0), 60))
    place = t["name"].replace(t["common_name"], "").strip() or t["abbrev"]
    d.text((M, 226), place.upper(), fill=C["muted"], font=F("semibold", 26))
    res = "W" if t["won"] else ("OTL" if game["outcome"] in ("OT", "SO") else "L")
    where = "@" if not t["is_home"] else "vs"
    extra = {"OT": " (OT)", "SO": " (SO)"}.get(game["outcome"], "")
    d.text((M, 272), f"{res}  {t['score']}–{t['opp_score']}{extra}  {where} {opp['abbrev']}",
           fill=C["text"], font=F("bold", 44))

    # tiles 3 x 2
    pp = f"{t['pp_goals']}/{t['pp_opps']}"
    tiles = [
        (f"{t['xg']:.2f}", "EXPECTED GOALS", C["text"]),
        (_pct(t["xg5_pct"]), "5V5 xG SHARE", _share_color(t["xg5_pct"])),
        (_pct(t["cf5_pct"]), "5V5 SHOT SHARE", _share_color(t["cf5_pct"])),
        (str(t["sog"]), "SHOTS ON GOAL", C["text"]),
        (str(t["hd"]), "HIGH-DANGER CHANCES", C["text"]),
        (pp, "POWER PLAY", C["text"]),
    ]
    tw, th, gap = (W - 2 * M - 2 * 20) / 3, 156, 20
    for i, (val, label, vc) in enumerate(tiles):
        r, c = divmod(i, 3)
        x0 = M + c * (tw + gap)
        y0 = 360 + r * (th + gap)
        _tile(d, [x0, y0, x0 + tw, y0 + th], val, label, vc)

    # top performers
    y = 724
    d.text((M, y), "TOP PERFORMERS", fill=C["text"], font=F("semibold", 24))
    d.text((W - M, y), "GAME SCORE", fill=C["muted"], font=F("semibold", 20), anchor="ra")
    y += 46
    skaters = sorted((p for p in game["players"] if p["team_side"] == side),
                     key=lambda p: p["game_score"], reverse=True)[:3]
    for p in skaters:
        name_f = F("bold", 34)
        d.text((M, y), _ellipsize(d, p["name"], name_f, 640), fill=C["text"], font=name_f)
        d.text((M, y + 46), f"{p['position']}  ·  {_skater_line(p)}  ·  {p['toi']} TOI",
               fill=C["body"], font=F("regular", 24))
        d.text((W - M, y + 6), _num(p["game_score"]), fill=color, font=F("bold", 52), anchor="ra")
        y += 104

    # goalies
    y += 10
    d.text((M, y), "IN NET", fill=C["text"], font=F("semibold", 24))
    y += 46
    goalies = [g for g in game["goalies"] if g["team_side"] == side]
    for g in goalies[:2]:
        dec = {"W": "WIN", "L": "LOSS", "O": "OT LOSS"}.get(g.get("decision") or "", "")
        name_f = F("bold", 32 if len(goalies) > 1 else 34)
        d.text((M, y), _ellipsize(d, g["name"], name_f, 560), fill=C["text"], font=name_f)
        if dec:
            d.text((W - M, y + 6), dec, fill=C["muted"], font=F("semibold", 22), anchor="ra")
        gs_col = GOOD if g["gsax"] > 0.5 else BAD if g["gsax"] < -0.5 else C["body"]
        d.text((M, y + 44), _goalie_line(g), fill=gs_col if len(goalies) == 1 else C["body"],
               font=F("regular", 26))
        y += 92 if len(goalies) > 1 else 100
    _footer(d)
    return img


# -------------------------------------------------------------- impact slide ---
# Game Score parts, in stacking order (labels shown in the legend)
PARTS = [("scoring", "GOALS + ASSISTS", "#00FF88"),
         ("shots", "SHOTS", "#58A6FF"),
         ("play5", "5V5 SHOT ATTEMPTS", "#B392F0"),
         ("goals5", "5V5 GOALS ON ICE", "#E3B341"),
         ("other", "BLOCKS · FO · PEN.", "#8B949E")]
DESERVED_XG = 0.4     # on-ice 5v5 xG +/- that counts as winning the chances
DESERVED_IXG = 0.5    # or this much individual xG
OUTCHANCED_XG = -0.4


def impact_flag(p):
    """Process vs. results: no points despite winning the chances, or points despite losing them."""
    pts = p["G"] + p["A"]
    xpm = p.get("xg_pm5", 0)
    # won his chances, or got plenty of looks himself without his line losing the chances
    if pts == 0 and (xpm >= DESERVED_XG or (p["ixG"] >= DESERVED_IXG and xpm >= 0)):
        return "DESERVED MORE", C["stat"]
    if pts > 0 and xpm <= OUTCHANCED_XG:
        return "OUTCHANCED", "#E3B341"
    return None


def _short_name(d, name, font, max_w):
    """Full name if it fits, else 'J. Pageau', else ellipsized."""
    if d.textlength(name, font=font) <= max_w:
        return name
    parts = name.split()
    if len(parts) > 1:
        short = f"{parts[0][0]}. {' '.join(parts[1:])}"
        if d.textlength(short, font=font) <= max_w:
            return short
        name = short
    return _ellipsize(d, name, font, max_w)


def _arrow(d, x, y, up, color, size=10):
    if up:
        d.polygon([(x, y + size), (x + size, y + size), (x + size / 2, y)], fill=color)
    else:
        d.polygon([(x, y), (x + size, y), (x + size / 2, y + size)], fill=color)


def render_impact_slide(game, side, context=None):
    """Every skater's Game Score split into what drove it, with season context."""
    context = context or {}
    t = game["teams"][side]
    opp = game["teams"]["home" if side == "away" else "away"]
    color = t["color"]
    img, d = _canvas(accent=color)
    _header(d, "PLAYER IMPACT", _pretty_date(game["date"]), color=color)

    res = "W" if t["won"] else ("OTL" if game["outcome"] in ("OT", "SO") else "L")
    where = "@" if not t["is_home"] else "vs"
    extra = {"OT": " (OT)", "SO": " (SO)"}.get(game["outcome"], "")
    title = t["common_name"].upper()
    lw = logos.paste(img, t["abbrev"], (M, 140), height=78, max_w=110, anchor="lm")
    tx = M + (lw + 22 if lw else 0)
    result = f"{res}  {t['score']}–{t['opp_score']}{extra}  {where} {opp['abbrev']}"
    rw = d.textlength(result, font=F("bold", 40))
    tf = _fit(d, title, "bold", 72, W - M - rw - 36 - tx, 36)
    d.text((tx, 140), title, fill=color, font=tf, anchor="lm")
    d.text((W - M, 140), result, fill=C["text"], font=F("bold", 40), anchor="rm")
    d.text((M, 186), "Every skater's Game Score, split into what drove it", fill=C["muted"],
           font=F("regular", 24))

    # legend
    lf = F("semibold", 17)
    x, y = M, 232
    for _, label, c in PARTS:
        d.rounded_rectangle([x, y + 2, x + 18, y + 18], radius=4, fill=c)
        d.text((x + 25, y), label, fill=C["body"], font=lf)
        x += 25 + d.textlength(label, font=lf) + 22
    has_ctx = any(p["player_id"] in context for p in game["players"] if p["team_side"] == side)

    skaters = sorted((p for p in game["players"] if p["team_side"] == side),
                     key=lambda p: p["game_score"], reverse=True)
    goalies = [g for g in game["goalies"] if g["team_side"] == side]
    name_x, xg_x, bx0, bx1, gs_x = M, M + 438, M + 470, W - M - 120, W - M - 26

    hy = 274
    hf = F("semibold", 18)
    d.text((name_x, hy), "SKATER", fill=C["faint"], font=hf)
    d.text((xg_x, hy), "5V5 xG±", fill=C["faint"], font=hf, anchor="ra")
    d.text((gs_x + 26, hy), "GAME SCORE", fill=C["faint"], font=hf, anchor="ra")
    if has_ctx:
        mid = (bx0 + bx1) / 2
        d.text((mid + 14, hy), "= HIS SEASON AVG", fill=C["faint"], font=hf, anchor="ma")
        lw = d.textlength("= HIS SEASON AVG", font=hf)
        tx = mid + 14 - lw / 2 - 16
        d.line([(tx, hy - 2), (tx, hy + 20)], fill="#FFFFFF", width=3)

    # bar scale: shared across rows, zero placed so the biggest negative and positive both fit
    neg = max([-sum(v for v in p["gs_parts"].values() if v < 0) for p in skaters] + [0.5])
    pos = max([sum(v for v in p["gs_parts"].values() if v > 0) for p in skaters] + [1.5])
    avgs = [context[p["player_id"]]["avg"] for p in skaters if p["player_id"] in context]
    neg = max([neg] + [-a for a in avgs])
    pos = max([pos] + avgs)
    ppu = (bx1 - bx0) / (neg + pos)
    zero = bx0 + neg * ppu

    top = 308
    bottom = 1150 - 40 * max(0, len(goalies) - 1)
    row_h = min(48, (bottom - top) / max(len(skaters), 1))
    d.line([(zero, top - 6), (zero, top + row_h * len(skaters) - 4)], fill="#3A414C", width=2)
    y = top
    for i, p in enumerate(skaters):
        if i % 2 == 0:
            d.rounded_rectangle([M - 20, y, W - M + 20, y + row_h - 4], radius=8, fill="#161A21")
        cy = y + (row_h - 4) / 2
        # name + flag
        pos_s = {"L": "LW", "R": "RW"}.get(p["position"], p["position"])
        d.text((name_x, cy), pos_s, fill=C["muted"], font=F("semibold", 18), anchor="lm")
        flag = impact_flag(p)
        name_f = F("bold", 24)
        avail = (xg_x - 92) - (name_x + 40)   # leave room for the xG± number
        fw = 0
        if flag:
            ff = F("bold", 14)
            fw = d.textlength(flag[0], font=ff) + 16
        name = _short_name(d, p["name"], name_f, avail - (fw + 10 if flag else 0))
        d.text((name_x + 40, cy), name, fill=C["text"], font=name_f, anchor="lm")
        if flag:
            fx = name_x + 40 + d.textlength(name, font=name_f) + 10
            d.rounded_rectangle([fx, cy - 11, fx + fw, cy + 11], radius=6, outline=flag[1], width=2)
            d.text((fx + fw / 2, cy), flag[0], fill=flag[1], font=ff, anchor="mm")
        # 5v5 xG +/- (process)
        xpm = p.get("xg_pm5", 0)
        xc = GOOD if xpm >= DESERVED_XG else BAD if xpm <= OUTCHANCED_XG else C["body"]
        d.text((xg_x, cy), _signed(xpm), fill=xc, font=F("semibold", 22), anchor="rm")
        # stacked bar
        bh = 16
        right, left = zero, zero
        for key, _, c in PARTS:
            v = p["gs_parts"].get(key, 0)
            w = abs(v) * ppu
            if w < 1:
                continue
            if v > 0:
                d.rectangle([right, cy - bh / 2, right + w, cy + bh / 2], fill=c)
                right += w
            else:
                d.rectangle([left - w, cy - bh / 2, left, cy + bh / 2], fill=c)
                left -= w
        ctx = context.get(p["player_id"])
        if ctx:
            ax = zero + ctx["avg"] * ppu
            d.line([(ax, cy - bh / 2 - 6), (ax, cy + bh / 2 + 6)], fill="#FFFFFF", width=3)
        # value + trend
        gs = p["game_score"]
        gc = GOOD if gs >= 1.0 else BAD if gs < 0 else C["text"]
        d.text((gs_x, cy), _num(gs), fill=gc, font=F("bold", 28), anchor="rm")
        if ctx and ctx.get("trend"):
            hot = ctx["trend"] == "hot"
            _arrow(d, gs_x + 10, cy - 6, hot, GOOD if hot else BAD, 12)
        y += row_h

    # goalies
    y = max(y + 8, 1150 - 40 * max(0, len(goalies) - 1))
    for g in goalies:
        d.text((name_x, y), "G", fill=C["muted"], font=F("semibold", 18))
        d.text((name_x + 40, y - 4), _ellipsize(d, g["name"], F("bold", 24), 330), fill=C["text"],
               font=F("bold", 24))
        gs_col = GOOD if g["gsax"] > 0.5 else BAD if g["gsax"] < -0.5 else C["body"]
        d.text((W - M, y - 2), _goalie_line(g), fill=gs_col, font=F("regular", 24), anchor="ra")
        y += 40

    # how to read it
    fy = 1226
    nf = F("regular", 18)
    line1 = "5v5 xG± = expected goals for minus against with him on the ice at 5-on-5."
    d.text((M, fy), line1, fill=C["muted"], font=nf)
    if has_ctx:
        ax = M + d.textlength(line1, font=nf) + 22
        _arrow(d, ax, fy + 4, True, GOOD, 11)
        _arrow(d, ax + 15, fy + 4, False, BAD, 11)
        d.text((ax + 34, fy), "= hot / cold run", fill=C["muted"], font=nf)
    d.text((M, fy + 26), "DESERVED MORE: no points, but won his chances.    "
           "OUTCHANCED: had points, but lost his chances.", fill=C["muted"], font=nf)
    _footer(d)
    return img


# --------------------------------------------------------------- game number ---
SEASON_GAMES = 1312  # 32 teams x 82 games / 2


def game_number(game_id):
    """NHL game number for a regular-season game id (2026020116 -> 116), else None."""
    s = str(game_id)
    return int(s[6:]) if len(s) == 10 and s[4:6] == "02" else None


def _game_label(game):
    n = game_number(game["game_id"])
    return f"NHL GAME #{n}" if n else "GAME BREAKDOWN"


# --------------------------------------------------------------- cover slide ---
def _mix(c1, c2, t):
    a, b = _hex_rgb(c1) if isinstance(c1, str) else c1, _hex_rgb(c2) if isinstance(c2, str) else c2
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _cover_background(away_c, home_c, size=(W, H)):
    """Diagonal blend from the away colour (top-left) to the home colour (bottom-right)."""
    small_w, small_h = size[0] // 10, size[1] // 10
    bg = Image.new("RGB", (small_w, small_h))
    px = bg.load()
    a_dark, h_dark = _mix(away_c, C["bg"], 0.55), _mix(home_c, C["bg"], 0.55)
    for y in range(small_h):
        for x in range(small_w):
            t = (x / small_w + y / small_h) / 2          # 0 top-left .. 1 bottom-right
            t = min(1, max(0, (t - 0.35) / 0.3))         # crisp-ish diagonal seam
            px[x, y] = _mix(a_dark, h_dark, t)
    return bg.resize(size, Image.BICUBIC)


def _wrap_lines(d, text, font, max_w, max_lines):
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
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(d, lines[-1] + " …", font, max_w)
    return lines


def cover_headline(game, copy=None):
    """The AI hook when we have one; otherwise the top performer."""
    if copy and copy.get("ai") and copy.get("hook"):
        return copy["hook"].strip()
    if game["stars"]:
        p = game["stars"][0]
        if p["position"] == "G":
            return f"{p['name']} led the way: {p['saves']} saves, {_signed(p['gsax'])} goals saved above expected"
        return f"{p['name']} led the way: {p['G']}G {p['A']}A, {_num(p['game_score'])} Game Score"
    return ""


def cover_canvas(left_color, right_color, left_abbrev=None, right_abbrev=None, panel=(240, 950),
                 accent=C["accent"], size=(W, H)):
    """Shared cover look: diagonal colour blend, giant logo watermarks, dark fades top and
    bottom, and an opaque panel. Returns (RGB image, draw)."""
    cw, ch = size
    base = _cover_background(left_color, right_color, size).convert("RGBA")
    for ab, xy, anchor in ((left_abbrev, (-120, 40), "lt"), (right_abbrev, (cw + 120, ch - 40), "rb")):
        mark = logos.logo(ab, height=620, max_w=760, opacity=0.16) if ab else None
        if mark is not None:
            x = xy[0] if anchor[0] == "l" else xy[0] - mark.width
            y = xy[1] if anchor[1] == "t" else xy[1] - mark.height
            base.alpha_composite(mark, (int(x), int(y)))
    fade = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    r, g, b = _hex_rgb(C["bg"])
    for i in range(260):
        fd.line([(0, ch - 260 + i), (cw, ch - 260 + i)], fill=(r, g, b, int(235 * (i / 260) ** 1.6)))
    for i in range(170):
        fd.line([(0, i), (cw, i)], fill=(r, g, b, int(200 * (1 - i / 170) ** 1.4)))
    base.alpha_composite(fade)
    if panel:
        overlay = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rounded_rectangle(
            [M - 24, panel[0], cw - M + 24, panel[1]], radius=28, fill=(*_hex_rgb(C["bg"]), 232),
            outline=(*_hex_rgb(C["panel_border"]), 255), width=2)
        base.alpha_composite(overlay)
    img = base.convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, cw, 14], fill=accent)
    return img, d


def render_cover_slide(game, headline=""):
    """Slide 1: reads at grid size. Team-colour blend, logo watermarks, opaque score panel."""
    a, h = game["teams"]["away"], game["teams"]["home"]
    away_c, home_c = _distinct(a["color"], h["color"])
    p_top, p_bot = 240, 950
    img, d = cover_canvas(a["color"], h["color"], a["abbrev"], h["abbrev"], (p_top, p_bot))
    status = {"OT": "FINAL · OT", "SO": "FINAL · SHOOTOUT"}.get(game["outcome"], "FINAL")
    _header(d, f"{_game_label(game)}  //  {status}", _pretty_date(game["date"]))
    d.text((M, 110), "Chirp Analytics", fill=C["text"], font=F("bold", 30))

    # logos + scores
    cy = p_top + 190
    for t, color, x, anchor in ((a, away_c, M + 135, "mm"), (h, home_c, W - M - 135, "mm")):
        if not logos.paste(img, t["abbrev"], (x, cy), height=190, max_w=220, anchor="mm"):
            d.text((x, cy), t["abbrev"], fill=color, font=F("bold", 96), anchor="mm")
        d.text((x, cy + 140), t["common_name"].upper(), fill=C["muted"], font=F("semibold", 28),
               anchor="mm")
    sf = F("bold", 150)
    d.text((W / 2 - 40, cy), str(a["score"]), fill=C["text"] if a["won"] else C["muted"], font=sf,
           anchor="rm")
    d.text((W / 2, cy), "–", fill=C["faint"], font=F("bold", 70), anchor="mm")
    d.text((W / 2 + 40, cy), str(h["score"]), fill=C["text"] if h["won"] else C["muted"], font=sf,
           anchor="lm")
    # xG strip
    y = cy + 200
    d.line([(M + 10, y), (W - M - 10, y)], fill=C["panel_border"], width=2)
    y += 30
    d.text((W / 2, y), "EXPECTED GOALS", fill=C["muted"], font=F("semibold", 24), anchor="mt")
    xf = F("bold", 64)
    d.text((W / 2 - 40, y + 40), f"{a['xg']:.2f}", fill=away_c, font=xf, anchor="ra")
    d.text((W / 2, y + 52), "–", fill=C["faint"], font=F("bold", 44), anchor="ma")
    d.text((W / 2 + 40, y + 40), f"{h['xg']:.2f}", fill=home_c, font=xf, anchor="la")
    # three quick comparisons
    y += 150
    pp = lambda t: f"{t['pp_goals']}/{t['pp_opps']}"
    cols = [("SHOTS", str(a["sog"]), str(h["sog"])),
            ("HIGH-DANGER", str(a["hd"]), str(h["hd"])),
            ("POWER PLAY", pp(a), pp(h))]
    cw = (W - 2 * M) / 3
    for i, (label, av, hv) in enumerate(cols):
        cx = M + cw * (i + 0.5)
        d.text((cx, y), label, fill=C["muted"], font=F("semibold", 20), anchor="mt")
        vf = F("bold", 38)
        d.text((cx - 16, y + 34), av, fill=away_c, font=vf, anchor="ra")
        d.text((cx, y + 40), "–", fill=C["faint"], font=F("bold", 28), anchor="ma")
        d.text((cx + 16, y + 34), hv, fill=home_c, font=vf, anchor="la")

    # headline under the panel
    if headline:
        hf = F("bold", 44)
        lines = _wrap_lines(d, headline, hf, W - 2 * M, 3)
        y = p_bot + 40
        for line in lines:
            d.text((M, y), line, fill=C["text"], font=hf)
            y += 56
    d.text((W - M, H - 120), "SWIPE FOR THE BREAKDOWN  →", fill=C["accent"], font=F("bold", 30),
           anchor="ra")
    _footer(d)
    return img


def render_game_carousel(game, context=None, headline="", extra=None):
    """cover, game, away team, away player impact, home team, home player impact (+ extras)."""
    gid, day = game["game_id"], game["date"][:10]
    paths = [_save(render_cover_slide(game, headline), f"{day}_{gid}_0_cover.jpg"),
             _save(render_game_slide(game), f"{day}_{gid}_1_game.jpg"),
             _save(render_team_slide(game, "away"), f"{day}_{gid}_2_away.jpg"),
             _save(render_impact_slide(game, "away", context), f"{day}_{gid}_3_away_impact.jpg"),
             _save(render_team_slide(game, "home"), f"{day}_{gid}_4_home.jpg"),
             _save(render_impact_slide(game, "home", context), f"{day}_{gid}_5_home_impact.jpg")]
    for i, (name, img) in enumerate(extra or [], 6):
        paths.append(_save(img, f"{day}_{gid}_{i}_{name}.jpg"))
    log.info("Rendered carousel for %s: %s", gid, ", ".join(p.name for p in paths))
    return paths


# -------------------------------------------------------------- weekly slides ---
def _range_label(start, end):
    s, e = Date.fromisoformat(start), Date.fromisoformat(end)
    if s.month == e.month:
        return f"{s.strftime('%b').upper()} {s.day}–{e.day}"
    return f"{s.strftime('%b').upper()} {s.day} – {e.strftime('%b').upper()} {e.day}"


def render_weekly_cover(week):
    img, d = _canvas()
    _header(d, "WEEKLY REPORT", f"{week['games']} GAMES")
    d.text((M, 140), "THE WEEK IN", fill=C["muted"], font=F("bold", 56))
    d.text((M, 206), "ANALYTICS", fill=C["text"], font=F("bold", 120))
    d.text((M, 350), _range_label(week["start"], week["end"]), fill=C["accent"],
           font=F("bold", 64))
    cards = []
    if week["players_top"]:
        p = week["players_top"][0]
        cards.append(("TOP SKATER", p["name"], f"{p['team_abbrev']}  ·  {_num(p['game_score'])} Game Score",
                      p["color"], p["team_abbrev"]))
    if week["teams_top"]:
        t = week["teams_top"][0]
        cards.append(("BEST 5V5 TEAM", t["name"], f"{t['xg5_pct']:.1f}% of 5v5 expected goals",
                      t["color"], t["abbrev"]))
    if week["players_bottom"]:
        p = week["players_bottom"][0]
        cards.append(("COLDEST SKATER", p["name"], f"{p['team_abbrev']}  ·  {_num(p['game_score'])} Game Score",
                      p["color"], p["team_abbrev"]))
    y = 500
    for label, title, sub, color, abbrev in cards:
        _panel(d, [M - 24, y, W - M + 24, y + 196])
        d.rectangle([M - 24, y + 24, M - 16, y + 172], fill=color)
        lw = logos.paste(img, abbrev, (W - M, y + 98), height=120, max_w=150, anchor="rm")
        d.text((M + 8, y + 28), label, fill=C["muted"], font=F("semibold", 24))
        d.text((M + 8, y + 66), _ellipsize(d, title, F("bold", 52), W - 2 * M - 20 - (lw + 20 if lw else 0)),
               fill=C["text"], font=F("bold", 52))
        d.text((M + 8, y + 134), sub, fill=C["body"], font=F("regular", 28))
        y += 222
    d.text((W - M, H - 120), "SWIPE  →", fill=C["accent"], font=F("bold", 30), anchor="ra")
    _footer(d)
    return img


def _list_slide(title, subtitle, header_cols, rows, accent):
    """rows: list of dicts with rank, main, tag, tag_color, cols (list of str), value, value_color."""
    img, d = _canvas(accent=accent)
    _header(d, "WEEKLY REPORT", "", color=accent)
    d.text((M, 96), title, fill=C["text"], font=_fit(d, title, "bold", 72, W - 2 * M, 48))
    d.text((M, 184), subtitle, fill=C["muted"], font=F("regular", 26))
    col_xs = [W - M - 330, W - M - 200]
    y = 248
    hf = F("semibold", 20)
    d.text((M + 70, y), header_cols[0], fill=C["faint"], font=hf)
    for x, label in zip(col_xs, header_cols[1:3]):
        d.text((x, y), label, fill=C["faint"], font=hf, anchor="ma")
    d.text((W - M, y), header_cols[3], fill=C["faint"], font=hf, anchor="ra")
    y += 36
    row_h = 92
    for r in rows:
        if r["rank"] % 2 == 1:
            d.rounded_rectangle([M - 20, y - 8, W - M + 20, y + row_h - 14], radius=12, fill="#161A21")
        d.text((M, y + 14), f"{r['rank']}", fill=accent, font=F("bold", 36))
        nx = M + 70
        if r.get("logo") and logos.paste(img, r["logo"], (nx + 24, y + 37), height=50, max_w=56,
                                         anchor="mm"):
            nx += 66
        name_f = F("bold", 32)
        d.text((nx, y + 2), _ellipsize(d, r["main"], name_f, col_xs[0] - nx - 80), fill=C["text"],
               font=name_f)
        d.text((nx, y + 44), r["tag"], fill=r["tag_color"], font=F("semibold", 22))
        for x, val in zip(col_xs, r["cols"]):
            d.text((x, y + 18), val, fill=C["body"], font=F("regular", 28), anchor="ma")
        d.text((W - M, y + 10), r["value"], fill=r.get("value_color", C["text"]), font=F("bold", 44),
               anchor="ra")
        y += row_h
    _footer(d)
    return img


def render_weekly_carousel(week):
    tag = week["end"]
    slides = [render_weekly_cover(week)]

    def player_rows(players, color):
        return [{"rank": i, "main": p["name"], "logo": p["team_abbrev"],
                 "tag": f"{p['team_abbrev']}  ·  {p['position']}", "tag_color": p["color"],
                 "cols": [str(p["gp"]), f"{p['G']}-{p['A']}"],
                 "value": _num(p["game_score"]), "value_color": color}
                for i, p in enumerate(players, 1)]

    def team_rows(teams, color):
        return [{"rank": i, "main": t["name"], "logo": t.get("abbrev"), "tag": t["record"],
                 "tag_color": t["color"],
                 "cols": [str(t["gp"]), f"{t['cf5_pct']:.0f}%" if t["cf5_pct"] is not None else "–"],
                 "value": f"{t['xg5_pct']:.1f}%", "value_color": color}
                for i, t in enumerate(teams, 1)]

    slides.append(_list_slide("TOP 10 SKATERS", "Total Game Score this week (min. 2 games)",
                              ["PLAYER", "GP", "G-A", "GAME SCORE"],
                              player_rows(week["players_top"], GOOD), GOOD))
    slides.append(_list_slide("BOTTOM 10 SKATERS", "Lowest total Game Score this week (min. 2 games)",
                              ["PLAYER", "GP", "G-A", "GAME SCORE"],
                              player_rows(week["players_bottom"], BAD), BAD))
    slides.append(_list_slide("TOP 10 TEAMS", "Share of 5v5 expected goals this week",
                              ["TEAM", "GP", "5V5 CF%", "5V5 xG%"],
                              team_rows(week["teams_top"], GOOD), GOOD))
    slides.append(_list_slide("BOTTOM 10 TEAMS", "Lowest share of 5v5 expected goals this week",
                              ["TEAM", "GP", "5V5 CF%", "5V5 xG%"],
                              team_rows(week["teams_bottom"], BAD), BAD))
    names = ["cover", "skaters_top", "skaters_bottom", "teams_top", "teams_bottom"]
    return [_save(img, f"week_{tag}_{i}_{n}.jpg") for i, (img, n) in enumerate(zip(slides, names), 1)]
