import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import features  # noqa: E402
from ledger import encode_game  # noqa: E402
from test_pipeline import MIN_GAME, SO_GAME, FakeSource  # noqa: E402
from metrics import analyze_game  # noqa: E402
from nhl_fetcher import load_game  # noqa: E402


def _records():
    src = FakeSource()
    games = {g["id"]: analyze_game(load_game(src, g)) for g in src.score("2026-10-15")["games"]}
    recs = []
    for i in range(6):  # replay the two real games on different days
        for gid in (MIN_GAME, SO_GAME):
            rec = encode_game(games[gid])
            rec["id"] = gid + 1000 * (i + 1)
            rec["date"] = f"2026-10-{i + 4:02d}"
            recs.append(rec)
    return recs


def test_feature_posts_render():
    recs = _records()
    some = {pid for r in recs[:1] for pid in list(r["sk"])[:6]}
    slides, caption, alts, snap = features.awards_post(recs, "2026-10-09", some)
    assert len(slides) == len(alts) == 7 and "Hart" in caption and snap["hart"]
    slides, caption, alts = features.rookies_post(recs, "2026-10-09", some)
    assert len(slides) == len(alts) >= 2
    built = features.fantasy_post(recs, "2026-10-09")
    assert built is None or len(built[0]) == 2
