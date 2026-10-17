"""Animated posts: render, caption and publish, never twice (state["reels"]).

  replay slide       every game carousel (slide 2): shot map + xG race, synced
  game of the night  one Reel per night, once every game on the slate is final
  spotlight          one Reel per night for the best hat trick / 4+ point game, if any
  ovi / crosby       a Reel right after a Capitals / Penguins post when Ovechkin scores or
                     Crosby passes someone on the all-time points list
A failure here is logged and skipped: animated posts never block the regular carousels.
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone

import animations as A
from content_generator import DISCLOSURE
from hashtags import TEAM_TAGS, game_tags, line as tag_line
from publisher import publish_reel

log = logging.getLogger("reels")

REPLAY_ALT = ("Animated replay: every shot appears on the rink in game order, sized by its expected "
              "goals value, while the expected goals race and the score update")
REPLAY_THUMB_MS = 13000          # thumbnail = the finished replay
NOTE = "xG = our shot-quality model, trained on 237k NHL shots. Data: NHL play-by-play."


def replay_slide(game):
    try:
        return A.render_game_replay(game, "slide")
    except Exception:
        log.exception("Replay slide failed for %s", game["game_id"])
        return None


# ------------------------------------------------------------------ state ---
def _done(state, key):
    return key in state.data.get("reels", {})


def _record(state, key, info):
    state.refresh()
    state.data.setdefault("reels", {})[key] = {**info, "at": datetime.now(timezone.utc).isoformat(
        timespec="seconds")}
    state._save(f"Record reel {key}")


MORNING = (11, 30)   # nightly Reels go out the next day at 11:30 AM ET, not at 1 AM


def morning_after(day, now=None):
    """ISO time for the morning after `day` (ET), or None if that's already past."""
    from datetime import date, time, timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    due = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(*MORNING), tzinfo=et)
    now = now or datetime.now(timezone.utc)
    if due <= now + timedelta(minutes=10):
        return None
    return due.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _publish(state, key, path, caption, title, mode, thumb_ms, due_at=None):
    res = publish_reel(path, caption, key=key, title=title, mode=mode, thumb_ms=thumb_ms, due_at=due_at)
    _record(state, key, {"title": title, "media_id": res["media_id"],
                         "permalink": res.get("permalink"), "mode": res.get("mode"),
                         "scheduled_for": res.get("scheduled_for")})
    log.info("Posted reel %s (%s)", title, res.get("mode"))
    return res


def _name_tag(name):
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "#" + re.sub(r"[^A-Za-z0-9]", "", ascii_)


def _caption(body, tags):
    return f"{body.strip()}\n\n{NOTE}\n{DISCLOSURE}\n\n{tag_line(tags)}"


# -------------------------------------------------------------- milestones ---
def post_milestone(ev, state, mode=None):
    key = f"{ev['kind']}-{ev['game_id']}"
    if _done(state, key):
        return None
    try:
        if ev["kind"] == "ovi":
            path = A.render_ovi_goal(ev)
            n = ev["after"] - ev["before"]
            lines = "\n".join(f"🎯 {g['line']}" for g in ev["goals"])
            where = "vs" if ev["home"] else "@"
            body = (f"🚨 OVECHKIN {'SCORES' if n == 1 else f'SCORES {n}'} {where} {ev['opp']}. "
                    f"Career goal #{ev['after']:,}{' (NHL record)' if ev['record'] else ''}.\n\n"
                    f"{lines}\n\n{ev['to_next']} to {ev['next_milestone']:,}. "
                    f"{ev['extra'].capitalize()}.\n\nThe farewell tour rolls on. 🏒")
            tags = ["#Ovechkin", "#ALLCAPS", "#NHL", "#Gr8", "#HockeyAnalytics"]
            title = f"Ovechkin goal #{ev['after']}"
            thumb = 9000
        else:
            path = A.render_crosby_climb(ev)
            passed = " and ".join(ev["passed"][-2:])
            body = (f"📈 Sidney Crosby passes {passed} on the NHL's all-time points list.\n\n"
                    f"{ev['after']:,} career points, #{ev['rank_after']} all-time."
                    + (f" Next up: {ev['next_name']}, {ev['to_next']} away." if ev.get("next_name") else ""))
            tags = ["#Crosby", "#LetsGoPens", "#NHL", "#NHLHistory", "#HockeyAnalytics"]
            title = f"Crosby passes {passed}"
            thumb = 8000
        return _publish(state, key, path, _caption(body, tags), title, mode, thumb)
    except Exception:
        log.exception("Milestone reel %s failed", key)
        return None


