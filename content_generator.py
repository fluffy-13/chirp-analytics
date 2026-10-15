"""Caption + hook copy. Gemini writes the voice; it is never allowed to invent numbers."""
import json
import logging
import re

from config import GEMINI_API_KEY, GEMINI_MODEL, IG_HANDLE

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


def fact_sheet(post):
    p = post["player"]
    lines = [
        f"Game: {post['matchup']} on {post['date']}",
        f"Player: {post['player_name']} ({post['position']}, {post['team']})",
        f"Headline stat: {post['headline_value']} {post['headline_label']}",
        *[f"- {b}" for b in post["sub_bullets"]],
        f"Goals {p['G']}, assists {p['A']}, shots on goal {p['SOG']}, shot attempts {p['iCF']}",
        f"Individual xG {p['ixG']:.2f}, Game Score {p['game_score']:.2f}, TOI {p['toi']}",
        "Team xG: " + ", ".join(f"{k} {v:.2f}" for k, v in post["team_xg"].items()),
    ]
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
- "xG" here is the page's own shot-quality model; call it xG, never "official".

Return JSON:
- hook: one punchy line for the graphic, max {HOOK_MAX} characters.
- caption: 2–3 sentences explaining why the performance stood out analytically, then a question to drive comments.
- hashtags: 5 relevant hashtags (team + hockey analytics), each starting with #.
"""


def _call_gemini(prompt):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=0.8,
        ),
    )
    return json.loads(resp.text)


def fallback_copy(post):
    p = post["player"]
    last = post["player_name"].split()[-1] if post["player_name"] else "He"
    hook = f"{last} tilted the ice for {post['team_abbrev']}."
    caption = (f"{post['player_name']} posted {post['headline_value']} {post['headline_label'].lower()} "
               f"in {post['matchup']}. {p['iCF']} shot attempts and {p['iHD']} from the home-plate area "
               f"tell the story. Who was the best skater in this one?")
    return {"hook": hook[:HOOK_MAX], "caption": caption, "hashtags": []}


def generate_copy(post, attempts=2):
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
            log.warning("Gemini call failed (attempt %s): %s", attempt, exc)
            continue
        problem = _valid(copy, allowed)
        if not problem:
            return copy
        log.warning("Rejected AI copy (attempt %s): %s", attempt, problem)
        prompt += f"\n\nYour previous answer was rejected: {problem}. Fix it."
    log.warning("Falling back to template copy")
    return fallback_copy(post)


def build_caption(copy, post):
    team_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", post["team"])
    tags = ["#NHL", "#HockeyAnalytics", team_tag]
    for t in copy.get("hashtags", []):
        t = "#" + re.sub(r"[^A-Za-z0-9_]", "", t.lstrip("#"))
        if len(t) > 1 and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    footnote = ("xG = our shot-quality model, trained on 237k NHL shots from the last two seasons. "
                "Data: NHL play-by-play.")
    caption = f"{copy['caption'].strip()}\n\n{footnote}\n\n{' '.join(tags[:10])}"
    return caption[:CAPTION_MAX]
