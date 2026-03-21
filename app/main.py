from __future__ import annotations

from app.config import load_settings
from app.db import init_db


def main() -> None:
    settings = load_settings()
    init_db(settings.db_path)
    print(f"Database initialized at {settings.db_path}")


if __name__ == "__main__":
    main()
