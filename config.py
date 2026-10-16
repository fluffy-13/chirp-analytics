"""Central configuration. Every secret comes from the environment (or a local .env)."""
import os
from pathlib import Path

try:  # optional: load a local .env during development
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(key, default=None):
    value = os.environ.get(key)
    return value if value not in (None, "") else default


ROOT = Path(__file__).resolve().parent

# --- AI copy ---------------------------------------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL")  # optional override; otherwise the first available below
# Tried in order; a model Google has retired (404) is skipped automatically.
GEMINI_MODEL_FALLBACKS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.6-flash",
                          "gemini-3.5-flash-lite"]

# --- Instagram Graph API -----------------------------------------------------
IG_ACCESS_TOKEN = _env("IG_ACCESS_TOKEN")
IG_USER_ID = _env("IG_USER_ID")
GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v23.0")
IG_HANDLE = _env("IG_HANDLE", "@chirpanalytics")

# --- Posting through Make.com (no Meta developer app needed) ----------------
# A Make scenario: Custom webhook -> Instagram for Business "Create a Photo Post".
# Treat the URL like a password: anyone holding it can post to the account.
MAKE_WEBHOOK_URL = _env("MAKE_WEBHOOK_URL")

# --- Image hosting (Instagram fetches the image from a public URL) -----------
# Option A: Supabase Storage public bucket (uploaded automatically)
SUPABASE_URL = _env("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = _env("SUPABASE_BUCKET", "ig-posts")
# Option B: you sync OUTPUT_DIR to a static host yourself
IMAGE_HOST_BASE_URL = _env("IMAGE_HOST_BASE_URL")

# --- NHL data ----------------------------------------------------------------
NHL_WEB_API = "https://api-web.nhle.com/v1"
NHL_STATS_API = "https://api.nhle.com/stats/rest/en"
TIMEZONE = "America/New_York"  # "yesterday" is computed in this zone

# --- Paths -------------------------------------------------------------------
OUTPUT_DIR = ROOT / "output_posts"
STATE_FILE = ROOT / "state" / "posted.json"
FONT_DIR = ROOT / "fonts"  # drop Inter-Regular/SemiBold/Bold .ttf/.otf here

# --- Card palette ------------------------------------------------------------
PALETTE = {
    "bg": "#0F1115",
    "panel": "#1F242D",
    "panel_border": "#30363D",
    "accent": "#00FF88",
    "stat": "#58A6FF",
    "text": "#FFFFFF",
    "body": "#C9D1D9",
    "muted": "#8B949E",
    "faint": "#484F58",
}
