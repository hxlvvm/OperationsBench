-- Review views for one snapshot date, read from the one-row params table.
-- "As of the snapshot" means events that start before the end of that day (start_ts < cutoff).
-- Each view keeps every candidate row with the first exclusion reason that applies, and exclusion IS NULL is
-- an open opportunity. These are illustrative care opportunities, not validated quality measures.

CREATE OR REPLACE TABLE params AS SELECT NULL::DATE AS snapshot;

CREATE OR REPLACE VIEW as_of AS
SELECT snapshot, snapshot + INTERVAL 1 DAY AS cutoff FROM params;

-- grain: one row per patient
CREATE OR REPLACE VIEW cohort AS
WITH last_contact AS (
    SELECT e.patient_id, max(e.start_ts) AS last_contact
    FROM encounters e, as_of a
    WHERE e.start_ts < a.cutoff
    GROUP BY 1
)
SELECT p.patient_id, p.first_name, p.last_name, p.gender,
       date_diff('year', p.birth_date, a.snapshot)
           - (strftime(a.snapshot, '%m%d') < strftime(p.birth_date, '%m%d'))::INT AS age,
       l.last_contact,
       CASE WHEN p.birth_date > a.snapshot THEN 'not_born'
            WHEN p.death_date <= a.snapshot THEN 'died'
            -- no record in 24 months: the patient may get care elsewhere, so a missing visit proves nothing
            WHEN l.last_contact IS NULL OR l.last_contact < a.cutoff - INTERVAL 24 MONTH THEN 'no_recent_contact'
       END AS exclusion
FROM patients p CROSS JOIN as_of a
LEFT JOIN last_contact l USING (patient_id);

-- Adults with no wellness visit in the 15 months before the snapshot.
-- grain: one row per patient
CREATE OR REPLACE VIEW wellness_review AS
WITH last_wellness AS (
    SELECT e.patient_id, max(e.start_ts) AS last_wellness
    FROM encounters e, as_of a
    WHERE e.encounter_class = 'wellness' AND e.start_ts < a.cutoff
    GROUP BY 1
)
SELECT c.patient_id, w.last_wellness,
       CASE WHEN c.exclusion IS NOT NULL THEN c.exclusion
            WHEN c.age < 18 THEN 'under_18'
            WHEN w.last_wellness >= a.cutoff - INTERVAL 15 MONTH THEN 'up_to_date'
       END AS exclusion
FROM cohort c CROSS JOIN as_of a
LEFT JOIN last_wellness w USING (patient_id);

-- Emergency visits in the 44 days before the snapshot with no ambulatory, outpatient, wellness or virtual
-- visit within 14 days. Obstetric emergency admissions (deliveries) are left out.
-- grain: one row per emergency encounter
CREATE OR REPLACE VIEW ed_followup_review AS
WITH ed AS (
    SELECT e.encounter_id, e.patient_id, e.start_ts AS ed_ts
    FROM encounters e, as_of a
    WHERE e.encounter_class = 'emergency'
      AND e.description NOT ILIKE '%obstetric%'
      AND e.start_ts >= a.cutoff - INTERVAL 44 DAY AND e.start_ts < a.cutoff
),
after_ed AS (
    SELECT ed.encounter_id,
           min(f.start_ts) FILTER (WHERE f.encounter_class IN ('ambulatory', 'outpatient', 'wellness', 'virtual'))
               AS first_followup,
           bool_or(f.encounter_class = 'inpatient' AND f.start_ts <= ed.ed_ts + INTERVAL 1 DAY) AS admitted
    FROM ed CROSS JOIN as_of a
    JOIN encounters f ON f.patient_id = ed.patient_id
     AND f.start_ts > ed.ed_ts AND f.start_ts <= ed.ed_ts + INTERVAL 14 DAY
     AND f.start_ts < a.cutoff  -- never look past the snapshot
    GROUP BY 1
)
SELECT ed.encounter_id, ed.patient_id, ed.ed_ts, n.first_followup,
       CASE WHEN c.exclusion IS NOT NULL THEN c.exclusion
            WHEN n.admitted THEN 'admitted'
            WHEN n.first_followup IS NOT NULL THEN 'followed_up'
            WHEN ed.ed_ts + INTERVAL 14 DAY >= a.cutoff THEN 'window_open'
       END AS exclusion
FROM ed CROSS JOIN as_of a
JOIN cohort c USING (patient_id)
LEFT JOIN after_ed n USING (encounter_id);
