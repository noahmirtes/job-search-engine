"""Generate the export workbook from scored jobs in the local database."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.reporting import generate_report
from _default_paths import _default_paths

def main() -> None:
    """Entrypoint for building one report workbook and storing export metadata."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)

    with get_connection(config.paths.db_path) as connection:
        summary = generate_report(connection, config)

    print(f"Export id: {summary.export_id}")
    print(f"Report path: {summary.export_path}")
    print(f"Rows in 'new' tab: {summary.new_count}")
    print(f"Rows in 'all' tab: {summary.all_count}")
    if config.scoring_config.report.include_all_jobs_list:
        print(f"Rows in 'all_jobs_list' tab: {summary.all_jobs_list_count}")


if __name__ == "__main__":
    main()
