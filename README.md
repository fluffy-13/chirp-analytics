# Chirp Analytics

Every morning: pull last night's finished games → compute real analytics from play-by-play and
shift charts → pick the night's best skater by Game Score → Gemini writes the hook + caption
(fact-checked against the data) → render a 1080×1350 JPEG → publish to Instagram.

## Files
| File | Job |
|---|---|
| `config.py` | env vars, paths, palette |
| `nhl_fetcher.py` | NHL API client with retries, plus `FixtureSource` for offline runs |
| `metrics.py` | home-plate chances, on-ice 5v5 Corsi, Game Score, spotlight pick |
| `xg_model.py` + `xg_model.json` | trained xG model (pure Python at runtime) |
| `tools/fit_xg.py`, `tools/check_parity.py` | retrain the model, verify live features match training |
| `content_generator.py` | Gemini JSON copy, rejects invented numbers/claims, template fallback |
| `renderer.py` | the card (wrapped text, font fallbacks, JPEG) |
| `publisher.py` | Supabase upload → IG container → poll until ready → publish |
| `main.py` | orchestration, dry-run by default, never posts the same game twice |

## Run
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in keys
python main.py              # dry run: card + caption in output_posts/
python main.py --publish    # post it
python tests/make_fixture.py && python main.py --fixtures tests/fixtures   # offline test
pytest -q tests
```

## Setup notes
- **Fonts:** put Inter (`Inter-Regular`, `-SemiBold`, `-Bold`) in `fonts/`. Falls back to Arial/DejaVu.
- **Image hosting:** create a *public* Supabase Storage bucket `ig-posts`; Instagram downloads the
  image from that URL. Or set `IMAGE_HOST_BASE_URL` if you host files yourself.
- **Instagram:** needs a Business/Creator account linked to a Facebook Page, a Meta app with
  `instagram_business_content_publish`, and a long-lived token (expires every 60 days — refresh it).
- **Scheduling:** `.github/workflows/daily-post.yml` runs daily; add the keys as repo secrets.

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

`tools/check_parity.py` converts real games into NHL-API JSON and confirms the bot computes every
feature exactly as training did (50 games, 4,149 shots, 0 mismatches).

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
