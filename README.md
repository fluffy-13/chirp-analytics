# Chirp Analytics

Automated NHL analytics for Instagram (@chirpanalytics).

- **Every game, 5–10 minutes after the final horn:** a 3-slide carousel — the game breakdown
  (score, expected-goals flow chart, shot/chance/power-play/faceoff comparison, three stars)
  and a breakdown for each team (xG, 5v5 shares, top performers, goalie with goals saved above
  expected).
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
| `dump.yml` | manual (dev) | saves a night's raw NHL JSON to the `fixtures` branch |

**Where posts go** is the repo variable `POST_MODE`:
- `preview` (default) — nothing is posted; slides + captions land on the **`previews` branch**
  (open its README on GitHub to see every carousel).
- `buffer` — Buffer's API (`BUFFER_API_KEY`). No Meta developer app or Facebook Page needed:
  connect @chirpanalytics inside Buffer with Instagram login. Run the manual workflow with
  `buffer-check` first (lists channels and schema, posts nothing; log lands in `previews/logs/`).
- `make` — Make.com scenario via `MAKE_WEBHOOK_URL` (payload: `type`, `image_urls`, `caption`, `key`).
- `graph` — Instagram Graph API directly (`IG_ACCESS_TOKEN`, `IG_USER_ID`).

What has been posted lives on the **`state` branch** (`posted.json`), so a game or week is never
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
