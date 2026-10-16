import intro_cards as ic


def test_intro_posts_render():
    data = ic.load_season()
    for which, n in (("standings", 5), ("finishing", 4), ("goalies", 4)):
        paths, caption, alts = ic.render_intro(which, data)
        assert len(paths) == n == len(alts)
        assert all(p.exists() for p in paths)
        assert "None" not in caption and len(caption) < 2200
        assert caption.count("#") <= 30


def test_standings_order_and_minimums():
    data = ic.load_season()
    s = ic.standings(data)
    assert [t["xg5_pct"] for t in s] == sorted((t["xg5_pct"] for t in s), reverse=True)
    hot, cold = ic.finishers(data)
    assert all(p["gp"] >= ic.SKATER_MIN_GP for p in hot + cold)
    best, worst = ic.goalie_lists(data)
    assert all(g["gp"] >= ic.GOALIE_MIN_GP for g in best + worst)
