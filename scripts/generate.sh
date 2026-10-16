#!/usr/bin/env bash
# Generate the synthetic population with pinned Synthea settings.
# Usage: scripts/generate.sh <synthea.jar> <out_dir> <population> [seed]
set -euo pipefail
JAR=$1 OUT=$2 POP=$3 SEED=${4:-20261016}
# Pinned: Synthea v4.0.0, fixed reference and end date (Synthea simulates up to "now" otherwise), CSV only.
# UTC JVM: Synthea writes birth dates in the JVM time zone but timestamps in UTC.
java -Xmx${JAVA_XMX:-6g} -Duser.timezone=UTC -jar "$JAR" \
  -s "$SEED" -cs "$SEED" -p "$POP" -r 20260101 -e 20260101 \
  --exporter.baseDirectory="$OUT" \
  --exporter.csv.export=true --exporter.fhir.export=false \
  --exporter.hospital.fhir.export=false --exporter.practitioner.fhir.export=false \
  --exporter.years_of_history=10 \
  Massachusetts
