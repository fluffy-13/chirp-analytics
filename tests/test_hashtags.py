from hashtags import TAG_RE, enforce, game_tags, TEAM_TAGS


def test_game_tags_are_five_and_use_team_tags():
    tags = game_tags("STL", "MIN", 2026020116)
    assert len(tags) == 5 and tags[:4] == ["#NHL", "#HockeyAnalytics", "#STLBlues", "#MNWild"]
    assert game_tags("WSH", "BOS", 1)[-1] == "#Ovechkin"
    assert game_tags("PIT", "COL", 1)[-1] == "#Crosby"
    assert len(TEAM_TAGS) == 32


def test_enforce_keeps_first_five_and_ignores_numbers():
    cap = "NHL Game #116, #5 in xG\n\n#A #B #C #a #D #E #F #G"
    out = enforce(cap)
    assert TAG_RE.findall(out) == ["#A", "#B", "#C", "#D", "#E"]
    assert "#116" in out and "#5 in xG" in out


def test_game_caption_has_exactly_five_tags():
    import content_generator as cg
    game = {"game_id": 2026020116, "teams": {"away": {"abbrev": "STL", "name": "St. Louis Blues"},
                                             "home": {"abbrev": "MIN", "name": "Minnesota Wild"}}}
    copy = {"hook": "Boldy #hattrick night", "caption": "Wild win. #GoWild #MNWild", "hashtags": ["#x"]}
    cap = cg.build_game_caption(copy, game)
    assert len(TAG_RE.findall(cap)) == 5 and "#hattrick" not in cap and "NHL Game #116" in cap
