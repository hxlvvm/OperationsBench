-- Model rows for one snapshot (params table): features use only events before the cutoff, the label only
-- events in the 365 days after it. Obstetric emergency admissions (deliveries) are not counted as acute use.

-- grain: one row per encounter, with the acute flag used by both features and label
CREATE OR REPLACE VIEW encounters_flagged AS
SELECT *,
       (encounter_class = 'inpatient' OR (encounter_class = 'emergency' AND description NOT ILIKE '%obstetric%'))
           AS is_acute
FROM encounters;

-- grain: one row per eligible patient (cohort exclusion IS NULL)
CREATE OR REPLACE VIEW model_rows AS
WITH hist AS (
    SELECT e.patient_id,
           count(*) FILTER (WHERE e.is_acute AND e.start_ts >= a.cutoff - INTERVAL 12 MONTH) AS acute_12m,
           count(*) FILTER (WHERE e.is_acute AND e.start_ts < a.cutoff - INTERVAL 12 MONTH
                                             AND e.start_ts >= a.cutoff - INTERVAL 24 MONTH) AS acute_12_24m,
           count(*) FILTER (WHERE e.encounter_class = 'urgentcare' AND e.start_ts >= a.cutoff - INTERVAL 12 MONTH)
               AS urgent_12m,
           count(*) FILTER (WHERE e.encounter_class IN ('ambulatory', 'outpatient', 'virtual')
                                  AND e.start_ts >= a.cutoff - INTERVAL 12 MONTH) AS office_12m,
           count(*) FILTER (WHERE e.encounter_class = 'wellness' AND e.start_ts >= a.cutoff - INTERVAL 24 MONTH)
               AS wellness_24m,
           count(*) FILTER (WHERE e.encounter_class IN ('home', 'hospice', 'snf')
                                  AND e.start_ts >= a.cutoff - INTERVAL 24 MONTH) AS post_acute_24m,
           coalesce(sum(e.claim_cost) FILTER (WHERE e.start_ts >= a.cutoff - INTERVAL 12 MONTH), 0) AS cost_12m,
           date_diff('day', max(e.start_ts) FILTER (WHERE e.is_acute), a.cutoff) AS days_since_acute
    FROM encounters_flagged e, as_of a
    WHERE e.start_ts < a.cutoff
    GROUP BY e.patient_id, a.cutoff
),
active AS (
    SELECT c.patient_id, count(DISTINCT c.code) AS n_active_disorders
    FROM conditions c, as_of a
    WHERE c.start_date <= a.snapshot AND (c.stop_date IS NULL OR c.stop_date > a.snapshot)
      AND c.description ILIKE '%(disorder)%'
    GROUP BY 1
),
outcome AS (
    SELECT e.patient_id, count(*) AS acute_next_365d
    FROM encounters_flagged e, as_of a
    WHERE e.is_acute AND e.start_ts >= a.cutoff AND e.start_ts < a.cutoff + INTERVAL 365 DAY
    GROUP BY 1
)
SELECT c.patient_id, a.snapshot, c.age, (c.gender = 'F')::INT AS female,
       h.acute_12m, h.acute_12_24m, h.urgent_12m, h.office_12m, h.wellness_24m, h.post_acute_24m,
       ln(1 + h.cost_12m) AS log_cost_12m,
       least(coalesce(h.days_since_acute, 3650), 3650) AS days_since_acute,
       coalesce(d.n_active_disorders, 0) AS n_active_disorders,
       (coalesce(o.acute_next_365d, 0) > 0)::INT AS label
FROM cohort c CROSS JOIN as_of a
JOIN hist h USING (patient_id)
LEFT JOIN active d USING (patient_id)
LEFT JOIN outcome o USING (patient_id)
WHERE c.exclusion IS NULL;
