"""Build the warehouse and export the review worklist for one snapshot.

Usage: python -m opsbench <csv_dir> <snapshot YYYY-MM-DD> <out_dir>
"""
import sys
from pathlib import Path

from opsbench import warehouse

csv_dir, snapshot, out_dir = sys.argv[1:4]
out = Path(out_dir)
out.mkdir(parents=True, exist_ok=True)
con = warehouse.build(csv_dir, out / "warehouse.duckdb")
warehouse.worklist(con, snapshot).to_csv(out / f"worklist_{snapshot}.csv", index=False)
funnel = warehouse.funnel(con, snapshot)
funnel.to_csv(out / f"funnel_{snapshot}.csv", index=False)
print(funnel.to_string(index=False))
