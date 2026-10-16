-- Typed staging tables over the Synthea CSV export. Every column is read as text and cast here, so a
-- code like 44054006 never becomes an integer and timestamps are always UTC.

-- grain: one row per patient
CREATE OR REPLACE TABLE patients AS
SELECT Id AS patient_id,
       FIRST AS first_name,
       LAST AS last_name,
       GENDER AS gender,
       BIRTHDATE::DATE AS birth_date,
       DEATHDATE::DATE AS death_date
FROM read_csv('{csv}/patients.csv', all_varchar = true);

-- grain: one row per encounter
CREATE OR REPLACE TABLE encounters AS
SELECT Id AS encounter_id,
       PATIENT AS patient_id,
       ENCOUNTERCLASS AS encounter_class,
       CODE AS code,
       DESCRIPTION AS description,
       START::TIMESTAMPTZ::TIMESTAMP AS start_ts,
       STOP::TIMESTAMPTZ::TIMESTAMP AS stop_ts,
       TOTAL_CLAIM_COST::DOUBLE AS claim_cost
FROM read_csv('{csv}/encounters.csv', all_varchar = true);

-- grain: one row per condition episode (a patient can have the same code more than once)
CREATE OR REPLACE TABLE conditions AS
SELECT PATIENT AS patient_id,
       ENCOUNTER AS encounter_id,
       CODE AS code,
       DESCRIPTION AS description,
       START::DATE AS start_date,
       STOP::DATE AS stop_date
FROM read_csv('{csv}/conditions.csv', all_varchar = true);
