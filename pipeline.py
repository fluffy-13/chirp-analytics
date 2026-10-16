"""Game-night and weekly jobs.

live:    poll the night's games every couple of minutes; as each one goes final, build its
         carousel (game + both teams) and post it — typically 5-10 minutes after the horn.
games:   process every finished game on a date (backfill / manual runs).
weekly:  top/bottom 10 skaters and teams for a Monday-Sunday week.

Everything posted is recorded in a small state file (on the `state` branch in GitHub Actions)
so no game or week is ever posted twice, even across overlapping runs.
"""
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from cards import cover_headline, render_game_carousel, render_weekly_carousel, _range_label
from config import OUTPUT_DIR, POST_MODE, TIMEZONE
from content_generator import (build_game_caption, build_weekly_caption, generate_game_copy)
from git_store import default_store
from ledger import Ledger
from trackers import tracker_slides
from metrics import aggregate_week, analyze_game
from nhl_fetcher import FINAL_STATES, GAME_TYPES, load_game
from publisher import publish_carousel

log = logging.getLogger("pipeline")
ET = ZoneInfo(TIMEZONE)
ACTIVE_STATES = {"LIVE", "CRIT", "PRE"}
MAX_FAILURES = 4


# -------------------------------------------------------------------- state ---
class State:
    FILE = "posted.json"

    def __init__(self, store=None):
        self.store = store or default_store("state", OUTPUT_DIR.parent / "state")
        raw = self.store.read(self.FILE)
        self.data = json.loads(raw) if raw else {}
        self.data.setdefault("games", {})
        self.data.setdefault("weeks", {})
        self.data.setdefault("failures", {})
        self.data.setdefault("intros", {})

    def refresh(self):
        """Merge in anything another run recorded since we loaded (never lose an entry)."""
        raw = self.store.read(self.FILE)
        if not raw:
            return
        fresh = json.loads(raw)
        for k in ("games", "weeks", "intros"):
            merged = dict(fresh.get(k, {}))
            merged.update(self.data.get(k, {}))
            self.data[k] = merged
        failures = dict(fresh.get("failures", {}))
        for key, n in self.data.get("failures", {}).items():
            failures[key] = max(n, failures.get(key, 0))
        self.data["failures"] = failures

    def done(self, kind, key):
        return str(key) in self.data[kind]

    def gave_up(self, key):
        return self.data["failures"].get(str(key), 0) >= MAX_FAILURES

    def record(self, kind, key, info):
        self.refresh()
        self.data[kind][str(key)] = {**info, "at": _utc_now()}
        self.data["failures"].pop(str(key), None)
        self._save(f"Record {kind[:-1]} {key}")

    def fail(self, key):
        self.refresh()
        n = self.data["failures"].get(str(key), 0) + 1
        self.data["failures"][str(key)] = n
        self._save(f"Failure {n} for {key}")
        return n

    def _save(self, message):
        self.store.write({self.FILE: json.dumps(self.data, indent=1, sort_keys=True).encode()},
                         message)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------- games ---
def _title(game):
    a, h = game["teams"]["away"], game["teams"]["home"]
    extra = {"OT": " (OT)", "SO": " (SO)"}.get(game["outcome"], "")
    return f"{a['abbrev']} {a['score']} @ {h['abbrev']} {h['score']}{extra} — {game['date'][:10]}"


def _pbp_complete(bundle):
    return any(p.get("typeDescKey") == "game-end" for p in bundle["pbp"].get("plays", []))


def post_game(source, score_game, state, mode=None, bundle=None):
    """Build and publish one game's carousel. Returns the publish result."""
    bundle = bundle or load_game(source, score_game)
    game = analyze_game(bundle)
    ledger = _ledger(state)
    try:
        context = ledger.context(game) if ledger else None
    except Exception:
        log.exception("Season context unavailable for %s", game["game_id"])
        context = None
    copy = generate_game_copy(game)
    extra, extra_alts = tracker_slides(source, game, bundle)
    paths = render_game_carousel(game, context, headline=cover_headline(game, copy), extra=extra)
    caption = build_game_caption(copy, game)
    a, h = game["teams"]["away"], game["teams"]["home"]
    alts = [f"{_title(game)}. Expected goals {a['abbrev']} {a['xg']:.2f}, {h['abbrev']} {h['xg']:.2f}.",
            f"Game breakdown: {_title(game)}, with the expected goals flow chart and three stars.",
            f"{a['name']} team breakdown",
            f"{a['name']} player impact: every skater's Game Score split into what drove it",
            f"{h['name']} team breakdown",
            f"{h['name']} player impact: every skater's Game Score split into what drove it"]
    alts += extra_alts
    result = publish_carousel(paths, caption, key=f"game-{game['game_id']}", title=_title(game),
                              meta={"game_id": game["game_id"], "date": game["date"],
                                    "alt_texts": alts}, mode=mode)
    state.record("games", game["game_id"], {"title": _title(game), "media_id": result["media_id"],
                                            "permalink": result.get("permalink"),
                                            "mode": result.get("mode")})
    log.info("Posted %s (%s)", _title(game), result.get("mode"))
    if ledger:
        try:
            ledger.add(game)
            ledger.save(f"Ledger: {_title(game)}")
        except Exception:  # season context is a nice-to-have; never fail a posted game over it
            log.exception("Could not update the ledger for %s", game["game_id"])
    return result


def _ledger(state):
    try:
        return Ledger(state.store)
    except Exception:
        log.exception("Could not load the ledger; posting without season context")
        return None


def finished_games(source, day):
    games = source.score(day).get("games", [])
    return [g for g in games if g.get("gameType") in GAME_TYPES]


