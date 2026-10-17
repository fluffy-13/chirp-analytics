# Chirp Analytics

Automated NHL analytics for Instagram (@chirpanalytics).

- **Every game, 5–10 minutes after the final horn:** a cover slide (team-colour blend, logos,
  score, xG, the AI headline) and then the game breakdown
  (score, expected-goals flow chart, shot/chance/power-play/faceoff comparison, three stars),
  then for each team a breakdown (xG, 5v5 shares, top performers, goalie with goals saved above
  expected) and a **player impact** slide: every skater's Game Score split into what drove it
  (goals + assists, shots, 5v5 shot attempts, 5v5 goals on ice, blocks/faceoffs/penalties), his
  on-ice 5v5 xG±, flags when results and process disagree (DESERVED MORE: no points but xG± ≥ +0.4,
  or 0.5+ individual xG with xG± ≥ 0; OUTCHANCED: points but xG± ≤ −0.4), a tick at his season
  average and a ▲/▼ for a hot/cold run (last 5 games averaging 0.4+ above/below his season, with
  3 of the 5 on that side; needs 5 prior games).
- **Animated** (silent MP4, text on screen; `animations.py`, `reels.py`):
  - *Replay slide* in every game carousel (slide 2): every shot appears on the rink in game order,
    sized by xG, synced with the expected-goals race and the score.
  - *Game of the Night* Reel once every game on the slate is final (biggest upset, OT/shootout,
    most chances), plus a *Player of the Night* Reel for the best hat trick / 4+ point game.
  - *Ovi goal* Reel (career-goal odometer, goalies beaten, next milestone) and *Crosby climb* Reel
    (rising up the all-time points ladder) right after those teams' game posts.
  - Video failures never block a post: the carousel falls back to still slides. Encoding uses
    ffmpeg, or the bundled `imageio-ffmpeg` binary when the runner has none.
- **Stories** (`stories.py`, 1080x1920, no captions/stickers via the API): *tonight's slate* about
  3 hours before the first puck drop (records, 5v5 xG share, xG favourite), a *final-score story*
  minutes after each game, and *last night's scores* with expected goals once the slate is done.
