import os
from pathlib import Path

APP_NAME = "Feedstitch"
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_FILENAME = "app.db"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def resolve_fixture_path(fixture_path: str) -> Path:
    """Resolve a source fixture path.

    Sources created by the directory harvest may store an absolute path when the
    file lives outside the repository fixtures directory; seed sources store a
    path relative to FIXTURES_DIR.
    """
    path = Path(fixture_path)
    return path if path.is_absolute() else FIXTURES_DIR / path
