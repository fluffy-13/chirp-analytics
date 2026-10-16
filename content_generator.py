"""Caption + hook copy. Gemini writes the voice; it is never allowed to invent numbers."""
import json
import logging
import re
import time
import unicodedata

from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MODEL_FALLBACKS, IG_HANDLE

log = logging.getLogger(__name__)

NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# Claims the fact sheet can never support (it holds one game, no history or league context)
UNSUPPORTED_CLAIM_RE = re.compile(
    r"\b(top \d+|record|career|season|league[- ]leading|leads the league|ranks?|"
    r"first time|streak|all[- ]time|ever)\b", re.IGNORECASE)
HOOK_MAX = 70
CAPTION_MAX = 2200  # Instagram hard limit

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "hook": {"type": "STRING"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["hook", "caption", "hashtags"],
}


def _n(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def fact_sheet(post):
    p = post["player"]
    lines = [
        f"Game: {post['matchup']} on {post['date']}",
        f"Player: {post['player_name']} ({post['position']}, {post['team']})",
        f"Headline stat: {post['headline_value']} {post['headline_label']}",
        f"HIS OWN (individual) stats: {_n(p['G'], 'goal')}, {_n(p['A'], 'assist')}, "
        f"{_n(p['SOG'], 'shot')} on goal, {_n(p['iCF'], 'shot attempt')}, "
        f"{_n(p['iHD'], 'attempt')} from the home-plate area, "
        f"{p['ixG']:.2f} individual xG, {p['toi']} time on ice, Game Score {p['game_score']:.2f}",
    ]
    on_ice = p["CF"] + p["CA"]
    if on_ice:
        lines.append(f"ON-ICE at 5v5 (all players, both teams, while he was on the ice): "
                     f"shot attempts {p['CF']}-{p['CA']} in his team's favour "
                     f"({100 * p['CF'] / on_ice:.0f}% CF)")
    lines.append("TEAM totals for the game, xG: "
                 + ", ".join(f"{k} {v:.2f}" for k, v in post["team_xg"].items()))
    if p["G"] and p["ixG"] and p["G"] > p["ixG"]:
        lines.append(f"Context: he scored {p['G']} goals on {p['ixG']:.2f} individual xG "
                     f"(finishing above expectation).")
    return "\n".join(lines)


def _numbers(text):
    text = re.sub(r"#\w+", "", text)  # hashtags may contain digits
    return set(NUM_RE.findall(text))


def _valid(copy, allowed):
    if not copy.get("hook") or not copy.get("caption"):
        return "empty field"
    if len(copy["hook"]) > HOOK_MAX:
        return "hook too long"
    text = copy["hook"] + " " + copy["caption"]
    invented = _numbers(text) - allowed
    if invented:
        return f"numbers not in the data: {sorted(invented)}"
    claim = UNSUPPORTED_CLAIM_RE.search(text)
    if claim:
        return f"unsupported claim '{claim.group(0)}' (no season/record/rank context in the data)"
    return None


def _prompt(facts):
    return f"""You write copy for an NHL analytics Instagram page. Tone: sharp, confident, nerdy but readable. No emojis in the hook.

FACT SHEET (the only source of truth):
{facts}

RULES
- Use ONLY numbers that appear in the fact sheet, written exactly as they appear. Do not round, convert, rank, or add any other number (no league ranks, season totals, or percentages that aren't listed).
- Do not claim anything not supported by the fact sheet (no records, streaks, or "best of the season").
- Keep the categories straight: HIS OWN stats are his alone; ON-ICE stats count every shot by both
  teams while he was on the ice (never call them his, or his line's, individual numbers); TEAM
  totals are the whole team's.
- "xG" here is the page's own shot-quality model; call it xG, never "official".

Return JSON:
- hook: one punchy line for the graphic, max {HOOK_MAX} characters.
- caption: 2–3 sentences explaining why the performance stood out analytically, then a question to drive comments.
- hashtags: 5 relevant hashtags (team + hockey analytics), each starting with #.
"""


_working_model = None


def _model_candidates():
    if _working_model:
        return [_working_model] + [m for m in GEMINI_MODEL_FALLBACKS if m != _working_model]
    seen, out = set(), []
    for m in ([GEMINI_MODEL] if GEMINI_MODEL else []) + GEMINI_MODEL_FALLBACKS:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _should_try_next_model(exc):
    """Retired model (404) or a busy one (503 / 429): move on to the next candidate."""
    text = str(exc)
    return any(k in text for k in ("404", "NOT_FOUND", "no longer available",
                                   "503", "UNAVAILABLE", "high demand",
                                   "429", "RESOURCE_EXHAUSTED"))


def _call_gemini(prompt):
    global _working_model
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.GenerateContentConfig(response_mime_type="application/json",
                                         response_schema=SCHEMA, temperature=0.8)
    last_exc = None
    for model in _model_candidates():
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:
            if _should_try_next_model(exc):
                log.info("Gemini model %s unavailable (%s), trying the next one",
                         model, str(exc)[:60])
                last_exc = exc
                continue
            raise
        if _working_model != model:
            log.info("Using Gemini model %s", model)
        _working_model = model
        return json.loads(resp.text)
    raise RuntimeError(f"No Gemini model available: {last_exc}")


def fallback_copy(post):
    p = post["player"]
    last = post["player_name"].split()[-1] if post["player_name"] else "He"
    hook = f"{last} tilted the ice for {post['team_abbrev']}."
    label = {"GAME SCORE": "Game Score", "INDIVIDUAL xG": "individual xG"}.get(
        post["headline_label"], post["headline_label"])
    caption = (f"{post['player_name']} posted a {post['headline_value']} {label} "
               f"in {post['matchup']}: {p['iCF']} shot attempts, {p['SOG']} on goal"
               + (f", {p['iHD']} from the home-plate area" if p["iHD"] else "")
               + ". Who was the best skater in this one?")
    return {"hook": hook[:HOOK_MAX], "caption": caption, "hashtags": []}


def generate_copy(post, attempts=3):
    facts = fact_sheet(post)
    allowed = _numbers(facts)
    if not GEMINI_API_KEY:
        log.info("No GEMINI_API_KEY set, using template copy")
        return fallback_copy(post)
    prompt = _prompt(facts)
    for attempt in range(1, attempts + 1):
        try:
            copy = _call_gemini(prompt)
        except Exception as exc:  # network/SDK/JSON errors
            log.warning("Gemini call failed (attempt %s): %s", attempt, str(exc)[:200])
            if attempt < attempts:
                time.sleep(15 * attempt)  # busy models usually recover within a minute
            continue
        problem = _valid(copy, allowed)
        if not problem:
            return {**copy, "ai": True}
        log.warning("Rejected AI copy (attempt %s): %s", attempt, problem)
        prompt += f"\n\nYour previous answer was rejected: {problem}. Fix it."
    log.warning("Falling back to template copy")
    return fallback_copy(post)


def _ascii(text):
    """Montréal -> Montreal (hashtags break on accented letters)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def build_caption(copy, post):
    team_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", _ascii(post["team"]))
    tags = ["#NHL", "#HockeyAnalytics", team_tag]
    for t in copy.get("hashtags", []):
        t = "#" + re.sub(r"[^A-Za-z0-9_]", "", _ascii(t.lstrip("#")))
        if len(t) > 1 and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    footnote = ("xG = our shot-quality model, trained on 237k NHL shots from the last two seasons. "
                "Data: NHL play-by-play.")
    caption = f"{copy['caption'].strip()}\n\n{footnote}\n\n{' '.join(tags[:10])}"
    return caption[:CAPTION_MAX]


# ------------------------------------------------------------- game posts ---
def _pct0(v):
    return "n/a" if v is None else f"{v:.0f}%"


def _star_line(p):
    if p["position"] == "G":
        sv = f"{p['sv_pct']:.3f}".lstrip("0") if p["sv_pct"] is not None else "n/a"
        return (f"{p['name']} ({p['team_abbrev']}, goalie): {p['saves']} saves on "
                f"{p['shots_against']} shots, {sv} save percentage, "
                f"{p['gsax']:+.2f} goals saved above expected")
    return (f"{p['name']} ({p['team_abbrev']}): {_n(p['G'], 'goal')}, {_n(p['A'], 'assist')}, "
            f"{_n(p['SOG'], 'shot')} on goal, {p['ixG']:.2f} individual xG, "
            f"Game Score {p['game_score']:.2f}")


def game_fact_sheet(game):
    a, h = game["teams"]["away"], game["teams"]["home"]
    extra = {"OT": " in overtime", "SO": " in a shootout"}.get(game["outcome"], "")
    winner, loser = (a, h) if a["won"] else (h, a)
    lines = [
        f"Final: {winner['name']} beat {loser['name']} {winner['score']}-{loser['score']}{extra} "
        f"on {game['date']} ({a['abbrev']} was the road team).",
        f"Expected goals, all situations: {a['abbrev']} {a['xg']:.2f}, {h['abbrev']} {h['xg']:.2f}.",
        f"5v5 share of expected goals: {a['abbrev']} {_pct0(a['xg5_pct'])}, "
        f"{h['abbrev']} {_pct0(h['xg5_pct'])}.",
        f"5v5 shot attempts: {a['abbrev']} {a['cf5']}, {h['abbrev']} {h['cf5']}.",
        f"Shots on goal: {a['abbrev']} {a['sog']}, {h['abbrev']} {h['sog']}.",
        f"High-danger chances: {a['abbrev']} {a['hd']}, {h['abbrev']} {h['hd']}.",
        f"Power play goals/opportunities: {a['abbrev']} {a['pp_goals']}/{a['pp_opps']}, "
        f"{h['abbrev']} {h['pp_goals']}/{h['pp_opps']}.",
    ]
    xg_winner = a if a["xg"] > h["xg"] else h
    lines.append(f"{xg_winner['name']} won the expected-goals battle"
                 + (" but lost the game." if not xg_winner["won"] else " and the game."))
    lines.append("Three stars (by Game Score):")
    lines += [f"  {i}. {_star_line(p)}" for i, p in enumerate(game["stars"], 1)]
    return "\n".join(lines)


def _game_prompt(facts):
    return f"""You write captions for an NHL analytics Instagram page. Each post is a carousel:
slide 1 game breakdown, slides 2-3 each team's breakdown. Tone: sharp, confident, nerdy but readable.

FACT SHEET (the only source of truth):
{facts}

RULES
- Use ONLY numbers that appear in the fact sheet, written exactly as they appear. Do not round,
  convert, total, or add any other number.
- No claims the fact sheet can't support (no records, streaks, standings, or season context).
- "xG" is the page's own shot-quality model; call it xG, never "official".

Return JSON:
- hook: a punchy first line for the caption, max {HOOK_MAX} characters, no emojis.
- caption: 2-3 sentences on what the numbers say about how this game was won, then one question
  to drive comments. Mention at least one of the three stars.
- hashtags: 5 relevant hashtags (both teams + hockey analytics), each starting with #.
"""


def fallback_game_copy(game):
    a, h = game["teams"]["away"], game["teams"]["home"]
    winner, loser = (a, h) if a["won"] else (h, a)
    extra = {"OT": " in OT", "SO": " in a shootout"}.get(game["outcome"], "")
    star = game["stars"][0] if game["stars"] else None
    caption = (f"{winner['common_name']} {winner['score']}, {loser['common_name']} {loser['score']}"
               f"{extra}. Expected goals: {a['abbrev']} {a['xg']:.2f}, {h['abbrev']} {h['xg']:.2f}.")
    if star:
        caption += f" First star: {star['name']} ({star['team_abbrev']})."
    caption += " Swipe for both teams' breakdowns. Who was the difference-maker?"
    hook = f"{winner['abbrev']} {winner['score']}, {loser['abbrev']} {loser['score']}{extra}"
    return {"hook": hook[:HOOK_MAX], "caption": caption, "hashtags": []}


def _generate(facts, prompt, fallback, attempts=3):
    allowed = _numbers(facts)
    if not GEMINI_API_KEY:
        log.info("No GEMINI_API_KEY set, using template copy")
        return fallback
    for attempt in range(1, attempts + 1):
        try:
            copy = _call_gemini(prompt)
        except Exception as exc:
            log.warning("Gemini call failed (attempt %s): %s", attempt, str(exc)[:200])
            if attempt < attempts:
                time.sleep(10 * attempt)
            continue
        problem = _valid(copy, allowed)
        if not problem:
            return {**copy, "ai": True}
        log.warning("Rejected AI copy (attempt %s): %s", attempt, problem)
        prompt += f"\n\nYour previous answer was rejected: {problem}. Fix it."
    log.warning("Falling back to template copy")
    return fallback


def generate_game_copy(game):
    facts = game_fact_sheet(game)
    return _generate(facts, _game_prompt(facts), fallback_game_copy(game))


def _tag(text):
    return "#" + re.sub(r"[^A-Za-z0-9]", "", _ascii(text))


def _assemble(body, base_tags, extra_tags, footnote):
    tags = list(base_tags)
    for t in extra_tags:
        t = "#" + re.sub(r"[^A-Za-z0-9_]", "", _ascii(t.lstrip("#")))
        if len(t) > 1 and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    return f"{body.strip()}\n\n{footnote}\n\n{' '.join(tags[:10])}"[:CAPTION_MAX]


DISCLOSURE = "Unofficial fan analytics, not affiliated with or endorsed by the NHL or its teams."
FOOTNOTE = ("xG = our shot-quality model, trained on 237k NHL shots. Game Score = Dom "
            "Luszczyszyn's single-game value formula. Data: NHL play-by-play.\n" + DISCLOSURE)
AI_NOTE = " Caption written with AI assistance."


def build_game_caption(copy, game):
    from cards import SEASON_GAMES, game_number
    a, h = game["teams"]["away"], game["teams"]["home"]
    n = game_number(game["game_id"])
    label = f"🏒 NHL Game #{n} of {SEASON_GAMES:,}\n" if n else ""
    body = f"{label}{copy['hook'].strip()}\n\n{copy['caption'].strip()}"
    return _assemble(body, ["#NHL", "#HockeyAnalytics", _tag(a["name"]), _tag(h["name"])],
                     copy.get("hashtags", []), FOOTNOTE + (AI_NOTE if copy.get("ai") else ""))


# ------------------------------------------------------------ weekly posts ---
def build_weekly_caption(week):
    from cards import _range_label
    lines = [f"The week in analytics: {_range_label(week['start'], week['end'])} "
             f"({week['games']} games)."]
    if week["players_top"]:
        lines.append("\nTop skaters by Game Score:")
        lines += [f"{i}. {p['name']} ({p['team_abbrev']}) {p['game_score']:.2f}"
                  for i, p in enumerate(week["players_top"][:3], 1)]
    if week["teams_top"]:
        lines.append("\nBest 5v5 teams by share of expected goals:")
        lines += [f"{i}. {t['name']} {t['xg5_pct']:.1f}%" for i, t in enumerate(week["teams_top"][:3], 1)]
    if week["players_bottom"] or week["teams_bottom"]:
        lines.append("\nSwipe for the full top and bottom 10s. Who's due for a bounce-back?")
    return _assemble("\n".join(lines), ["#NHL", "#HockeyAnalytics", "#NHLStats", "#FancyStats"], [],
                     FOOTNOTE)
