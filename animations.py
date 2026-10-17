"""Animated posts (silent MP4, on-screen text):

  game replay   every shot appearing on the rink in game order (sized by xG), synced with the
                expected-goals race and the score — a 4:5 slide in every game carousel, and a
                9:16 Reel for the game of the night
  ovi goal      Reel when Ovechkin scores: the career-goal odometer, tonight's goals on the rink,
                the goalie(s) he beat, the next milestone
  crosby climb  Reel when Crosby passes someone on the all-time points list
  spotlight     Reel for the night's best hat trick / 4+ point game: Game Score built piece by
                piece and his shots landing on the rink
"""
import logging
import math
import shutil
import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw

import logos
from cards import (BAD, GOOD, PARTS, C, F, M, _distinct, _ellipsize, _fit, _hex_rgb, _num,
                   _pretty_date, _signed, _game_label, _save, _out_path, cover_canvas)
from config import IG_HANDLE

log = logging.getLogger("animations")
FPS = 30
DISCLAIMER = f"{IG_HANDLE}  ·  Unofficial · not affiliated with the NHL"


# ------------------------------------------------------------------ encoder ---
def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


class Video:
    """Pipe RGB frames into ffmpeg: H.264 + a silent AAC track (Instagram expects audio)."""

    def __init__(self, path, w, h, fps=FPS):
        self.path, self.size, self.frames = path, (w, h), 0
        cmd = [_ffmpeg(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-shortest", "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-level", "4.1", "-c:a", "aac", "-b:a", "64k",
               "-movflags", "+faststart", str(path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def add(self, img, repeat=1):
        if img.size != self.size:
            raise ValueError(f"frame is {img.size}, video is {self.size}")
        data = img.convert("RGB").tobytes()
        for _ in range(repeat):
            self.proc.stdin.write(data)
            self.frames += 1

    def close(self):
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {self.path}")
        log.info("Video %s: %d frames (%.1fs)", self.path.name, self.frames, self.frames / FPS)
        return self.path


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------- rink ---
RINK_W, RINK_H = 200.0, 85.0


class Rink:
    """A full rink in a box; NHL feet -> pixels. Drawn once at 2x and downsampled (smooth)."""

    def __init__(self, box):
        self.x0, self.y0, self.x1, self.y1 = box
        self.ox = self.paste_x = self.x0
        self.sx = (self.x1 - self.x0) / RINK_W
        self.sy = (self.y1 - self.y0) / RINK_H
        self.layer = self._draw()

    def px(self, x, y):
        return self.ox + (x + 100) * self.sx, self.y0 + (42.5 - y) * self.sy

    def _draw(self):
        k = 2
        w, h = int(self.x1 - self.x0), int(self.y1 - self.y0)
        img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        P = lambda x, y: ((x + 100) * self.sx * k, (42.5 - y) * self.sy * k)
        r = 28 * self.sx * k
        d.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=r, fill="#141920",
                            outline="#4A525E", width=3 * k)
        line = lambda x, col, wd: d.line([P(x, 42.5), P(x, -42.5)], fill=col, width=int(wd * k))
        line(0, "#6B2A31", 4)
        for bx in (-25, 25):
            line(bx, "#2B4677", 5)
        for gx in (-89, 89):
            line(gx, "#6B2A31", 2)
        circ = lambda cx, cy, rad, col, wd: d.ellipse(
            [P(cx - rad, cy + rad), P(cx + rad, cy - rad)], outline=col, width=int(wd * k))
        circ(0, 0, 15, "#2B4677", 2)
        for cx in (-69, 69):
            for cy in (-22, 22):
                circ(cx, cy, 15, "#5A2830", 2)
                dot = P(cx, cy)
                d.ellipse([dot[0] - 3 * k, dot[1] - 3 * k, dot[0] + 3 * k, dot[1] + 3 * k], fill="#6B2A31")
        for nx in (-20, 20):
            for ny in (-22, 22):
                dot = P(nx, ny)
                d.ellipse([dot[0] - 3 * k, dot[1] - 3 * k, dot[0] + 3 * k, dot[1] + 3 * k], fill="#6B2A31")
        for gx, sgn in ((-89, 1), (89, -1)):  # creases + nets
            a, b = P(gx, 6), P(gx + sgn * 6 * 2, -6)
            box = [min(a[0], b[0]), a[1], max(a[0], b[0]), b[1]]
            d.pieslice(box, 270 if sgn > 0 else 90, 90 if sgn > 0 else 270, fill="#1C3350")
            n1, n2 = P(gx, 3), P(gx - sgn * 4, -3)
            d.rectangle([min(n1[0], n2[0]), n1[1], max(n1[0], n2[0]), n2[1]], outline="#8B949E",
                        width=2 * k)
        return img.resize((w, h), Image.LANCZOS)

    def paste(self, base):
        base.paste(self.layer, (int(self.paste_x), int(self.y0)), self.layer)


@lru_cache(maxsize=512)
def _dot(color, radius, ring=False, alpha=235):
    """Anti-aliased dot sprite (RGBA)."""
    k = 4
    r = max(2, int(round(radius)))
    s = (2 * r + 6) * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    rgb = _hex_rgb(color)
    d.ellipse([c - r * k, c - r * k, c + r * k, c + r * k], fill=(*rgb, alpha))
    if ring:
        d.ellipse([c - r * k, c - r * k, c + r * k, c + r * k], outline=(255, 255, 255, 255), width=3 * k)
    return img.resize((s // k, s // k), Image.LANCZOS)


def paste_dot(base, xy, color, radius, ring=False, alpha=235):
    spr = _dot(color, round(radius, 0), ring, alpha)
    base.paste(spr, (int(xy[0] - spr.width / 2), int(xy[1] - spr.height / 2)), spr)


def shot_radius(xg, scale=1.0):
    return scale * (6 + 34 * math.sqrt(max(xg, 0.0)))


def shot_xy(rink, ev):
    """Home team attacks the right net, away the left (coordinates arrive attacking +x)."""
    if ev.get("x") is None:
        return None
    x, y = ev["x"], ev["y"]
    if ev["side"] == "away":
        x, y = -x, -y
    return rink.px(x, y)


# ------------------------------------------------------------ game replay ---
def _clock(t, length):
    period = min(int(t // 1200) + 1, 4)
    if t >= length:
        return "FINAL"
    rem = 1200 - (t - (period - 1) * 1200) if period <= 3 else max(0, length - t)
    label = {1: "1ST", 2: "2ND", 3: "3RD"}.get(period, "OT")
    return f"{label}  ·  {int(rem // 60)}:{int(rem % 60):02d}"


class _Layout:
    def __init__(self, fmt):
        W = 1080
        self.W = W
        rink_w = W - 2 * M
        if fmt == "reel":
            # Instagram covers the top ~200px and the bottom/right edge of a Reel with its UI
            self.H = 1920
            self.header_y, self.board_y, self.logo_h, self.score_size = 70, 230, 170, 150
            self.clock_y = 452
            self.headline_y = 500
            rink_top = 590
            self.chart = (M + 34, 1110, W - M - 150, 1430)
            self.toast_y = 1475
            self.footer_y = 1580
        else:
            self.H = 1350
            self.header_y, self.board_y, self.logo_h, self.score_size = 50, 104, 96, 96
            self.clock_y = 246
            self.headline_y = None
            rink_top = 290
            self.chart = (M + 34, 800, W - M - 110, 1110)
            self.toast_y = 1160
            self.footer_y = 1288
        self.rink = (M, rink_top, M + rink_w, rink_top + rink_w * RINK_H / RINK_W)


def _static_game(game, lay, kicker, rink, colors):
    a, h = game["teams"]["away"], game["teams"]["home"]
    away_c, home_c = colors
    img = Image.new("RGB", (lay.W, lay.H), C["bg"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, lay.W, 14], fill=C["accent"])
    d.text((M, lay.header_y), kicker, fill=C["accent"], font=F("semibold", 28))
    d.text((lay.W - M, lay.header_y), _pretty_date(game["date"]), fill=C["muted"], font=F("semibold", 28),
           anchor="ra")
    # logos on the scoreboard
    by = lay.board_y + lay.logo_h / 2
    for t, x, col in ((a, M + 100, away_c), (h, lay.W - M - 100, home_c)):
        if not logos.paste(img, t["abbrev"], (x, by), height=lay.logo_h, max_w=lay.logo_h * 1.25,
                           anchor="mm"):
            d.text((x, by), t["abbrev"], fill=col, font=F("bold", 72), anchor="mm")
    rink.paste(img)
    # which end is whose
    for t, x, col in ((a, rink.px(-62, 0)[0], away_c), (h, rink.px(62, 0)[0], home_c)):
        mark = logos.logo(t["abbrev"], height=(rink.y1 - rink.y0) * 0.38, opacity=0.13)
        if mark is not None:
            img.paste(mark, (int(x - mark.width / 2), int((rink.y0 + rink.y1) / 2 - mark.height / 2)), mark)
    d.text((rink.x0 + 12, rink.y1 + 12), f"←  {a['abbrev']} SHOTS", fill=away_c, font=F("semibold", 22))
    d.text((rink.x1 - 12, rink.y1 + 12), f"{h['abbrev']} SHOTS  →", fill=home_c, font=F("semibold", 22),
           anchor="ra")
    # chart frame
    x0, y0, x1, y1 = lay.chart
    d.text((M, y0 - 62), "EXPECTED GOALS RACE", fill=C["text"], font=F("semibold", 24))
    d.text((lay.W - M, y0 - 60), "dot size = xG  ·  ring = goal", fill=C["faint"], font=F("regular", 20),
           anchor="ra")
    return img


def render_game_replay(game, fmt="slide", kicker=None, headline=None, seconds=12.0):
    """fmt: "slide" (1080x1350, carousel) or "reel" (1080x1920). Returns the MP4 path."""
    lay = _Layout(fmt)
    a, h = game["teams"]["away"], game["teams"]["home"]
    away_c, home_c = _distinct(a["color"], h["color"])
    colors = {"away": away_c, "home": home_c}
    rink = Rink(lay.rink)
    kicker = kicker or f"GAME REPLAY  //  {_game_label(game)}"
    base = _static_game(game, lay, kicker, rink, (away_c, home_c))
    length = max(game["game_length"], 3600)
    events = sorted(game["timeline"], key=lambda e: e["t"])
    totals = {"away": sum(e["xg"] for e in events if e["side"] == "away"),
              "home": sum(e["xg"] for e in events if e["side"] == "home")}
    ymax = max(1.0, max(totals.values()) * 1.15)
    x0, y0, x1, y1 = lay.chart

    def X(t):
        return x0 + (x1 - x0) * t / length

    def Y(v):
        return y1 - (y1 - y0) * v / ymax

    # static chart grid
    gd = ImageDraw.Draw(base)
    step = 1 if ymax <= 6 else 2
    v = 0
    while v <= ymax:
        gd.line([(x0, Y(v)), (x1, Y(v))], fill="#262C36", width=1)
        gd.text((x0 - 12, Y(v)), f"{v:g}", fill=C["faint"], font=F("regular", 20), anchor="rm")
        v += step
    for m in (1200, 2400, 3600):
        if m < length:
            gd.line([(X(m), y0), (X(m), y1)], fill="#30363D", width=2)
    path = _out_path(f"{game['date'][:10]}_{game['game_id']}_replay_{fmt}.mp4")
    vid = Video(path, lay.W, lay.H)

    intro, outro = (0.5, 3.0) if fmt == "reel" else (0.3, 2.5)
    n_play = int(seconds * FPS)
    final_score = {"away": a["score"], "home": h["score"]}
    goal_times = [e for e in events if e["goal"]]

    def frame(T, anim_t, final=False):
        img = base.copy()
        d = ImageDraw.Draw(img)
        # scoreboard
        score = {s: sum(1 for e in goal_times if e["side"] == s and e["t"] <= T) for s in ("away", "home")}
        if final:
            score = final_score  # shootout winners get the extra goal at the end
        sf = F("bold", lay.score_size)
        by = lay.board_y + lay.logo_h / 2
        d.text((lay.W / 2 - 34, by), str(score["away"]), fill=C["text"], font=sf, anchor="rm")
        d.text((lay.W / 2, by), "–", fill=C["faint"], font=F("bold", lay.score_size // 2), anchor="mm")
        d.text((lay.W / 2 + 34, by), str(score["home"]), fill=C["text"], font=sf, anchor="lm")
        clock = _clock(T, length) if not final else \
            {"OT": "FINAL · OT", "SO": "FINAL · SHOOTOUT"}.get(game["outcome"], "FINAL")
        d.text((lay.W / 2, lay.clock_y), clock, fill=C["accent"] if final else C["muted"],
               font=F("bold", 30), anchor="mm")
        if headline and lay.headline_y:
            d.text((lay.W / 2, lay.headline_y), headline, fill=C["text"],
                   font=_fit(d, headline, "bold", 38, lay.W - 2 * M, 22), anchor="mm")
        # shots
        for e in events:
            if e["t"] > T:
                break
            xy = shot_xy(rink, e)
            if not xy:
                continue
            age = (T - e["t"]) / length * seconds  # seconds of animation since it appeared
            pop = 1.0 + 0.8 * max(0.0, 1 - age / 0.35)
            paste_dot(img, xy, colors[e["side"]], shot_radius(e["xg"], 0.85) * pop, ring=e["goal"],
                      alpha=230 if e["goal"] else 170)
        # xG race lines
        tips = {}
        for side in ("away", "home"):
            pts, cum = [(X(0), Y(0))], 0.0
            for e in events:
                if e["t"] > T:
                    break
                if e["side"] != side:
                    continue
                pts.append((X(e["t"]), Y(cum)))
                cum += e["xg"]
                pts.append((X(e["t"]), Y(cum)))
            pts.append((X(min(T, length)), Y(cum)))
            d.line(pts, fill=colors[side], width=6, joint="curve")
            tips[side] = (X(min(T, length)), Y(cum), cum)
            # goal markers on the line
            run = 0.0
            for e in events:
                if e["t"] > T:
                    break
                if e["side"] == side:
                    run += e["xg"]
                    if e["goal"]:
                        paste_dot(img, (X(e["t"]), Y(run)), colors[side], 11, ring=True, alpha=255)
        # running totals at the tip of each line, nudged apart when they meet
        (ax, ay, av), (hx, hy, hv) = tips["away"], tips["home"]
        if abs(ay - hy) < 34:
            mid = (ay + hy) / 2
            ay, hy = (mid + 17, mid - 17) if av <= hv else (mid - 17, mid + 17)
        for (tx, ty, tv), side in (((ax, ay, av), "away"), ((hx, hy, hv), "home")):
            d.text((tx + 12, ty), f"{tv:.2f}", fill=colors[side], font=F("bold", 30), anchor="lm")
        # goal toast
        recent = [e for e in goal_times if e["t"] <= T and (T - e["t"]) / length * seconds < 1.4]
        if recent and not final:
            e = recent[-1]
            tm = a if e["side"] == "away" else h
            fade = 1 - ((T - e["t"]) / length * seconds) / 1.4
            col = colors[e["side"]]
            text = f"GOAL  ·  {e['scorer']} ({tm['abbrev']})  ·  {e['xg']:.2f} xG"
            tf = _fit(d, text, "bold", 40 if fmt == "reel" else 34, lay.W - 2 * M - 20, 22)
            tw = d.textlength(text, font=tf)
            bx = (lay.W - tw) / 2 - 24
            d.rounded_rectangle([bx, lay.toast_y - 8, lay.W - bx, lay.toast_y + tf.size + 18], radius=14,
                                fill=_mix_hex(col, C["bg"], 0.25 + 0.5 * (1 - fade)))
            d.text((lay.W / 2, lay.toast_y), text, fill="#FFFFFF", font=tf, anchor="ma")
        d.text((M if fmt == "slide" else lay.W / 2, lay.footer_y), DISCLAIMER, fill=C["faint"],
               font=F("regular", 22), anchor="la" if fmt == "slide" else "ma")
        return img

    vid.add(frame(0, 0), repeat=int(intro * FPS))
    for i in range(n_play + 1):
        T = length * ease(i / n_play) if fmt == "never" else length * i / n_play
        vid.add(frame(T, i / FPS))
    last = frame(length, seconds, final=True)
    if fmt == "reel":
        last = _end_card(last, game, lay, colors, totals)
    vid.add(last, repeat=int(outro * FPS))
    return vid.close()


def _mix_hex(c1, c2, t):
    a, b = _hex_rgb(c1), _hex_rgb(c2)
    return "#{:02X}{:02X}{:02X}".format(*(int(x + (y - x) * t) for x, y in zip(a, b)))


def _end_card(img, game, lay, colors, totals):
    """Final frame of the Reel: dim the replay, final score + xG + call to action."""
    a, h = game["teams"]["away"], game["teams"]["home"]
    over = Image.new("RGBA", img.size, (*_hex_rgb(C["bg"]), 205))
    out = img.convert("RGBA")
    out.alpha_composite(over)
    out = out.convert("RGB")
    d = ImageDraw.Draw(out)
    cy = 760
    d.text((lay.W / 2, cy - 230), {"OT": "FINAL · OT", "SO": "FINAL · SHOOTOUT"}.get(game["outcome"], "FINAL"),
           fill=C["accent"], font=F("bold", 40), anchor="mm")
    for t, x in ((a, lay.W / 2 - 280), (h, lay.W / 2 + 280)):
        if not logos.paste(out, t["abbrev"], (x, cy - 40), height=170, max_w=220, anchor="mm"):
            d.text((x, cy - 40), t["abbrev"], fill=C["text"], font=F("bold", 90), anchor="mm")
    d.text((lay.W / 2 - 40, cy - 40), str(a["score"]), fill=C["text"], font=F("bold", 150), anchor="rm")
    d.text((lay.W / 2 + 40, cy - 40), str(h["score"]), fill=C["text"], font=F("bold", 150), anchor="lm")
    d.text((lay.W / 2, cy + 110), "EXPECTED GOALS", fill=C["muted"], font=F("semibold", 26), anchor="mm")
    d.text((lay.W / 2 - 30, cy + 170), f"{totals['away']:.2f}", fill=colors["away"], font=F("bold", 64), anchor="rm")
    d.text((lay.W / 2 + 30, cy + 170), f"{totals['home']:.2f}", fill=colors["home"], font=F("bold", 64), anchor="lm")
    d.text((lay.W / 2, cy + 300), "Full breakdown on our page  →", fill=C["accent"], font=F("bold", 40),
           anchor="mm")
    d.text((lay.W / 2, cy + 356), IG_HANDLE, fill=C["text"], font=F("bold", 34), anchor="mm")
    return out


# ------------------------------------------------------------ shared reel bits ---
REEL_W, REEL_H = 1080, 1920


def half_rink(box):
    """Attacking half (x 0..100) of a rink, as a Rink whose px() maps the right half into box."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    r = Rink((x0 - w, y0, x1, y1))
    r.layer = r.layer.crop((int(w), 0, int(w) + int(w), r.layer.height))
    r.paste_x = x0
    return r


def _bg(left_color, right_color, left_ab=None, right_ab=None, accent=C["accent"]):
    img, _ = cover_canvas(left_color, right_color, left_ab, right_ab, panel=None, accent=accent,
                          size=(REEL_W, REEL_H))
    return img


def _panel_rgba(img, box, alpha=225, radius=28):
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(over).rounded_rectangle(box, radius=radius, fill=(*_hex_rgb(C["bg"]), alpha),
                                           outline=(*_hex_rgb(C["panel_border"]), 255), width=2)
    out = img.convert("RGBA")
    out.alpha_composite(over)
    return out.convert("RGB")


def _reel_footer(d):
    d.text((REEL_W / 2, 1580), DISCLAIMER, fill=C["faint"], font=F("regular", 22), anchor="ma")


def _fade_text(d, xy, text, font, color, p, anchor="la"):
    """Draw text sliding up 20px and fading in as p goes 0 -> 1 (fade approximated by mixing)."""
    if p <= 0:
        return
    p = ease(p)
    x, y = xy
    col = _mix_hex(C["bg"], color, p) if color.startswith("#") else color
    d.text((x, y + 20 * (1 - p)), text, fill=col, font=font, anchor=anchor)


def _odometer(img, center, old, new, p, font, color):
    """Digits that changed roll up from `old` to `new` as p goes 0 -> 1."""
    old, new = str(old), str(new)
    if len(old) != len(new):
        old = new if p >= 1 else old.rjust(len(new))
    d = ImageDraw.Draw(img)
    widths = [d.textlength(ch, font=font) for ch in new]
    total = sum(widths) + 8 * (len(new) - 1)
    x = center[0] - total / 2
    h = int(font.size * 0.9)
    top = center[1] - h / 2
    pe = ease(p)
    for ch_old, ch_new, w in zip(old, new, widths):
        cell = Image.new("RGBA", (int(w) + 6, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cell)
        if ch_old == ch_new or p >= 1:
            cd.text((3, h / 2), ch_new, fill=color, font=font, anchor="lm")
        else:
            cd.text((3, h / 2 - pe * h), ch_old, fill=color, font=font, anchor="lm")
            cd.text((3, h / 2 + (1 - pe) * h), ch_new, fill=color, font=font, anchor="lm")
        img.paste(cell, (int(x), int(top)), cell)
        x += w + 8


# --------------------------------------------------------------- ovi goal ---
def render_ovi_goal(ev, seconds=10.0):
    """ev: date, game_id, before, after, opp, home, goals [{x, y, xg, goalie, line}], record (bool),
    next_milestone, to_next, extra (e.g. 'FINAL REGULAR-SEASON VISIT TO BOSTON')."""
    red = "#E03A3E"
    base = _bg("#C8102E", "#041E42", "WSH", ev.get("opp"), accent=red)
    base = _panel_rgba(base, [M - 24, 250, REEL_W - M + 24, 1520])
    d = ImageDraw.Draw(base)
    d.text((M, 70), "OVI'S FAREWELL TOUR", fill=red, font=F("bold", 34))
    d.text((REEL_W - M, 70), _pretty_date(ev["date"]), fill=C["muted"], font=F("semibold", 28), anchor="ra")
    rw = 560
    rink = half_rink(((REEL_W - rw) / 2, 900, (REEL_W + rw) / 2, 900 + rw * 85 / 100))
    path = _out_path(f"{ev['date']}_{ev['game_id']}_ovi.mp4")
    vid = Video(path, REEL_W, REEL_H)
    n = int(seconds * FPS)
    goals = ev["goals"]
    for i in range(n):
        t = i / FPS
        img = base.copy()
        dd = ImageDraw.Draw(img)
        dd.text((REEL_W / 2, 300), "CAREER GOALS", fill=C["muted"], font=F("semibold", 34), anchor="mm")
        steps = max(1, ev["after"] - ev["before"])  # one tick per goal tonight
        roll = min(1.0, max(0.0, (t - 0.5) / (0.7 * steps))) * steps
        k = min(int(roll), steps - 1)
        _odometer(img, (REEL_W / 2, 470), ev["before"] + k, ev["before"] + k + 1, roll - k,
                  F("bold", 240), C["text"])
        tag = "NHL RECORD" if ev.get("record") else ""
        settle = 0.5 + 0.7 * steps
        _fade_text(dd, (REEL_W / 2, 600), tag, F("bold", 40), red, (t - settle) / 0.5, anchor="mm")
        where = "vs" if ev["home"] else "@"
        n_g = len(goals)
        tonight = f"Tonight {where} {ev['opp']}: {n_g} goal{'s' * (n_g > 1)}"
        _fade_text(dd, (REEL_W / 2, 668), tonight, F("semibold", 40), C["text"], (t - settle - 0.2) / 0.5,
                   anchor="mm")
        if t > 2.8:
            rink.paste(img)
            dd = ImageDraw.Draw(img)
            for k, g in enumerate(goals):
                gt = t - 3.0 - 0.7 * k
                if gt <= 0 or g.get("x") is None:
                    continue
                pop = 1.0 + 0.9 * max(0.0, 1 - gt / 0.35)
                paste_dot(img, rink.px(g["x"], g["y"]), red, shot_radius(g["xg"], 0.9) * pop, ring=True,
                          alpha=255)
            ly = 720
            for k, g in enumerate(goals[:3]):
                _fade_text(dd, (REEL_W / 2, ly + 60 * k), g["line"], F("semibold", 34), C["body"],
                           (t - 3.2 - 0.7 * k) / 0.5, anchor="mm")
        if t > 5.6:
            p = (t - 5.6) / 0.6
            _fade_text(dd, (REEL_W / 2, 1420), f"{ev['to_next']} TO {ev['next_milestone']:,}",
                       F("bold", 64), C["text"], p, anchor="mm")
            if ev.get("extra"):
                _fade_text(dd, (REEL_W / 2, 1484), ev["extra"], _fit(dd, ev["extra"], "bold", 34,
                                                                     REEL_W - 2 * M, 22),
                           red, (t - 6.2) / 0.6, anchor="mm")
        _reel_footer(dd)
        vid.add(img)
    return vid.close()


# ------------------------------------------------------------ crosby climb ---
def render_crosby_climb(ev, seconds=9.0):
    """ev: date, game_id, before, after, board [{name, points, me}] (sorted, after tonight),
    passed [names], rank_after, next_name, to_next."""
    gold = "#FCB514"
    base = _bg("#FCB514", "#101010", "PIT", None, accent=gold)
    base = _panel_rgba(base, [M - 24, 250, REEL_W - M + 24, 1520])
    d = ImageDraw.Draw(base)
    d.text((M, 70), "CROSBY: CHASING HISTORY", fill=gold, font=F("bold", 34))
    d.text((REEL_W - M, 70), _pretty_date(ev["date"]), fill=C["muted"], font=F("semibold", 28), anchor="ra")
    d.text((REEL_W / 2, 300), "ALL-TIME POINTS", fill=C["muted"], font=F("semibold", 34), anchor="mm")
    board = ev["board"]                       # final order
    me_final = next(i for i, r in enumerate(board) if r["me"])
    me_start = me_final + len(ev["passed"])   # where he started
    path = _out_path(f"{ev['date']}_{ev['game_id']}_crosby.mp4")
    vid = Video(path, REEL_W, REEL_H)
    top, row_h = 560, 104
    first_rank = ev["rank_after"] - me_final
    n = int(seconds * FPS)
    for i in range(n):
        t = i / FPS
        img = base.copy()
        dd = ImageDraw.Draw(img)
        climb = ease((t - 1.2) / 2.4)
        pts = round(ev["before"] + (ev["after"] - ev["before"]) * climb)
        _odometer(img, (REEL_W / 2, 420), f"{ev['before']:,}", f"{pts:,}", 1.0, F("bold", 150), C["text"])
        me_pos = me_start + (me_final - me_start) * climb
        for idx, r in enumerate(board):
            if r["me"]:
                pos = me_pos
            else:
                # rows he passes slide down one slot as he goes by
                passed_idx = idx - me_final  # >0 for rows below him at the end
                pos = idx
                if 0 < passed_idx <= len(ev["passed"]):
                    pos = idx - 1 + min(1.0, max(0.0, (climb * len(ev["passed"]) - (len(ev["passed"]) - passed_idx))))
            y = top + pos * row_h
            if r["me"]:
                dd.rounded_rectangle([M - 10, y - 8, REEL_W - M + 10, y + row_h - 20], radius=14,
                                     fill="#2A2410", outline=gold, width=3)
            rank = first_rank + round(pos)
            dd.text((M + 10, y + 38), f"{rank}", fill=gold if r["me"] else C["muted"], font=F("bold", 40),
                    anchor="lm")
            dd.text((M + 90, y + 38), r["name"], fill=C["text"], font=F("bold", 42), anchor="lm")
            val = pts if r["me"] else r["points"]
            dd.text((REEL_W - M - 10, y + 38), f"{val:,}", fill=C["text"], font=F("bold", 42), anchor="rm")
        if t > 4.0 and ev["passed"]:
            msg = "PASSES " + " AND ".join(n.upper() for n in ev["passed"][-2:])
            _fade_text(dd, (REEL_W / 2, 1300), msg, _fit(dd, msg, "bold", 52, REEL_W - 2 * M, 28), gold,
                       (t - 4.0) / 0.6, anchor="mm")
            _fade_text(dd, (REEL_W / 2, 1380), f"#{ev['rank_after']} ALL-TIME", F("bold", 44), C["text"],
                       (t - 4.4) / 0.6, anchor="mm")
            if ev.get("next_name"):
                _fade_text(dd, (REEL_W / 2, 1450), f"Next: {ev['next_name']}, {ev['to_next']} away",
                           F("semibold", 34), C["body"], (t - 5.0) / 0.6, anchor="mm")
        _reel_footer(dd)
        vid.add(img)
    return vid.close()


# --------------------------------------------------------------- spotlight ---
def render_spotlight(game, player, reason, seconds=10.0):
    """The night's standout: counters, Game Score built from its parts, his shots on the rink."""
    side = player["team_side"]
    team = game["teams"][side]
    opp = game["teams"]["home" if side == "away" else "away"]
    color = team["color"]
    base = _bg(team["color"], "#0F1115", team["abbrev"], None, accent=color)
    base = _panel_rgba(base, [M - 24, 250, REEL_W - M + 24, 1520])
    d = ImageDraw.Draw(base)
    d.text((M, 70), f"PLAYER OF THE NIGHT  //  {reason.upper()}", fill=color, font=F("bold", 32))
    d.text((REEL_W - M, 70), _pretty_date(game["date"]), fill=C["muted"], font=F("semibold", 28), anchor="ra")
    lw = logos.paste(base, team["abbrev"], (REEL_W - M - 10, 360), height=150, max_w=180, anchor="rm")
    name_f = _fit(d, player["name"].upper(), "bold", 76, REEL_W - 2 * M - (lw + 30 if lw else 0) - 10, 44)
    d.text((M + 10, 300), player["name"].upper(), fill=C["text"], font=name_f)
    where = "@" if not team["is_home"] else "vs"
    pos = {"L": "LW", "R": "RW"}.get(player["position"], player["position"])
    d.text((M + 10, 400), f"{team['abbrev']}  ·  {pos}  ·  {where} {opp['abbrev']}  ·  "
           f"{team['score']}–{opp['score']} {'W' if team['won'] else 'L'}", fill=C["body"], font=F("semibold", 32))
    rw = 600
    rink = half_rink(((REEL_W - rw) / 2, 920, (REEL_W + rw) / 2, 920 + rw * 85 / 100))
    shots = [e for e in game["timeline"] if e.get("shooter_id") == player["player_id"] and e.get("x") is not None]
    stats = [("G", player["G"], "{:.0f}"), ("A", player["A"], "{:.0f}"), ("SOG", player["SOG"], "{:.0f}"),
             ("xG", player["ixG"], "{:.2f}")]
    parts = player.get("gs_parts", {})
    path = _out_path(f"{game['date'][:10]}_{game['game_id']}_spotlight.mp4")
    vid = Video(path, REEL_W, REEL_H)
    n = int(seconds * FPS)
    bar_x0, bar_x1, bar_y = M + 10, REEL_W - M - 10, 760
    pos_total = sum(v for v in parts.values() if v > 0) or 1
    for i in range(n):
        t = i / FPS
        img = base.copy()
        dd = ImageDraw.Draw(img)
        # counters
        cw = (REEL_W - 2 * M) / 4
        for k, (label, val, fmt) in enumerate(stats):
            p = ease((t - 0.4 - 0.15 * k) / 1.0)
            cx = M + cw * (k + 0.5)
            dd.text((cx, 520), fmt.format(val * p), fill=C["text"], font=F("bold", 96), anchor="mm")
            dd.text((cx, 600), label, fill=C["muted"], font=F("semibold", 30), anchor="mm")
        # Game Score bar, built part by part
        dd.text((bar_x0, bar_y - 70), "GAME SCORE", fill=C["muted"], font=F("semibold", 30))
        x = bar_x0
        shown = 0.0
        for k, (key, label, col) in enumerate(PARTS):
            v = parts.get(key, 0)
            if v <= 0:
                continue
            p = ease((t - 2.0 - 0.45 * k) / 0.45)
            w = (bar_x1 - bar_x0) * v / pos_total * p
            if w > 1:
                dd.rectangle([x, bar_y, x + w, bar_y + 46], fill=col)
                short = {"scoring": "G + A", "shots": "SHOTS", "play5": "5V5 SHOTS",
                         "goals5": "5V5 GOALS", "other": "OTHER"}[key]
                if p >= 1 and w > 90:
                    dd.text((x + w / 2, bar_y + 70), short, fill=col, font=F("semibold", 20), anchor="mm")
            x += w
            shown += v * p
        dd.text((bar_x1, bar_y - 70), _num(sum(parts.values()) if t > 4.6 else shown), fill=color,
                font=F("bold", 52), anchor="ra")
        # his shots
        if t > 4.4:
            rink.paste(img)
            dd = ImageDraw.Draw(img)
            for k, e in enumerate(shots):
                st = t - 4.6 - 0.25 * k
                if st <= 0:
                    continue
                pop = 1.0 + 0.8 * max(0.0, 1 - st / 0.3)
                paste_dot(img, rink.px(e["x"], e["y"]), color, shot_radius(e["xg"], 0.9) * pop,
                          ring=e["goal"], alpha=240 if e["goal"] else 180)
            dd.text((REEL_W / 2, 885), "HIS SHOTS  ·  ring = goal", fill=C["muted"], font=F("semibold", 24),
                    anchor="mm")
        if t > seconds - 2.6:
            _fade_text(dd, (REEL_W / 2, 1470), "Full breakdown on our page  →", F("bold", 40), C["accent"],
                       (t - (seconds - 2.6)) / 0.5, anchor="mm")
        _reel_footer(dd)
        vid.add(img)
    return vid.close()


# -------------------------------------------------------- game of the night ---
def drama(game):
    """(score, reason) for picking the game of the night."""
    a, h = game["teams"]["away"], game["teams"]["home"]
    win, lose = (a, h) if a["won"] else (h, a)
    total_xg = a["xg"] + h["xg"]
    upset = max(0.0, lose["xg"] - win["xg"])
    goals = a["score"] + h["score"]
    score = 0.45 * total_xg + 1.6 * upset + (1.5 if game["outcome"] in ("OT", "SO") else 0) \
        + (0.8 if abs(a["score"] - h["score"]) <= 1 else 0) + 0.15 * goals
    if upset >= 0.8:
        reason = (f"Upset: the {win['common_name']} won despite losing the xG battle "
                  f"{win['xg']:.2f}–{lose['xg']:.2f}")
    elif game["outcome"] in ("OT", "SO"):
        reason = f"Needed {'overtime' if game['outcome'] == 'OT' else 'a shootout'}: " \
                 f"{a['abbrev']} {a['xg']:.2f} xG vs {h['abbrev']} {h['xg']:.2f}"
    elif total_xg >= 7:
        reason = f"{total_xg:.1f} expected goals of chaos"
    else:
        reason = f"{win['common_name']} win it on {win['xg']:.2f} xG to {lose['xg']:.2f}"
    return score, reason


def spotlight_candidate(games):
    """Best hat trick or 4+ point night across these analysed games, or None."""
    best = None
    for g in games:
        for p in g["players"]:
            pts = p["G"] + p["A"]
            if p["G"] >= 3 or pts >= 4:
                if best is None or p["game_score"] > best[1]["game_score"]:
                    reason = "hat trick" if p["G"] >= 3 else f"{pts}-point night"
                    best = (g, p, reason)
    return best
