"""Instagram Stories (1080x1920 images, no captions or stickers via the API):

  slate       game days, ~3 hours before the first puck drop (not before 10 AM ET): tonight's
              games with each team's record, 5v5 xG share and an "xG favourite"
  final       minutes after each final: vertical score card pointing to the full breakdown
  scoreboard  once the slate is done: every result with the expected goals beside the score

Content stays inside Instagram's story safe zone (y 250-1670). Failures are logged and skipped.
"""
import logging
from datetime import date as Date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from PIL import ImageDraw

import logos
from cards import (C, F, M, _distinct, _ellipsize, _fit, _game_label, _num, _out_path, _pretty_date,
                   _save, cover_canvas, cover_headline)
from config import IG_HANDLE
from metrics import team_color

log = logging.getLogger("stories")
ET = ZoneInfo("America/New_York")
SW, SH = 1080, 1920
SAFE_TOP, SAFE_BOTTOM = 250, 1670
SLATE_LEAD = timedelta(hours=3)
PER_FRAME = 5


# ---------------------------------------------------------------- shared ---
def _base(left="#00FF88", right="#0F1115", left_ab=None, right_ab=None, accent=C["accent"]):
    img, d = cover_canvas(team_color(None, left_ab) if left_ab else left,
                          team_color(None, right_ab) if right_ab else right,
                          left_ab, right_ab, panel=None, accent=accent, size=(SW, SH))
    return img, d


def _panel(img, box, alpha=228):
    from PIL import Image
    from cards import _hex_rgb
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(over).rounded_rectangle(box, radius=28, fill=(*_hex_rgb(C["bg"]), alpha),
                                           outline=(*_hex_rgb(C["panel_border"]), 255), width=2)
    out = img.convert("RGBA")
    out.alpha_composite(over)
    return out.convert("RGB")


def _footer(d):
    d.text((SW / 2, SAFE_BOTTOM - 30), f"{IG_HANDLE}  ·  Unofficial · not affiliated with the NHL",
           fill=C["muted"], font=F("regular", 24), anchor="mm")


def _team_form(records, abbrev):
    """Record and 5v5 xG share from the season store."""
    w = l = otl = 0
    xgf = xga = 0.0
    for rec in records:
        t = rec["teams"].get(abbrev)
        if not t:
            continue
        if t["won"]:
            w += 1
        elif t.get("otl"):
            otl += 1
        else:
            l += 1
        xgf += t.get("xgf5", 0)
        xga += t.get("xga5", 0)
    share = 100 * xgf / (xgf + xga) if xgf + xga else None
    return {"record": f"{w}-{l}-{otl}", "gp": w + l + otl, "xg5_pct": share}


def _start_et(g):
    try:
        return datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")).astimezone(ET)
    except (KeyError, ValueError):
        return None


def _time_label(dt):
    return dt.strftime("%-I:%M %p").replace(":00 ", " ") + " ET" if dt else "TBD"


# ----------------------------------------------------------------- slate ---
def slate_frames(day, games, records):
    """Tonight's games, PER_FRAME per story frame."""
    games = sorted(games, key=lambda g: g.get("startTimeUTC", ""))
    frames = []
    chunks = [games[i:i + PER_FRAME] for i in range(0, len(games), PER_FRAME)]
    for n, chunk in enumerate(chunks, 1):
        first = chunk[0]
        img, d = _base(left_ab=first["awayTeam"]["abbrev"], right_ab=first["homeTeam"]["abbrev"])
        img = _panel(img, [M - 24, 420, SW - M + 24, 1600])
        d = ImageDraw.Draw(img)
        d.text((M, SAFE_TOP + 20), "TONIGHT'S SLATE", fill=C["accent"], font=F("bold", 64))
        sub = Date.fromisoformat(day).strftime("%A, %B %-d").upper()
        if len(chunks) > 1:
            sub += f"  ·  {n}/{len(chunks)}"
        d.text((M, SAFE_TOP + 100), sub, fill=C["text"], font=F("semibold", 32))
        row_h = (1600 - 450) / PER_FRAME
        y = 450
        for g in chunk:
            a, h = g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]
            fa, fh = _team_form(records, a), _team_form(records, h)
            cy = y + row_h / 2 - 10
            for ab, x, anchor in ((a, M + 70, "mm"), (h, SW - M - 70, "mm")):
                if not logos.paste(img, ab, (x, cy - 20), height=110, max_w=130, anchor="mm"):
                    d.text((x, cy - 20), ab, fill=C["text"], font=F("bold", 52), anchor="mm")
            for f, x in ((fa, M + 70), (fh, SW - M - 70)):
                d.text((x, cy + 58), f["record"], fill=C["body"], font=F("semibold", 24), anchor="mm")
            d.text((SW / 2, cy - 52), _time_label(_start_et(g)), fill=C["text"], font=F("bold", 38),
                   anchor="mm")
            d.text((SW / 2, cy - 8), "@", fill=C["faint"], font=F("bold", 30), anchor="mm")
            if fa["xg5_pct"] is not None and fh["xg5_pct"] is not None:
                fav = a if fa["xg5_pct"] >= fh["xg5_pct"] else h
                d.text((SW / 2, cy + 34), f"5v5 xG%  {fa['xg5_pct']:.0f}  –  {fh['xg5_pct']:.0f}",
                       fill=C["body"], font=F("semibold", 26), anchor="mm")
                d.text((SW / 2, cy + 72), f"xG favourite: {fav}", fill=team_color(None, fav),
                       font=F("bold", 26), anchor="mm")
            if g is not chunk[-1]:
                d.line([(M + 10, y + row_h - 6), (SW - M - 10, y + row_h - 6)], fill=C["panel_border"], width=2)
            y += row_h
        d.text((SW / 2, 1630), "Breakdowns land minutes after each final", fill=C["accent"],
               font=F("bold", 30), anchor="mm")
        frames.append(img)
    return frames


