"""Hashtag sets. Instagram allows at most 5 hashtags per post (since Dec 2025) and either blocks
the post or drops the extras, so every set here is 5 and publish() enforces the cap.

Game posts: #NHL + #HockeyAnalytics + each team's official hashtag + one rotating topic tag
(or the tracked star's name in Capitals / Penguins games).
"""
import re

MAX_TAGS = 5

# Official team hashtags (The Hockey Writers' 2025-26 list); update each season.
TEAM_TAGS = {
    "ANA": "#FlyTogether", "BOS": "#NHLBruins", "BUF": "#Sabrehood", "CGY": "#Flames",
    "CAR": "#CarolinaCulture", "CHI": "#Blackhawks", "COL": "#GoAvsGo", "CBJ": "#CBJ",
    "DAL": "#TexasHockey", "DET": "#LGRW", "EDM": "#LetsGoOilers", "FLA": "#TimeToHunt",
    "LAK": "#GoKingsGo", "MIN": "#MNWild", "MTL": "#GoHabsGo", "NSH": "#Smashville",
    "NJD": "#NJDevils", "NYI": "#Isles", "NYR": "#NYR", "OTT": "#GoSensGo", "PHI": "#LetsGoFlyers",
    "PIT": "#LetsGoPens", "SJS": "#TheFutureIsTeal", "SEA": "#SeaKraken", "STL": "#STLBlues",
    "TBL": "#GoBolts", "TOR": "#LeafsForever", "UTA": "#TusksUp", "VAN": "#Canucks",
    "VGK": "#VegasBorn", "WSH": "#ALLCAPS", "WPG": "#GoJetsGo",
}
ROTATING = ["#NHLStats", "#ExpectedGoals", "#AdvancedStats", "#HockeyStats"]
STARS = {"WSH": "#Ovechkin", "PIT": "#Crosby"}

WEEKLY = ["#NHL", "#HockeyAnalytics", "#NHLStats", "#AdvancedStats", "#FantasyHockey"]
FEATURES = {
    "awards": ["#NHL", "#NHLAwards", "#HartTrophy", "#Vezina", "#HockeyAnalytics"],
    "rookies": ["#NHL", "#NHLRookies", "#CalderTrophy", "#NHLProspects", "#HockeyAnalytics"],
    "fantasy": ["#FantasyHockey", "#WaiverWire", "#FantasyHockeyAdvice", "#NHL", "#HockeyAnalytics"],
    "lines": ["#NHL", "#HockeyAnalytics", "#NHLLines", "#FantasyHockey", "#AdvancedStats"],
}

# a hashtag needs a letter: "#5 in xG" and "NHL Game #116" are not tags
TAG_RE = re.compile(r"(?<![\w&])#(?=\w*[A-Za-z])\w+")


def game_tags(away, home, game_id=0):
    tags = ["#NHL", "#HockeyAnalytics"]
    for ab in (away, home):
        tags.append(TEAM_TAGS.get(ab, f"#{ab}"))
    star = next((STARS[ab] for ab in (away, home) if ab in STARS), None)
    tags.append(star or ROTATING[int(game_id) % len(ROTATING)])
    return tags[:MAX_TAGS]


def line(tags):
    return " ".join(tags[:MAX_TAGS])


def enforce(caption, limit=MAX_TAGS):
    """Keep only the first `limit` hashtags in a caption (safety net before publishing)."""
    seen = []

    def keep(m):
        tag = m.group(0)
        if tag.lower() in seen:
            return ""
        if len(seen) >= limit:
            return ""
        seen.append(tag.lower())
        return tag

    out = TAG_RE.sub(keep, caption)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r"[ \t]+\n", "\n", out).rstrip()
