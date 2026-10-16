"""Team logos for the cards, fetched from the NHL's public logo CDN at render time.

Logos are trademarks of the NHL and its teams; they're used only to identify teams and are
never committed to this repo. Anything that goes wrong (offline, renderer missing) returns
None and the card simply renders without the logo.
"""
import io
import logging
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image

from config import OUTPUT_DIR

log = logging.getLogger("logos")
URL = "https://assets.nhle.com/logos/nhl/svg/{abbrev}_dark.svg"
CACHE = OUTPUT_DIR.parent / "logo_cache"
LOCAL_DIR = os.environ.get("LOGO_DIR")  # dev: a folder of {ABBR}.svg files
RENDER_PX = 600


def _svg(abbrev):
    if LOCAL_DIR:
        p = Path(LOCAL_DIR) / f"{abbrev}.svg"
        return p.read_bytes() if p.exists() else None
    cached = CACHE / f"{abbrev}.svg"
    if cached.exists():
        return cached.read_bytes()
    import requests
    r = requests.get(URL.format(abbrev=abbrev), timeout=15,
                     headers={"User-Agent": "nhl-analytics-ig/2.0"})
    r.raise_for_status()
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(r.content)
    return r.content


@lru_cache(maxsize=None)
def _master(abbrev):
    try:
        import cairosvg
        svg = _svg(abbrev)
        if not svg:
            return None
        png = cairosvg.svg2png(bytestring=svg, output_width=RENDER_PX)
        img = Image.open(io.BytesIO(png)).convert("RGBA")
        bbox = img.getbbox()
        return img.crop(bbox) if bbox else None
    except Exception as exc:
        log.warning("No logo for %s: %s", abbrev, exc)
        return None


def logo(abbrev, height=None, width=None, max_w=None, opacity=1.0):
    """RGBA logo scaled to a height (or width), or None."""
    m = _master(abbrev)
    if m is None:
        return None
    if width:
        size = (int(width), max(1, int(m.height * width / m.width)))
    else:
        h = int(height or 100)
        size = (max(1, int(m.width * h / m.height)), h)
        if max_w and size[0] > max_w:
            size = (int(max_w), max(1, int(m.height * max_w / m.width)))
    img = m.resize(size, Image.LANCZOS)
    if opacity < 1:
        a = img.getchannel("A").point(lambda v: int(v * opacity))
        img.putalpha(a)
    return img


def paste(base, abbrev, xy, height=None, anchor="lt", **kw):
    """Paste a logo onto an RGB image. anchor: l/m/r + t/m/b. Returns its width (0 if none)."""
    img = logo(abbrev, height=height, **kw)
    if img is None:
        return 0
    x, y = xy
    if anchor[0] == "m":
        x -= img.width / 2
    elif anchor[0] == "r":
        x -= img.width
    if anchor[1] == "m":
        y -= img.height / 2
    elif anchor[1] == "b":
        y -= img.height
    base.paste(img, (int(x), int(y)), img)
    return img.width
