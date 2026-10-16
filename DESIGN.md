# Design and pre-registered evaluation

Written before the test snapshot was scored. Changes after scoring are listed at the end with their date.

## Data

- Synthea v4.0.0 (Apache-2.0), Massachusetts, seed 20261016, 10,000 living patients, reference and end date
  2026-01-01, 10 years of history, CSV export (`scripts/generate.sh`).
- The JVM runs in UTC. Synthea writes birth dates in the JVM's time zone but timestamps in UTC. On a Berlin-time
  machine, 8 of 1,155 pilot patients had a newborn visit dated the day before birth. The data check
  `encounters before birth` caught this.
- Two 1,000-patient runs with the same seed gave identical rows in patients, encounters, conditions and
  observations (compared after sorting).
- Generated data is not committed. The CSVs carry SNOMED CT and LOINC codes, and Synthea's NOTICE puts SNOMED CT use
  under fair use and the IHTSDO affiliate terms. The repo therefore ships the generator settings and hand-written
  fixtures only, and `scripts/generate.sh` rebuilds the data.

## Pilot findings that shaped the queries (1,000-patient pilot)

- About 15% of patients have an emergency or inpatient encounter in a given year, so 10,000 patients give roughly
  1,400 positives a year and about 280 in a 20% test split.
- Diabetics without an HbA1c in 12 months: 2 of 66. Synthea schedules the test, so the query would only show
  the generator's schedule. Dropped.
- Adults with no wellness visit in 15 months: 17%. Emergency visits with no follow-up in 14 days: 84%. Kept.
- 340 of 2,442 emergency encounters are obstetric emergency admissions (deliveries). They are not counted as
  acute use or as emergency visits needing follow-up.

## Review queries (deterministic, `opsbench/sql/opportunities.sql`)

As of a snapshot date, events count if they start before the end of that day. Every candidate keeps the first
exclusion reason that applies, so the funnel adds up.

- **Cohort:** born, alive at the snapshot, and at least one encounter in the last 24 months. Without a recent
  record, a missing visit says nothing about the patient's care.
- **Overdue wellness visit:** adults (18+ at the snapshot) whose last wellness visit is more than 15 months before
  the cutoff, or who have never had one.
- **Emergency visit without follow-up:** non-obstetric emergency visits in the 44 days before the cutoff, with no
  ambulatory, outpatient, wellness or virtual visit within 14 days. Excluded: inpatient admission within 1 day
  (`admitted`), follow-up found (`followed_up`), and 14 days not yet passed (`window_open`).

These are illustrative care opportunities, not validated quality measures (HEDIS or CMS).

## Model evaluation (`opsbench/evaluate.py`)

- **Question:** at a fixed review budget of the top 10% of eligible patients, does a learned ranking find more
  patients with future acute use than ranking by prior acute use?
- **Label:** any inpatient or non-obstetric emergency encounter in the 365 days after the cutoff.
- **Features:** only events before the cutoff. Age, sex, and counts of acute, urgent-care, office, wellness and
  post-acute encounters. Also log claim cost over 12 months, days since the last acute encounter, and the number of
  active disorders.
- **Split:** patients are split by a hash of their ID, so each patient sits in the same split at every snapshot.
  - Train: snapshot 2023-12-31, buckets 0-59.
  - Validation: snapshot 2023-12-31, buckets 60-79.
  - Test: snapshot 2024-12-31, buckets 80-99. The test is later in time and has unseen patients.
- **Candidates:**
  - logistic regression with C = 0.01, 0.1 or 1;
  - a histogram gradient-boosted tree with default settings.

  Fitted on train. The model with the best validation average precision is chosen.
- **Baseline:** acute encounters in the last 12 months, with the 12 months before that as a tie-break. Ties at the
  budget threshold count by expected share.
- **Test metrics:** AUROC, average precision, and the share of positives captured in the top 10%. The Brier score
  is reported for the model only.
  - Uncertainty comes from a paired bootstrap over test patients: 2,000 resamples, seed 0.
- **Decision rule:** the worklist uses the model only if the lower end of the 95% CI of (model capture − baseline
  capture) is above 0. Otherwise the model is not adopted and the README says so.
- **Test runs:** the test snapshot is scored once. All results are on a synthetic population and say nothing about
  real patients.

## Changes after scoring

- 2026-10-16: corrected the wording of the determinism and time-zone notes. The evaluation is unchanged.
