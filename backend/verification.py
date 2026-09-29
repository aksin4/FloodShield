"""Model verification report: mass conservation, grid convergence, 1979 plausibility.
Writes outputs/verification.json (shown on the dashboard 'Method & data' tab)."""
import json
import numpy as np
from config import RUNS, OUTPUTS, WET_THRESHOLD
from simulation import read_asc
from scenarios import SCENARIOS


def mass_balance(rdir):
    """Volume conservation: inflow in = stored + outflow out (from LISFLOOD-FP .mass)."""
    rows = []
    with open(rdir / "out" / "res.mass") as f:
        next(f)
        for line in f:
            p = line.split()
            if len(p) >= 9:
                rows.append([float(p[0]), float(p[5]), float(p[6]), float(p[8])])
    a = np.array(rows)
    t, vol, qin, qout = a.T
    dt = np.diff(t, prepend=0)
    vin = np.cumsum(qin * dt); vout = np.cumsum(qout * dt)
    released = vin[-1]
    stored_plus_out = vol[-1] + vout[-1]
    return dict(inflow_mcm=round(released / 1e6, 2), stored_mcm=round(vol[-1] / 1e6, 2),
                outflow_mcm=round(vout[-1] / 1e6, 2),
                error_pct=round(100 * (stored_plus_out - released) / released, 2))


def convergence(sid):
    out = {}
    for res in (60, 30):
        rd = RUNS / f"{sid}_{res}m"
        if not (rd / "out" / "res.max").exists():
            return None
        d, _ = read_asc(rd / "out" / "res.max")
        out[res] = float((d > WET_THRESHOLD).sum() * res * res / 1e6)
    return dict(area_60m=round(out[60], 2), area_30m=round(out[30], 2),
                diff_pct=round(100 * (out[60] - out[30]) / out[30], 1))


def build():
    rep = dict(mass_balance={}, convergence={}, validation_1979=None)
    for s in SCENARIOS:
        for res in (30, 60):
            rd = RUNS / f"{s['id']}_{res}m"
            if (rd / "info.json").exists():
                rep["mass_balance"][f"{s['id']}_{res}m"] = mass_balance(rd)
        c = convergence(s["id"])
        if c:
            rep["convergence"][s["id"]] = c
    f = OUTPUTS / "scenarios" / "S3_extreme" / "summary.json"
    if f.exists():
        m = json.loads(f.read_text())
        morbi = next((p for p in m["places"] if p["name"] == "Morbi"), None)
        lil = next((p for p in m["places"] if p["name"] == "Lilapar"), None)
        rep["validation_1979"] = dict(
            observed="Morbi flood depth 3.7-9.1 m; low-lying areas flooded within ~20 min of the wave "
                     "reaching the town; Lilapar (next to the dam) completely inundated",
            model_morbi_depth_m=morbi and morbi["depth"], model_morbi_arrival_min=morbi and round(morbi["arrival_h"] * 60),
            model_lilapar_depth_m=lil and lil["depth"],
            within_range=bool(morbi and 3.7 <= morbi["depth"] <= 9.1), res=m["res"])
    sar = OUTPUTS / "sar" / "s1_flood_20240902.tif"
    s0 = OUTPUTS / "scenarios" / "S0_release" / "max_depth.tif"
    if sar.exists() and s0.exists():
        import rasterio
        from scipy import ndimage
        obs = rasterio.open(sar).read(1) == 1
        mod = rasterio.open(s0).read(1) > WET_THRESHOLD
        if obs.shape == mod.shape:
            corridor = ndimage.binary_dilation(mod, iterations=int(1000 / 30))
            hit = obs & ndimage.binary_dilation(mod, iterations=2)
            rep["sar_check"] = dict(
                event="Aug-2024 Machhu-2 gate release (S0) vs Sentinel-1 2 Sep 2024",
                sar_pixels_in_corridor=int((obs & corridor).sum()),
                captured_by_model_pct=round(100 * hit.sum() / max((obs & corridor).sum(), 1), 1),
                sar_pixels_outside_corridor_pct=round(100 * (obs & ~corridor).sum() / max(obs.sum(), 1), 1),
                note="SAR image is ~5 days after the release peak (residual water only), so this "
                     "measures hit rate, not false alarms.")
    (OUTPUTS / "verification.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    build()
