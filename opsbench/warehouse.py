"""Build the DuckDB warehouse from a Synthea CSV export and run the review queries."""
from datetime import date, timedelta
from pathlib import Path

import duckdb

SQL = Path(__file__).parent / "sql"

# Each check counts offending rows; any non-zero count stops the build.
CHECKS = {
    "duplicate patient ids": "SELECT count(*) - count(DISTINCT patient_id) FROM patients",
    "duplicate encounter ids": "SELECT count(*) - count(DISTINCT encounter_id) FROM encounters",
    "encounters without a patient": "SELECT count(*) FROM encounters ANTI JOIN patients USING (patient_id)",
    "conditions without a patient": "SELECT count(*) FROM conditions ANTI JOIN patients USING (patient_id)",
    "encounters ending before they start": "SELECT count(*) FROM encounters WHERE stop_ts < start_ts",
    "encounters before birth": """SELECT count(*) FROM encounters JOIN patients USING (patient_id)
                                  WHERE start_ts::DATE < birth_date""",
}


def build(csv_dir, db=":memory:"):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone = 'UTC'")
    con.execute((SQL / "staging.sql").read_text().replace("{csv}", str(Path(csv_dir).resolve())))
    failed = {name: n for name, sql in CHECKS.items() if (n := con.execute(sql).fetchone()[0])}
    if failed:
        raise ValueError(f"data checks failed: {failed}")
    con.execute((SQL / "opportunities.sql").read_text())
    con.execute((SQL / "features.sql").read_text())
    return con


def set_snapshot(con, snapshot):
    con.execute("UPDATE params SET snapshot = ?", [date.fromisoformat(str(snapshot))])


def worklist(con, snapshot):
    """Open opportunities, one row per patient (wellness) or per emergency visit (ED follow-up)."""
    set_snapshot(con, snapshot)
    return con.execute("""
        SELECT 'overdue_wellness' AS opportunity, w.patient_id, c.first_name, c.last_name, c.age,
               w.last_wellness AS evidence_ts,
               date_diff('day', w.last_wellness, a.snapshot) AS days_since
        FROM wellness_review w JOIN cohort c USING (patient_id) CROSS JOIN as_of a WHERE w.exclusion IS NULL
        UNION ALL
        SELECT 'ed_no_followup', r.patient_id, c.first_name, c.last_name, c.age, r.ed_ts,
               date_diff('day', r.ed_ts, a.snapshot)
        FROM ed_followup_review r JOIN cohort c USING (patient_id) CROSS JOIN as_of a WHERE r.exclusion IS NULL
        ORDER BY opportunity, days_since DESC NULLS FIRST, patient_id
    """).df()


def funnel(con, snapshot):
    """Candidate counts by outcome: every exclusion reason, plus the open opportunities."""
    set_snapshot(con, snapshot)
    return con.execute("""
        SELECT 'overdue_wellness' AS opportunity, coalesce(exclusion, 'OPEN') AS outcome, count(*) AS n
        FROM wellness_review GROUP BY ALL
        UNION ALL
        SELECT 'ed_no_followup', coalesce(exclusion, 'OPEN'), count(*) FROM ed_followup_review GROUP BY ALL
        ORDER BY opportunity, n DESC
    """).df()


def timeline(con, patient_id, snapshot, months=24):
    """A patient's encounters in the months before the snapshot, newest first. Read-only: no params table."""
    cutoff = date.fromisoformat(str(snapshot)) + timedelta(days=1)
    return con.execute(f"""
        SELECT start_ts, encounter_class, description
        FROM encounters
        WHERE patient_id = ? AND start_ts < ?::TIMESTAMP AND start_ts >= ?::TIMESTAMP - INTERVAL {int(months)} MONTH
        ORDER BY start_ts DESC
    """, [patient_id, cutoff, cutoff]).df()


def model_rows(con, snapshot):
    """One row per eligible patient: as-of features and the next-365-day acute-use label."""
    set_snapshot(con, snapshot)
    return con.execute("SELECT * FROM model_rows ORDER BY patient_id").df()
