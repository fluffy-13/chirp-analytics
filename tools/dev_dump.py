"""Dev: run the test suite on the CI machine and save its output + environment info."""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_store import GitBranchStore  # noqa: E402

out = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests", "-x", "-p", "no:cacheprovider"],
                     capture_output=True, text=True)
ff = shutil.which("ffmpeg")
info = subprocess.run([ff or "true", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
env = f"python {sys.version}\nffmpeg {ff}\nlibx264: {'libx264' in info}\n"
GitBranchStore("fixtures").write({"dev/pytest.txt": (env + out.stdout[-20000:] + out.stderr[-5000:]).encode()},
                                 "Dev pytest output")
print(env, out.stdout[-3000:])
