"""1080x1350 (4:5) spotlight card. Saved as JPEG — the IG publishing API only accepts JPEG."""
import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import FONT_DIR, IG_HANDLE, OUTPUT_DIR, PALETTE as C

log = logging.getLogger(__name__)

W, H = 1080, 1350
M = 80  # side margin

_FONT_CANDIDATES = {
    "regular": ["Inter-Regular.ttf", "Inter-Regular.otf",
                "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
                "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "semibold": ["Inter-SemiBold.ttf", "Inter-SemiBold.otf",
                 "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
                 "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "bold": ["Inter-Bold.ttf", "Inter-Bold.otf",
             "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
             "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def _font(weight, size):
    for cand in _FONT_CANDIDATES[weight]:
        path = Path(cand) if Path(cand).is_absolute() else FONT_DIR / cand
        if path.exists():
            return ImageFont.truetype(str(path), size)
    log.warning("No %s font found, using Pillow default (add Inter to %s)", weight, FONT_DIR)
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit(draw, text, weight, size, max_w, min_size):
    """Shrink a single-line string until it fits."""
    while size > min_size:
        font = _font(weight, size)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size -= 4
    return _font(weight, min_size)


def render_card(post, hook):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    card = Image.new("RGB", (W, H), C["bg"])
    d = ImageDraw.Draw(card)
    content_w = W - 2 * M

    d.rectangle([0, 0, W, 16], fill=C["accent"])

    tag = _font("semibold", 28)
    d.text((M, 70), "ANALYTICS SPOTLIGHT // NHL", fill=C["accent"], font=tag)
    d.text((W - M, 70), post["date"], fill=C["muted"], font=tag, anchor="ra")

    # Hook
    y = 140
    hook_font = _font("bold", 50)
    for line in _wrap(d, hook, hook_font, content_w)[:2]:
        d.text((M, y), line, fill=C["text"], font=hook_font)
        y += 62

    # Player
    y += 36
    name_font = _fit(d, post["player_name"].upper(), "bold", 76, content_w, 48)
    d.text((M, y), post["player_name"].upper(), fill=C["text"], font=name_font)
    y += 92
    d.text((M, y), f"{post['team'].upper()}  ·  {post['position']}", fill=C["muted"], font=tag)

    # Stat panel
    y += 70
    panel_h = 270
    d.rounded_rectangle([M, y, W - M, y + panel_h], radius=18,
                        fill=C["panel"], outline=C["panel_border"], width=2)
    stat_font = _font("bold", 140)
    d.text((M + 44, y + 28), post["headline_value"], fill=C["stat"], font=stat_font)
    d.text((M + 48, y + 186), post["headline_label"], fill=C["text"], font=_font("semibold", 34))
    d.text((W - M - 44, y + 192), post["matchup"], fill=C["muted"], font=tag, anchor="ra")
    y += panel_h + 70

    # Breakdown
    d.text((M, y), "ADVANCED METRICS BREAKDOWN", fill=C["text"], font=tag)
    y += 64
    body = _font("regular", 36)
    for bullet in post["sub_bullets"]:
        d.ellipse([M, y + 14, M + 16, y + 30], fill=C["accent"])
        for line in _wrap(d, bullet, body, content_w - 50):
            d.text((M + 50, y), line, fill=C["body"], font=body)
            y += 48
        y += 26

    # Footer
    small = _font("regular", 24)
    d.text((M, H - 92), f"{IG_HANDLE}  |  Data: NHL play-by-play", fill=C["faint"], font=small)
    d.text((M, H - 58), "xG: our model, trained on 237k NHL shots (2024-26)", fill=C["faint"], font=small)

    slug = re.sub(r"[^a-z0-9]+", "-", post["player_name"].lower()).strip("-")
    path = OUTPUT_DIR / f"{post['date']}_{post['game_id']}_{slug}.jpg"
    card.save(path, "JPEG", quality=92)
    log.info("Card saved: %s", path)
    return path
