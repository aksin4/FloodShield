"""Post-batch: re-analyse 30 m runs with latest impact code, run S0 at 30 m, rebuild verification."""
from impact import analyse
from scenarios import SCENARIOS, BY_ID
from simulation import run
from config import RUNS
import verification
s = BY_ID["S0_release"]
r, i = run(s, res=30, name=s["id"])
for s in SCENARIOS:
    d = RUNS / f"{s['id']}_30m"
    if (d / "info.json").exists():
        m = analyse(d, 30, s["id"], s["label"])
        print(s["id"], m["flood"]["area_km2"], m["buildings"]["total"], flush=True)
verification.build()