- **Trackers** (an extra slide in their teams' games): *Ovi's Farewell Tour* in Capitals games
  (career goals, milestones, goals vs. tonight's opponent, goalies he's scored on, final visits,
  games left, PP/GW/OT goals with all-time ranks) and *Crosby: Chasing History* in Penguins games
  (the all-time points ladder around him, pace, assists rank). Career logs live on the `state`
  branch (`trackers/{player_id}.json`), seeded once with `tools/backfill_trackers.py` and topped up
  from the NHL game log on every post.
- Posts carry the NHL game number (slides + first caption line), team logos (fetched from the NHL's
  logo CDN at render time, never stored in this repo) and a short disclosure: unofficial, not
  affiliated with the NHL; AI-written captions are labelled.
- **Feature posts** (`features.yml`):
  - *Fantasy pickups*, Sundays 6:50 PM ET: under-the-radar adds for categories leagues
    (G, A, PPP, SOG, HIT, BLK) — last 14 days of per-game category value plus a bonus for a growing
    role (ice time / PP time up), excluding this season's top 150 and anyone with 45+ points last
    season.
  - *Rookie watch*, every other Wednesday 11:40 AM ET: Calder-eligible skaters by Game Score, the
    last two weeks, and rookie goalies by GSAx.
  - *Top lines*, Thursdays 11:40 AM ET: the season's best 5v5 forward lines and D pairs by share
    of expected goals (min. 40 minutes together early on, ~5 min a game later) and the lines of the
    week (biggest 5v5 xG margin over 7 days). Line combos come from the shift data, second by second.
  - *Awards race*, the 1st of each month 10:40 AM ET: the 'deserved' race by our numbers — Hart
    (Game Score), Norris (D Game Score), Vezina (GSAx), Calder (rookie Game Score), Selke (5v5
    expected goals prevented vs. his team), Lady Byng (Game Score with ≤2 PIM, or 1 per 5 games),
    with movement since last month.
- **Every Monday:** the weekly report — top and bottom 10 skaters (total Game Score) and top and
  bottom 10 teams (share of 5v5 expected goals).

Every number comes from the NHL's public play-by-play. Captions are written by Gemini from a fact
sheet and rejected if they contain any number or claim that isn't in it (template fallback).

## How it runs
| Workflow | When | What |
|---|---|---|
| `live.yml` | 11:50, 18:40, 23:50 ET daily | polls every 2 min while games are on; posts each final |
| `weekly.yml` | Mondays 09:40 ET | last Monday–Sunday week |
| `run.yml` | manual | `games` for a date, `weekly`, `live`, `buffer-check`, or `make-sample`, with a mode override |
| `ledger.yml` | manual | backfills the season ledger (each player's Game Score per game) for a date range |
| `dump.yml` | manual (dev) | saves a night's raw NHL JSON to the `fixtures` branch |

**Where posts go** is the repo variable `POST_MODE`:
- `preview` (default) — nothing is posted; slides + captions land on the **`previews` branch**
  (open its README on GitHub to see every carousel).
- `buffer` — Buffer's API (`BUFFER_API_KEY`). No Meta developer app or Facebook Page needed:
  connect @chirpanalytics inside Buffer with Instagram login. Run the manual workflow with
  `buffer-check` first (lists channels and schema, posts nothing; log lands in `previews/logs/`).
- `make` — Make.com scenario via `MAKE_WEBHOOK_URL` (payload: `type`, `image_urls`, `caption`, `key`).
- `graph` — Instagram Graph API directly (`IG_ACCESS_TOKEN`, `IG_USER_ID`).

What has been posted lives on the **`state` branch** (`posted.json`, plus `ledger.json`), so a game or week is never
posted twice, even if runs overlap. A game that fails 4 times is skipped and the run is marked failed
(GitHub emails you).

## Files
| File | Job |
|---|---|
| `pipeline.py` | live poller, per-night backfill, weekly job, posted-state |
| `metrics.py` | per-game analysis: team totals, 5v5 shares, xG timeline, goalies (GSAx), three stars; weekly aggregation |
| `cards.py` | game / team / weekly slides (1080×1350 JPEG) |
| `content_generator.py` | Gemini captions with number/claim checking, template fallback |
| `publisher.py` | preview / Buffer / Make / Graph publishing, single image or carousel, Supabase image hosting |
| `buffer_client.py` | Buffer GraphQL client: find the Instagram channel, publish now, confirm it went live |
| `ledger.py` | season store on the `state` branch: one file per game (`games/{season}/{id}.json`) with every player's line, incl. 5v5/PP/SH ice time |
| `season.py` | season aggregates from the store: skaters, goalies, rookie list, fantasy category values |
| `features.py` | awards race, rookie watch and fantasy pickups slides + captions |
| `trackers.py` | Ovechkin and Crosby tracker slides + their career logs |
| `logos.py` | team logos from the NHL logo CDN (cached per run, never committed) |
| `intro_cards.py` | one-off season-so-far intro posts (`python main.py intro --post standings`) |
| `git_store.py` | small files on a git branch without touching the checkout |
| `xg_model.py` + `xg_model.json` | trained xG model (pure Python at runtime) |
| `nhl_fetcher.py` | NHL API client with retries; `FixtureSource` for offline runs |
| `main.py` | command line |

## Run locally
```bash
pip install -r requirements.txt
python main.py games --date 2026-10-15        # preview mode: renders to output_posts/
python main.py weekly --end 2026-10-18
pytest -q tests
```

## xG model
Gradient-boosted trees (300 trees, depth 3) trained on **237,241 unblocked shots / 15,892 goals**
from the 2024-25 and 2025-26 seasons, exported to `xg_model.json` and scored in pure Python.

Features: distance, angle, shot type, strength (EV/PP/SH), rebound and how far the puck moved
across on it, rush, time since the previous event, what that event was (faceoff, hit, giveaway,
takeaway, shot...), and how far and fast the puck travelled from it. Empty-net shots are excluded.

**Honest test** (trained on 2024-25 only, scored on all of 2025-26), see `tools/holdout_report.json`:

| model | log loss | AUC | xG per actual goal |
|---|---|---|---|
| this model | 0.2165 | 0.770 | 1.04 |
| old hand-set starter | 0.2572 | 0.700 | 1.52 |
| dataset's published xG (benchmark) | 0.2155 | 0.773 | 1.12 |

`tools/check_parity.py` confirms the bot computes every feature exactly as training did
(50 games, 4,149 shots, 0 mismatches).

**Retrain each offseason:**
```bash
pip install -r tools/requirements-train.txt
git clone --filter=blob:none --no-checkout --depth 1 https://github.com/sportsdataverse/fastrhockey-nhl-data
cd fastrhockey-nhl-data && git checkout HEAD -- nhl/pbp/parquet/play_by_play_2026.parquet nhl/pbp/parquet/play_by_play_2027.parquet && cd ..
python tools/fit_xg.py --train <2026 file> --test <2027 file>          # check it holds up
python tools/fit_xg.py --train <2026 file> <2027 file> --write         # ship it
python tools/check_parity.py <2027 file>
```
Training data: play-by-play compiled from the NHL API by the sportsdataverse project.
Game Score: Dom Luszczyszyn's single-game value formula (goalies: 0.1×saves − 0.75×goals against).