def run_games(source, day, state, mode=None, game_id=None, force=False):
    """Post every finished game on `day` that hasn't been posted yet."""
    failed = []
    for g in finished_games(source, day):
        if game_id and g["id"] != int(game_id):
            continue
        if g.get("gameState") not in FINAL_STATES:
            continue
        if state.done("games", g["id"]) and not force:
            log.info("Already posted %s, skipping", g["id"])
            continue
        try:
            post_game(source, g, state, mode)
        except Exception:
            log.exception("Game %s failed", g["id"])
            failed.append(g["id"])
            state.fail(g["id"])
    return failed


# ---------------------------------------------------------------------- live ---
def slate_dates(now_et):
    """Tonight's games, plus last night's while late West-coast games may still be wrapping up."""
    today = now_et.date()
    return [today - timedelta(days=1), today] if now_et.hour < 9 else [today]


def _start_time(g):
    try:
        return datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def run_live(source, state, mode=None, poll=120, max_runtime=5.6 * 3600, shift_wait=360,
             lookahead=6 * 3600, now=None, sleep=time.sleep):
    """Poll until every game in the window is posted (or the runtime budget is spent)."""
    now = now or (lambda: datetime.now(timezone.utc))
    started = now()
    first_final = {}
    gave_up = []
    while True:
        t = now()
        if (t - started).total_seconds() > max_runtime:
            log.info("Runtime budget spent; the next scheduled run takes over")
            break
        pending = 0
        for day in slate_dates(t.astimezone(ET)):
            try:
                games = finished_games(source, day.isoformat())
            except Exception as exc:
                log.warning("Schedule fetch for %s failed: %s", day, exc)
                pending += 1
                continue
            for g in games:
                gid, gs = g["id"], g.get("gameState")
                if state.done("games", gid) or state.gave_up(gid):
                    continue
                if gs in FINAL_STATES:
                    first_final.setdefault(gid, t)
                    waited = (t - first_final[gid]).total_seconds()
                    try:
                        bundle = load_game(source, g)
                        complete = _pbp_complete(bundle) and bundle["shifts"]
                        if not complete and waited < shift_wait:
                            log.info("Game %s final; waiting for complete data (%ds)", gid,
                                     int(waited))
                            pending += 1
                            continue
                        post_game(source, g, state, mode, bundle=bundle)
                    except Exception:
                        log.exception("Game %s failed", gid)
                        if state.fail(gid) >= MAX_FAILURES:
                            gave_up.append(gid)
                        else:
                            pending += 1
                elif gs in ACTIVE_STATES:
                    pending += 1
                else:  # FUT: only keep waiting if it starts soon
                    st = _start_time(g)
                    if st and (st - t).total_seconds() < lookahead:
                        pending += 1
        if not pending:
            log.info("Nothing left to post in this window")
            break
        sleep(poll)
    return gave_up


# -------------------------------------------------------------------- weekly ---
def last_completed_week(today_et):
    """Monday-Sunday week ending on the most recent Sunday before today."""
    end = today_et - timedelta(days=today_et.weekday() + 1)
    return end - timedelta(days=6), end


def run_weekly(source, state, end=None, mode=None, force=False, min_gp=2):
    if end:
        end_d = date.fromisoformat(end)
        start_d = end_d - timedelta(days=6)
    else:
        start_d, end_d = last_completed_week(datetime.now(ET).date())
    key = end_d.isoformat()
    if state.done("weeks", key) and not force:
        log.info("Week ending %s already posted", key)
        return None
    analyses = []
    d = start_d
    while d <= end_d:
        for g in finished_games(source, d.isoformat()):
            if g.get("gameState") in FINAL_STATES:
                try:
                    analyses.append(analyze_game(load_game(source, g)))
                except Exception:
                    log.exception("Skipping game %s in weekly", g["id"])
        d += timedelta(days=1)
    if not analyses:
        log.info("No finished games between %s and %s", start_d, end_d)
        return None
    week = aggregate_week(analyses, start_d.isoformat(), end_d.isoformat(), min_gp=min_gp)
    paths = render_weekly_carousel(week)
    caption = build_weekly_caption(week)
    title = f"Weekly report — {_range_label(week['start'], week['end'])}"
    alts = [f"Weekly analytics report, {title}", "Top 10 skaters by Game Score",
            "Bottom 10 skaters by Game Score", "Top 10 teams by 5v5 expected goals share",
            "Bottom 10 teams by 5v5 expected goals share"]
    result = publish_carousel(paths, caption, key=f"week-{key}", title=title,
                              meta={"week_end": key, "alt_texts": alts}, mode=mode)
    state.record("weeks", key, {"title": title, "media_id": result["media_id"],
                                "mode": result.get("mode"), "games": week["games"]})
    return result


# -------------------------------------------------------------------- intros ---
INTRO_TITLES = {"standings": "Intro: the real standings", "finishing": "Intro: hot hands vs. snakebitten",
                "goalies": "Intro: goalies stealing games"}


def run_intro(which, state, mode=None, force=False):
    """One-off season-so-far post, from the approved data snapshot."""
    from intro_cards import render_intro
    if state.done("intros", which) and not force:
        log.info("Intro %s already posted", which)
        return None
    paths, caption, alts = render_intro(which)
    result = publish_carousel(paths, caption, key=f"intro-{which}", title=INTRO_TITLES[which],
                              meta={"intro": which, "alt_texts": alts}, mode=mode)
    state.record("intros", which, {"title": INTRO_TITLES[which], "media_id": result["media_id"],
                                   "permalink": result.get("permalink"), "mode": result.get("mode")})
    log.info("Posted %s (%s)", INTRO_TITLES[which], result.get("mode"))
    return result
