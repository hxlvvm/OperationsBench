# OperationsBench

A care-operations worklist built in SQL over a synthetic patient population. It answers two questions a
care-coordination team asks every morning:

- Which adults are overdue for a wellness visit?
- Which emergency-department patients never got a follow-up visit?

Every patient on a list links to the encounters behind it, and every excluded patient keeps the reason.

On top of the queues sits one pre-registered experiment: does a learned risk ranking find more patients with
future acute care than ranking by past acute care?

**Result.** All numbers are on synthetic Synthea patients (snapshot 2025-12-31, 10,000 patients):
- **Queues:** 1,243 adults overdue for a wellness visit and 86 emergency visits with no follow-up.
- **Tests:** 7 of 7 golden-fixture tests pass, covering the date-boundary rules.
- **Experiment:** reviewing the top 10% of 1,921 held-out patients one year later caught **29.1%** of future acute
  care with logistic regression, against **20.8%** when ranking by prior acute use. The 95% CI for the difference
  is +3.6 to +12.3 points.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                                   # golden fixtures, no data needed

# Data: Synthea v4.0.0 (Java 17), about 7 minutes on 8 cores with a 9 GB heap for 10,000 patients
curl -L -o synthea.jar https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
JAVA_XMX=9g scripts/generate.sh synthea.jar data/synthea 10000

.venv/bin/python -m opsbench data/synthea/csv 2025-12-31 data/out    # warehouse, worklist, funnel
.venv/bin/python -m opsbench.evaluate data/synthea/csv data/out       # the experiment
.venv/bin/streamlit run app.py -- data/out
```

Same seed, same data: two 1,000-patient runs gave identical rows in every CSV checked.

## How it works

`opsbench/sql/staging.sql` loads the Synthea CSVs into typed DuckDB tables:
- every column is read as text and cast explicitly, so SNOMED codes stay strings and timestamps are UTC;
- each table states its grain.

The build stops if any data check fails:
- duplicate keys;
- orphan encounters or conditions;
- encounters ending before they start;
- encounters before birth.

The last check caught a real generator problem (below).

`opsbench/sql/opportunities.sql` is the review logic, as of one snapshot date. An event counts if it starts
before the end of that day.

| View | Grain | Rule | Exclusion reasons |
|---|---|---|---|
| `cohort` | patient | born, alive, any encounter in 24 months | `not_born`, `died`, `no_recent_contact` |
| `wellness_review` | patient | adult, last wellness visit more than 15 months ago or never | + `under_18`, `up_to_date` |
| `ed_followup_review` | emergency visit | non-obstetric emergency visit in the last 44 days, no ambulatory, outpatient, wellness or virtual visit within 14 days | + `admitted`, `followed_up`, `window_open` |

Each candidate keeps the first reason that applies, so the funnel adds up.
- Overdue wellness, snapshot 2025-12-31: 11,523 patients → 1,243 open, 6,512 `up_to_date`, 2,082 `under_18`,
  1,523 `died`, 163 `no_recent_contact` (`results/funnel_2025-12-31.csv`).
- `no_recent_contact` exists because a missing record proves nothing about a patient who may get care elsewhere.

`tests/fixtures/` holds 17 hand-written patients, each on one boundary:
- a wellness visit exactly 15 months back, and one a day earlier;
- a visit after the snapshot, which must not count;
- a follow-up at 14 days, and one at 14 days and one minute;
- an inpatient stay the same evening;
- a delivery;
- someone who turns 18 on the snapshot date;
- an event that is the label before the cutoff and a feature after it.

## The experiment

The plan in `DESIGN.md` was committed before the test snapshot was scored, and the test was scored once.

- **Label:** any inpatient or non-obstetric emergency encounter in the 365 days after the cutoff.
- **Features:** only events before the cutoff: encounter counts by type, claim cost, days since the last acute
  encounter, number of active disorders, age and sex.
- **Split:** train and select on the 2023-12-31 snapshot (patient buckets 0-79), then test on the 2024-12-31
  snapshot (buckets 80-99). The test is a later year and has unseen patients.

| Test, 2024-12-31 snapshot (1,921 patients, 265 with acute care) | Top-10% capture | Average precision | AUROC |
|---|---|---|---|
| Prior acute use (baseline) | 20.8% | 0.231 | 0.596 |
| Logistic regression, C = 1 (best of 4 on validation) | 29.1% | 0.333 | 0.666 |
| Difference, 95% paired-bootstrap CI | +3.6 to +12.3 pts | +0.064 to +0.144 | |

The gradient-boosted tree did worse on validation (AP 0.205 vs 0.236), so the simpler model was chosen. The
pre-registered rule adopts the model, because the CI excludes zero. It is not yet wired into a live queue. Full
output: `results/evaluation.json`.

## Limitations

- **Synthetic data.** The model learns Synthea's disease modules, not real care patterns. The numbers show the
  pipeline works and the evaluation is honest. They say nothing about real patients.
- **Illustrative rules.** The queues are care opportunities, not HEDIS or CMS measures. Urgent-care visits do not
  count as follow-up after an emergency visit, by design. In this snapshot no emergency visit was followed by an
  inpatient stay within a day, so `admitted` is 0.
- **Dropped query.** Diabetics without an HbA1c in 12 months was considered and dropped: Synthea schedules the
  test, and only 2 of 66 pilot diabetics were overdue.
- **Generator time zone.** Synthea writes birth dates in the JVM's time zone and timestamps in UTC. On a
  Berlin-time machine, 8 of 1,155 pilot patients had a newborn visit dated the day before birth. `scripts/generate.sh` runs the JVM
  in UTC.

## Data and licences

- **Code:** MIT.
- **Synthea:** Apache-2.0.
- **Generated data is not in this repo.** It carries SNOMED CT and LOINC codes under the terms in Synthea's
  NOTICE. Regenerate it with `scripts/generate.sh`.
- **Committed outputs:** `results/` holds only counts and metrics.
