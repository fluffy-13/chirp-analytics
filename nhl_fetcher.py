"""NHL data access. LiveSource hits the public NHL APIs; FixtureSource replays saved JSON."""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from config import NHL_STATS_API, NHL_WEB_API, TIMEZONE

log = logging.getLogger(__name__)

FINAL_STATES = {"OFF", "FINAL"}  # OFF = official final, FINAL = final but not yet official
GAME_TYPES = {2, 3}              # regular season, playoffs (skip preseason/all-star)


def default_target_date():
    """Yesterday in Eastern time — run the bot the morning after games."""
    return (datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)).date().isoformat()


class LiveSource:
    def __init__(self, timeout=15, retries=3):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "nhl-analytics-ig/2.0"

    def _get(self, url, params=None):
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.retries:
                    raise RuntimeError(f"NHL API request failed: {url} ({exc})") from exc
                wait = 2 ** attempt
                log.warning("Retrying %s in %ss (%s)", url, wait, exc)
                time.sleep(wait)

    def score(self, date):
        return self._get(f"{NHL_WEB_API}/score/{date}")

    def boxscore(self, game_id):
        return self._get(f"{NHL_WEB_API}/gamecenter/{game_id}/boxscore")

    def play_by_play(self, game_id):
        return self._get(f"{NHL_WEB_API}/gamecenter/{game_id}/play-by-play")

    def shifts(self, game_id):
        """Shift charts power on-ice (5v5) metrics. Optional: returns [] on failure."""
        try:
            data = self._get(f"{NHL_STATS_API}/shiftcharts",
                             params={"cayenneExp": f"gameId={game_id}"})
            return data.get("data", []) or []
        except RuntimeError as exc:
            log.warning("No shift data for %s, on-ice metrics disabled (%s)", game_id, exc)
            return []


class FixtureSource:
    """Reads score.json, <id>_boxscore.json, <id>_play-by-play.json, <id>_shifts.json."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def _load(self, name):
        return json.loads((self.dir / name).read_text())

    def score(self, date):
        return self._load("score.json")

    def boxscore(self, game_id):
        return self._load(f"{game_id}_boxscore.json")

    def play_by_play(self, game_id):
        return self._load(f"{game_id}_play-by-play.json")

    def shifts(self, game_id):
        path = self.dir / f"{game_id}_shifts.json"
        return json.loads(path.read_text()).get("data", []) if path.exists() else []


def completed_games(source, date):
    games = source.score(date).get("games", [])
    return [g for g in games
            if g.get("gameState") in FINAL_STATES and g.get("gameType") in GAME_TYPES]


def load_game(source, score_game):
    gid = score_game["id"]
    return {
        "score": score_game,
        "boxscore": source.boxscore(gid),
        "pbp": source.play_by_play(gid),
        "shifts": source.shifts(gid),
    }
