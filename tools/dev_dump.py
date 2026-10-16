"""Dev: dump small API lookups the new posts need, to the fixtures branch (dev/...)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_store import GitBranchStore  # noqa: E402
from nhl_fetcher import LiveSource  # noqa: E402
from season import rookie_ids  # noqa: E402

src = LiveSource()
out = {}
try:
    out["rookies"] = sorted(rookie_ids(src, "20262027"))
except Exception as exc:
    out["rookies_error"] = str(exc)
print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}))
GitBranchStore("fixtures").write({"dev/lookups.json": json.dumps(out).encode()}, "Dev lookups")
