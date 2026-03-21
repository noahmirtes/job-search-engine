from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_settings
from app.db import init_db


def main() -> None:
    settings = load_settings()
    init_db(settings.db_path)
    print(f"Initialized database at {settings.db_path}")


if __name__ == "__main__":
    main()