# ----------------------------------------------------------------- final ---
def final_frame(game, copy=None):
    a, h = game["teams"]["away"], game["teams"]["home"]
    away_c, home_c = _distinct(a["color"], h["color"])
    img, d = _base(left_ab=a["abbrev"], right_ab=h["abbrev"])
    img = _panel(img, [M - 24, 470, SW - M + 24, 1330])
    d = ImageDraw.Draw(img)
    status = {"OT": "FINAL · OT", "SO": "FINAL · SHOOTOUT"}.get(game["outcome"], "FINAL")
    d.text((M, SAFE_TOP + 20), status, fill=C["accent"], font=F("bold", 64))
    d.text((M, SAFE_TOP + 100), f"{_game_label(game)}  ·  {_pretty_date(game['date'])}", fill=C["text"],
           font=F("semibold", 30))
    cy = 700
    for t, x, col in ((a, M + 130, away_c), (h, SW - M - 130, home_c)):
        if not logos.paste(img, t["abbrev"], (x, cy), height=210, max_w=250, anchor="mm"):
            d.text((x, cy), t["abbrev"], fill=col, font=F("bold", 90), anchor="mm")
        d.text((x, cy + 150), t["common_name"].upper(), fill=C["muted"], font=F("semibold", 30), anchor="mm")
    d.text((SW / 2 - 30, cy), str(a["score"]), fill=C["text"] if a["won"] else C["muted"], font=F("bold", 170),
           anchor="rm")
    d.text((SW / 2 + 30, cy), str(h["score"]), fill=C["text"] if h["won"] else C["muted"], font=F("bold", 170),
           anchor="lm")
    y = cy + 230
    d.text((SW / 2, y), "EXPECTED GOALS", fill=C["muted"], font=F("semibold", 28), anchor="mm")
    d.text((SW / 2 - 30, y + 70), f"{a['xg']:.2f}", fill=away_c, font=F("bold", 72), anchor="rm")
    d.text((SW / 2 + 30, y + 70), f"{h['xg']:.2f}", fill=home_c, font=F("bold", 72), anchor="lm")
    head = cover_headline(game, copy)
    if head:
        hf = F("bold", 40)
        words, lines, cur = head.split(), [], ""
        for w in words:
            if d.textlength(f"{cur} {w}".strip(), font=hf) <= SW - 2 * M:
                cur = f"{cur} {w}".strip()
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        ly = 1380
        for line in lines[:3]:
            d.text((SW / 2, ly), line, fill=C["text"], font=hf, anchor="mm")
            ly += 52
    d.text((SW / 2, 1580), "Full breakdown on our page  →", fill=C["accent"], font=F("bold", 38), anchor="mm")
    _footer(d)
    return img


