import sys
from pathlib import Path

api_src = Path(__file__).resolve().parent / "apps" / "api" / "src"
if str(api_src) not in sys.path:
    sys.path.insert(0, str(api_src))

from forgegraph.main import app  # noqa: E402

__all__ = ["app"]
