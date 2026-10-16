"""Golden-cohort tests: each fixture patient sits on one boundary of the review rules (snapshot 2025-12-31)."""
import shutil
from pathlib import Path

import pytest

from opsbench import warehouse

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = "2025-12-31"


@pytest.fixture(scope="module")
def con():
    return warehouse.build(FIXTURES)


def outcomes(con, view, key):
    warehouse.set_snapshot(con, SNAPSHOT)
    return dict(con.execute(f"SELECT {key}, coalesce(exclusion, 'OPEN') FROM {view}").fetchall())


def test_wellness_rules(con):
    assert outcomes(con, "wellness_review", "patient_id") == {
        "p01": "OPEN",               # last wellness one day past 15 months
        "p02": "up_to_date",         # exactly 15 months before the cutoff
        "p03": "OPEN",               # the visit after the snapshot must not count
        "p04": "died",
        "p05": "under_18",
        "p06": "no_recent_contact",  # last record 31 months ago
        "p07": "OPEN",               # never had a wellness visit
        "p08": "OPEN", "p09": "OPEN", "p10": "OPEN", "p11": "OPEN", "p13": "OPEN", "p14": "OPEN",
        "p12": "up_to_date",
        "p15": "OPEN",               # turns 18 on the snapshot date
        "p16": "not_born",
        "p17": "up_to_date",
    }


def test_ed_followup_rules(con):
    assert outcomes(con, "ed_followup_review", "encounter_id") == {
        "e09": "followed_up",  # follow-up exactly 14 days later
        "e11": "OPEN",         # follow-up one minute past 14 days
        "e13": "window_open",  # 14 days have not passed yet
        "e14": "admitted",     # inpatient stay the same evening
        "e18": "followed_up",  # virtual visit while the window is still open
    }  # e16 (obstetric) and e17 (before the 44-day lookback) are not candidates


def test_worklist_matches_open_rows(con):
    wl = warehouse.worklist(con, SNAPSHOT)
    assert sorted(wl[wl.opportunity == "ed_no_followup"].patient_id) == ["p09"]
    assert len(wl[wl.opportunity == "overdue_wellness"]) == 10
    assert wl.loc[wl.patient_id == "p01", "days_since"].item() == 457


def test_earlier_snapshot_ignores_later_events(con):
    warehouse.set_snapshot(con, "2025-06-30")
    rows = dict(con.execute("SELECT patient_id, exclusion FROM wellness_review").fetchall())
    assert rows["p04"] == "died" and rows["p16"] == "not_born"
    assert rows["p09"] == "no_recent_contact"  # its only visits are in December 2025
    assert list(warehouse.timeline(con, "p03", "2025-06-30").start_ts.astype(str)) == ["2024-01-01 10:00:00"]


def test_build_rejects_orphan_encounters(tmp_path):
    for f in FIXTURES.glob("*.csv"):
        shutil.copy(f, tmp_path)
    with open(tmp_path / "encounters.csv", "a") as fh:
        fh.write("e99,2025-01-01T10:00:00Z,2025-01-01T11:00:00Z,nobody,ambulatory,1,x,0\n")
    with pytest.raises(ValueError, match="encounters without a patient"):
        warehouse.build(tmp_path)


def test_features_stop_at_cutoff_and_label_starts_there(con):
    before = warehouse.model_rows(con, "2025-11-30").set_index("patient_id")
    after = warehouse.model_rows(con, "2025-12-31").set_index("patient_id")
    # p17's inpatient stay on 2025-12-01 is the label before it happens and a feature after
    assert (before.loc["p17", "acute_12m"], before.loc["p17", "label"]) == (0, 1)
    assert (after.loc["p17", "acute_12m"], after.loc["p17", "label"]) == (1, 0)
    # a delivery (obstetric emergency admission) is not acute use
    assert before.loc["p12", "label"] == 0
    # p13's emergency visit on 2025-11-10 is history at both snapshots
    assert before.loc["p13", "acute_12m"] == 1 and before.loc["p13", "label"] == 0


def test_capture_counts_ties_by_expected_share():
    import numpy as np
    from opsbench.evaluate import capture
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    assert capture(y, np.arange(10, 0, -1).astype(float)) == 0.5          # top 1 of 10 holds 1 of 2 positives
    assert capture(y, np.ones(10)) == 0.1                                  # all tied: 1 slot x 2/10 positives
    assert capture(y, np.array([2, 1, 1, 1, 1, 0, 0, 0, 0, 0.])) == 0.5     # clear winner, ties below