# ------------------------------------------------------------ end of night ---
def end_of_night(source, day, state, mode=None):
    """Game of the night + player spotlight, once every game on `day` is final."""
    from metrics import analyze_game
    from nhl_fetcher import FINAL_STATES, GAME_TYPES, load_game
    gkey, skey = f"gotn-{day}", f"spot-{day}"
    if _done(state, gkey) and _done(state, skey):
        return
    try:
        games = [g for g in source.score(day).get("games", []) if g.get("gameType") in GAME_TYPES]
    except Exception as exc:
        log.warning("End of night %s: schedule unavailable (%s)", day, exc)
        return
    if not games or any(g.get("gameState") not in FINAL_STATES for g in games):
        return
    analyses = []
    for g in games:
        try:
            analyses.append(analyze_game(load_game(source, g)))
        except Exception:
            log.exception("End of night: skipping %s", g["id"])
    if not analyses:
        return
    if not _done(state, gkey):
        try:
            game = max(analyses, key=lambda g: A.drama(g)[0])
            reason = A.drama(game)[1]
            from cards import _game_label
            path = A.render_game_replay(game, "reel", kicker=f"GAME OF THE NIGHT  //  {_game_label(game)}",
                                        headline=reason)
            a, h = game["teams"]["away"], game["teams"]["home"]
            ext = {"OT": " (OT)", "SO": " (SO)"}.get(game["outcome"], "")
            body = (f"🎬 Game of the Night: {a['abbrev']} {a['score']} @ {h['abbrev']} {h['score']}{ext}\n"
                    f"{reason}.\n\nEvery shot, sized by its expected-goals value, as the xG race plays "
                    f"out. Full breakdown on our page.")
            _publish(state, gkey, path, _caption(body, game_tags(a["abbrev"], h["abbrev"], game["game_id"])),
                     f"Game of the night — {day}", mode, 14500, due_at=morning_after(day))
        except Exception:
            log.exception("Game of the night reel failed for %s", day)
    if not _done(state, skey):
        try:
            cand = A.spotlight_candidate(analyses)
            if not cand:
                _record(state, skey, {"title": "no spotlight tonight", "mode": "none"})
            else:
                game, p, why = cand
                path = A.render_spotlight(game, p, why)
                side = p["team_side"]
                team = game["teams"][side]
                opp = game["teams"]["home" if side == "away" else "away"]
                body = (f"⭐ Player of the Night: {p['name']} ({team['abbrev']}), {why}.\n\n"
                        f"{p['G']}G {p['A']}A, {p['SOG']} shots, {p['ixG']:.2f} xG and a "
                        f"{p['game_score']:.2f} Game Score "
                        f"{'vs' if team['is_home'] else '@'} {opp['abbrev']}.")
                tags = ["#NHL", "#HockeyAnalytics", TEAM_TAGS.get(team["abbrev"], "#NHLStats"),
                        "#HatTrick" if p["G"] >= 3 else "#NHLStats", _name_tag(p["name"])]
                due = morning_after(day)
                if due:  # 15 minutes after the game of the night, not on top of it
                    due = (datetime.fromisoformat(due.replace("Z", "+00:00"))
                           .replace(minute=MORNING[1] + 15).isoformat().replace("+00:00", "Z"))
                _publish(state, skey, path, _caption(body, tags), f"Spotlight: {p['name']} — {day}",
                         mode, 9000, due_at=due)
        except Exception:
            log.exception("Spotlight reel failed for %s", day)
