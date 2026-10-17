import sys
from pathlib import Path

# make the project modules importable however pytest is invoked (`pytest` or `python -m pytest`)
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
