"""Review worklist demo over the synthetic population.

Run: python -m opsbench <csv_dir> 2025-12-31 data/out && streamlit run app.py -- data/out
"""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from opsbench import warehouse

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/out")
LABELS = {"overdue_wellness": "Overdue wellness visit (adults, none in 15 months)",
          "ed_no_followup": "Emergency visit without follow-up in 14 days"}

st.set_page_config(page_title="OperationsBench", layout="wide")
st.title("OperationsBench")
st.caption("Synthetic demonstration. Synthea patients, not real people. "
           "Illustrative care opportunities, not validated quality measures.")

snapshots = sorted(p.stem.removeprefix("worklist_") for p in OUT.glob("worklist_*.csv"))
if not snapshots:
    st.error(f"No worklist in {OUT}. Run `python -m opsbench <csv_dir> 2025-12-31 {OUT}` first.")
    st.stop()
snapshot = st.sidebar.selectbox("Snapshot date", snapshots, index=len(snapshots) - 1)
worklist = pd.read_csv(OUT / f"worklist_{snapshot}.csv")
funnel = pd.read_csv(OUT / f"funnel_{snapshot}.csv")


@st.cache_resource
def connect():
    return duckdb.connect(str(OUT / "warehouse.duckdb"), read_only=True)


queue_tab, model_tab = st.tabs(["Review queues", "Risk ranking experiment"])
with queue_tab:
    for key, label in LABELS.items():
        rows = worklist[worklist.opportunity == key]
        st.subheader(f"{label}: {len(rows)} open")
        st.dataframe(funnel[funnel.opportunity == key][["outcome", "n"]], hide_index=True)
        pick = st.dataframe(rows.drop(columns="opportunity"), hide_index=True, on_select="rerun",
                            selection_mode="single-row", key=key)
        if pick.selection.rows:
            patient = rows.iloc[pick.selection.rows[0]]
            st.markdown(f"**{patient.first_name} {patient.last_name}**, age {patient.age}: encounters in the "
                        f"24 months before {snapshot}")
            st.dataframe(warehouse.timeline(connect(), patient.patient_id, snapshot), hide_index=True)

with model_tab:
    path = OUT / "evaluation.json"
    if path.exists():
        result = json.loads(path.read_text())
        st.write("Results on a synthetic population. They measure the generator, not deployment readiness.")
        st.json(result)
    else:
        st.info("Run `python -m opsbench.evaluate <csv_dir> <out_dir>` to add the experiment.")
