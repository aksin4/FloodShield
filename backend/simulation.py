"""LISFLOOD-FP automation: scenario -> inputs (.par/.bci/.bdy) -> run -> rasters.

Solver: LISFLOOD-FP 8.1 'acceleration' (local-inertial 2D shallow-water
formulation, Bates et al. 2010) on the Copernicus GLO-30 DEM.
"""
import json
import math
import shutil
import subprocess
import time
import numpy as np
import rasterio
from pyproj import Transformer

from config import RUNS, MODEL, LISFLOOD_EXE, CRS_MODEL, RIVER_CROSSING, DAM_CREST
from breach import hydrograph

TO_UTM = Transformer.from_crs("EPSG:4326", CRS_MODEL, always_xy=True).transform


def breach_cells(width, res, offset=120.0):
    """Point-source cells on a line parallel to the dam crest, `offset` m
    downstream (NW) of the river crossing, spanning the breach width."""
    x0, y0 = TO_UTM(*RIVER_CROSSING)
    xa, ya = TO_UTM(*DAM_CREST[0]); xb, yb = TO_UTM(*DAM_CREST[-1])
    ux, uy = (xb - xa), (yb - ya)
    L = math.hypot(ux, uy); ux, uy = ux / L, uy / L         # along-crest unit vector
    nx, ny = -uy, ux                                        # normal (points NW = downstream)
    cx, cy = x0 + nx * offset, y0 + ny * offset
    n = max(1, int(round(width / res)))
    pts, seen = [], set()
    for k in range(n):
        s = (k - (n - 1) / 2) * res
        x, y = cx + ux * s, cy + uy * s
        key = (int(x // res), int(y // res))
        if key in seen:
            continue
        seen.add(key)
        pts.append(((key[0] + 0.5) * res, (key[1] + 0.5) * res))
    return pts


def run(scenario: dict, res=60, name=None, verbose=False):
    """Run one dam-break scenario. Returns metadata dict."""
    name = name or scenario.get("id", "scenario")
    rdir = RUNS / f"{name}_{res}m"
    if rdir.exists():
        shutil.rmtree(rdir)
    rdir.mkdir(parents=True)
    tdir = MODEL / "terrain"
    meta = json.loads((tdir / f"meta_{res}m.json").read_text())
    shutil.copy(tdir / f"dem_{res}m.asc", rdir / "dem.asc")

    t_end_h = scenario.get("t_end_h", 10.0)
    hy = hydrograph(wse0=scenario["wse0"], breach_width=scenario["breach_width"],
                    breach_bottom=scenario["breach_bottom"], tf_h=scenario["tf_h"],
                    inflow_peak=scenario.get("inflow_peak", 0.0),
                    inflow_tp_h=scenario.get("inflow_tp_h", 6.0), t_end_h=t_end_h)

    # ---- point sources & boundary file ----
    cells = breach_cells(max(scenario["breach_width"], 3 * res), res)
    per_width = hy["q"] / (len(cells) * res)  # m^2/s per point cell
    with open(rdir / "dam.bci", "w") as f:
        for x, y in cells:
            f.write(f"P {x:.1f} {y:.1f} QVAR breach\n")
        # open (free outflow) boundaries on the downstream edges
        f.write(f"N {meta['xll']} {meta['xll'] + meta['ncols'] * res} FREE\n")
        f.write(f"W {meta['yll']} {meta['top']} FREE\n")
        f.write(f"E {meta['yll']} {meta['top']} FREE\n")
    step = 6  # every 60 s
    idx = np.arange(0, len(hy["t"]), step)
    with open(rdir / "dam.bdy", "w") as f:
        f.write("FloodShield breach hydrograph (m2/s per unit width)\nbreach\n")
        f.write(f"{len(idx)} seconds\n")
        for i in idx:
            f.write(f"{per_width[i]:.5f} {hy['t'][i]:.0f}\n")

    saveint = scenario.get("saveint_s", 1800)
    par = f"""DEMfile dem.asc
resroot res
dirroot out
sim_time {int(t_end_h * 3600)}
initial_tstep 1.0
massint 600
saveint {saveint}
fpfric {scenario.get('manning', 0.06)}
acceleration
bcifile dam.bci
bdyfile dam.bdy
hazard
elevoff
"""
    (rdir / "run.par").write_text(par)

    t0 = time.time()
    proc = subprocess.run([str(LISFLOOD_EXE), "-v" if verbose else "", "run.par"],
                          cwd=rdir, capture_output=True, text=True)
    runtime = time.time() - t0
    (rdir / "lisflood.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0 or not (rdir / "out" / "res.max").exists():
        raise RuntimeError(f"LISFLOOD-FP failed: {proc.stderr[-800:]} {proc.stdout[-800:]}")

    info = dict(name=name, res=res, runtime_s=round(runtime, 1), scenario=scenario,
                n_source_cells=len(cells), peak_q=round(hy["peak_q"]),
                t_peak_h=round(hy["t_peak_h"], 2), released_mcm=round(hy["released_mcm"], 2),
                v0_mcm=round(hy["v0_mcm"], 2),
                hydrograph=dict(t_h=(hy["t"][::30] / 3600).round(3).tolist(),
                                q=hy["q"][::30].round(1).tolist(),
                                wse=hy["wse"][::30].round(2).tolist()))
    (rdir / "info.json").write_text(json.dumps(info, indent=1))
    return rdir, info


def read_asc(path):
    with open(path) as f:
        hdr = {}
        for _ in range(6):
            k, v = f.readline().split()
            hdr[k.lower()] = float(v)
        a = np.loadtxt(f, dtype="float32")
    return a, hdr


if __name__ == "__main__":
    import sys
    sc = dict(id="test", wse0=57.3, breach_width=140, breach_bottom=42.0, tf_h=2.5, t_end_h=6)
    rdir, info = run(sc, res=int(sys.argv[1]) if len(sys.argv) > 1 else 60, verbose=True)
    print(json.dumps({k: v for k, v in info.items() if k != "hydrograph"}, indent=1))
    print(sorted(p.name for p in (rdir / "out").iterdir())[:40])