# ------------------------------------------------------------ scoreboard ---
def scoreboard_frames(day, analyses, per_frame=8):
    games = sorted(analyses, key=lambda g: g["game_id"])
    chunks = [games[i:i + per_frame] for i in range(0, len(games), per_frame)]
    frames = []
    for n, chunk in enumerate(chunks, 1):
        img, d = _base()
        img = _panel(img, [M - 24, 420, SW - M + 24, 1560])
        d = ImageDraw.Draw(img)
        d.text((M, SAFE_TOP + 20), "LAST NIGHT'S SCORES", fill=C["accent"], font=F("bold", 60))
        sub = Date.fromisoformat(day).strftime("%A, %B %-d").upper() + "  ·  with expected goals"
        if len(chunks) > 1:
            sub += f"  ·  {n}/{len(chunks)}"
        d.text((M, SAFE_TOP + 100), sub, fill=C["text"], font=_fit(d, sub, "semibold", 30, SW - 2 * M, 20))
        row_h = (1560 - 440) / per_frame
        y = 440
        for g in chunk:
            a, h = g["teams"]["away"], g["teams"]["home"]
            away_c, home_c = _distinct(a["color"], h["color"])
            cy = y + row_h / 2
            logos.paste(img, a["abbrev"], (M + 40, cy), height=min(84, row_h - 40), max_w=100, anchor="mm")
            logos.paste(img, h["abbrev"], (SW - M - 40, cy), height=min(84, row_h - 40), max_w=100, anchor="mm")
            d.text((M + 110, cy), a["abbrev"], fill=away_c, font=F("bold", 34), anchor="lm")
            d.text((SW - M - 110, cy), h["abbrev"], fill=home_c, font=F("bold", 34), anchor="rm")
            sf = F("bold", 56)
            d.text((SW / 2 - 40, cy - 14), str(a["score"]), fill=C["text"] if a["won"] else C["muted"], font=sf,
                   anchor="rm")
            d.text((SW / 2, cy - 14), "–", fill=C["faint"], font=F("bold", 36), anchor="mm")
            d.text((SW / 2 + 40, cy - 14), str(h["score"]), fill=C["text"] if h["won"] else C["muted"], font=sf,
                   anchor="lm")
            ext = {"OT": " OT", "SO": " SO"}.get(g["outcome"], "")
            d.text((SW / 2, cy + 36), f"xG {a['xg']:.1f} – {h['xg']:.1f}{ext}", fill=C["body"],
                   font=F("semibold", 24), anchor="mm")
            if g is not chunk[-1]:
                d.line([(M + 10, y + row_h), (SW - M - 10, y + row_h)], fill=C["panel_border"], width=2)
            y += row_h
        if n == len(chunks):
            d.text((SW / 2, 1610), "Game of the Night drops at 11:30 AM ET", fill=C["accent"],
                   font=F("bold", 34), anchor="mm")
        frames.append(img)
    return frames


# --------------------------------------------------------------- posting ---
def _done(state, key):
    return key in state.data.get("stories", {})


def _record(state, key, info):
    state.refresh()
    state.data.setdefault("stories", {})[key] = {**info, "at": datetime.now(timezone.utc).isoformat(
        timespec="seconds")}
    state._save(f"Record story {key}")


def _post(state, key, frames, title, mode):
    from publisher import publish_story
    paths = [_save(img, f"story_{key}_{i}.jpg") for i, img in enumerate(frames, 1)]
    res = publish_story(paths, key=key, title=title, mode=mode)
    _record(state, key, {"title": title, "frames": len(paths), "mode": res.get("mode"),
                         "media_ids": res.get("media_ids")})
    log.info("Posted story %s (%d frames, %s)", title, len(paths), res.get("mode"))


def maybe_post_slate(source, day, state, records, mode=None, now=None):
    """Post tonight's slate once we're within SLATE_LEAD of the first puck drop."""
    key = f"slate-{day}"
    if _done(state, key):
        return
    from nhl_fetcher import GAME_TYPES
    try:
        games = [g for g in source.score(day).get("games", []) if g.get("gameType") in GAME_TYPES]
    except Exception as exc:
        log.warning("Slate %s: schedule unavailable (%s)", day, exc)
        return
    upcoming = [g for g in games if g.get("gameState") in ("FUT", "PRE")]
    if not upcoming:
        return
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    first = min((_start_et(g) for g in upcoming if _start_et(g)), default=None)
    if first is None or now < max(first - SLATE_LEAD, now.replace(hour=10, minute=0, second=0)):
        return
    try:
        _post(state, key, slate_frames(day, games, records), f"Tonight's slate — {day}", mode)
    except Exception:
        log.exception("Slate story failed for %s", day)


def post_final(game, state, copy=None, mode=None):
    key = f"final-{game['game_id']}"
    if _done(state, key):
        return
    try:
        _post(state, key, [final_frame(game, copy)], f"Final story — {game['matchup']}", mode)
    except Exception:
        log.exception("Final story failed for %s", game["game_id"])


def post_scoreboard(day, analyses, state, mode=None):
    key = f"board-{day}"
    if _done(state, key) or not analyses:
        return
    try:
        _post(state, key, scoreboard_frames(day, analyses), f"Scoreboard — {day}", mode)
    except Exception:
        log.exception("Scoreboard story failed for %s", day)
