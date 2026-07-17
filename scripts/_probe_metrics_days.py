import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.storage.db import db_session, init_db

init_db()
with db_session() as c:
    r = c.execute(
        "SELECT COUNT(DISTINCT report_date) FROM metrics_daily WHERE metric_type='daily'"
    ).fetchone()
    print("metrics_days", r[0])
